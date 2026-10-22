"""Прозрачность ML-модели: журнал прогнозов (logs/predictions.csv) и живая статистика «Внутри модели».

Модуль только НАБЛЮДАЕТ за ИИ-трейдером: читает его признаки, прогноз и заявки после каждого шага и ничего не
меняет в торговой логике. Фактическое движение цены записывается строго ПОСЛЕ того, как пройдёт горизонт прогноза
(по умолчанию 3 с): до этого момента строка лежит в очереди и в журнал не попадает.
"""
from __future__ import annotations

import csv
import math
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from .ai_trader import AI_ID, IDX
from .features import FEATURES

NEUTRAL_BPS = 0.5      # |прогноз| меньше этого — «нейтральный», в точность направления не входит
BUCKET_SEC = 5         # точки графика «прогноз vs факт» усредняются по 5 с (как свечи)
CHART_POINTS = 120     # 10 минут

CSV_COLUMNS = (
    ["time_utc", "sim_time_s", "mode", "mid"]
    + FEATURES
    + ["pred_model_bps", "pred_used_bps", "shift_bps", "skew_bps", "half_bps", "ai_spread_bps",
       "bid", "ask", "bid_offset_bps", "ask_offset_bps", "position_btc", "horizon_s",
       "mid_after", "actual_move_bps", "direction_hit"]
)


def _r(v: Optional[float], d: int = 5):
    return "" if v is None else round(float(v), d)


class ExplainTracker:
    """Собирает по каждому шагу ИИ строку журнала, дозревает её через `horizon_sec` и ведёт живую статистику."""

    def __init__(self, horizon_sec: float = 3.0, log_path: Optional[str] = None, t0_wall: int = 0,
                 log_every: int = 1):
        self.horizon_sec = horizon_sec
        self.N = max(1, int(round(horizon_sec * 10)))
        self.t0_wall = t0_wall
        self.log_every = max(1, log_every)
        self.pending: deque = deque()
        self.last_count = -1
        self.cur: Optional[dict] = None
        # точность
        self.rows_total = 0       # зрелых строк с прогнозом
        self.n_dir = 0            # направление оценено (прогноз не нейтральный, факт != 0)
        self.hits = 0
        self.n_neutral = 0
        self.recent: deque = deque(maxlen=100)
        self._s = [0.0] * 6       # n, Σp, Σa, Σp², Σa², Σpa — для корреляции
        self._abs_err = 0.0
        self._abs_zero = 0.0
        # график
        self.chart: deque = deque(maxlen=CHART_POINTS)
        self._acc_idx: Optional[int] = None
        self._acc = [0.0, 0.0, 0]
        # журнал
        self.csv_path = log_path
        self.rows_written = 0
        self._f = None
        self._w = None
        if log_path:
            self._open(log_path)

    # ---------- файл ----------
    def _open(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 200:  # журнал прошлой сессии не затираем
            stamp = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y%m%d_%H%M%S")
            base, ext = os.path.splitext(path)
            os.replace(path, f"{base}_{stamp}{ext}")
        self._f = open(path, "w", newline="", encoding="utf-8-sig")
        self._w = csv.writer(self._f)
        self._w.writerow(CSV_COLUMNS)
        self._f.flush()

    def flush(self) -> None:
        if self._f and not self._f.closed:
            self._f.flush()

    def close(self) -> None:
        if self._f and not self._f.closed:
            self._f.flush()
            self._f.close()

    # ---------- шаг ----------
    def on_tick(self, sim) -> None:
        ai = sim.ai
        if ai is None or not ai.active or ai.last_x is None or ai.fb.n_updates == self.last_count:
            return  # ИИ не сделал нового шага (пустой стакан и т.п.)
        self.last_count = ai.fb.n_updates
        x = ai.last_x
        cfg = ai.cfg
        mid = ai.mid
        have_pred = ai.model is not None and ai.fb.ready
        pred_raw = float(ai.pred_raw) if have_pred else None
        pred_used = float(ai.pred) if have_pred else None
        quoting = ai.mode in ("quoting", "caution", "recovery")
        bid = ask = None
        for o in sim.ex.open_orders(AI_ID):
            if o.side == "buy" and (bid is None or o.price > bid):
                bid = o.price
            elif o.side == "sell" and (ask is None or o.price < ask):
                ask = o.price
        skew = cfg.gamma * ai.sigma ** 2 * cfg.tau * ai.q if quoting else None
        shift = cfg.pred_gain * pred_used if (pred_used is not None and quoting) else None
        w = sim.ex.wallets[AI_ID]
        row = {
            "tick": sim.tick_i, "sim_t": sim.now, "mode": ai.mode, "mid": mid,
            "features": [float(v) for v in x], "pred_raw": pred_raw, "pred_used": pred_used,
            "shift": shift, "skew": skew, "half": ai.half if quoting else None,
            "widen": cfg.pred_widen * abs(pred_used) / 10.0 * 100 if (pred_used is not None and quoting) else None,
            "bid": bid, "ask": ask, "pos": w.btc_total,
            "bid_off": (bid / mid - 1) * 1e4 if bid else None,
            "ask_off": (ask / mid - 1) * 1e4 if ask else None,
        }
        self.cur = row
        self.pending.append(row)
        # дозревание: факт известен только через N шагов
        while self.pending and sim.tick_i - self.pending[0]["tick"] >= self.N:
            self._finish(self.pending.popleft(), mid, sim)

    def _finish(self, row: dict, mid_after: float, sim) -> None:
        actual = (mid_after / row["mid"] - 1) * 1e4
        p = row["pred_raw"]
        hit = None
        if p is not None:
            self.rows_total += 1
            s = self._s
            s[0] += 1; s[1] += p; s[2] += actual; s[3] += p * p; s[4] += actual * actual; s[5] += p * actual
            self._abs_err += abs(actual - p)
            self._abs_zero += abs(actual)
            if abs(p) < NEUTRAL_BPS:
                self.n_neutral += 1
            elif actual != 0:
                hit = 1 if (p > 0) == (actual > 0) else 0
                self.n_dir += 1
                self.hits += hit
                self.recent.append(hit)
            self._bucket(row["sim_t"], p, actual)
        row["actual"], row["mid_after"], row["hit"] = actual, mid_after, hit
        if self._w is not None and (row["tick"] % self.log_every == 0):
            self._write(row)

    def _write(self, r: dict) -> None:
        ts = datetime.fromtimestamp(self.t0_wall + r["sim_t"], tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-5]
        half = r["half"]
        out = [ts, round(r["sim_t"], 1), r["mode"], _r(r["mid"], 2)]
        out += [_r(v) for v in r["features"]]
        out += [_r(r["pred_raw"]), _r(r["pred_used"]), _r(r["shift"]), _r(r["skew"]), _r(half),
                _r(2 * half if half is not None else None), _r(r["bid"], 2), _r(r["ask"], 2),
                _r(r["bid_off"]), _r(r["ask_off"]), _r(r["pos"], 6), self.horizon_sec,
                _r(r["mid_after"], 2), _r(r["actual"]), "" if r["hit"] is None else r["hit"]]
        self._w.writerow(out)
        self.rows_written += 1
        if self.rows_written % 200 == 0:
            self._f.flush()

    # ---------- график «прогноз vs факт» ----------
    def _bucket(self, sim_t: float, pred: float, actual: float) -> None:
        idx = int(sim_t // BUCKET_SEC)
        if self._acc_idx is None:
            self._acc_idx = idx
        if idx != self._acc_idx:
            self._push_bucket()
            self._acc_idx, self._acc = idx, [0.0, 0.0, 0]
        self._acc[0] += pred
        self._acc[1] += actual
        self._acc[2] += 1

    def _push_bucket(self) -> None:
        n = self._acc[2]
        if n:
            self.chart.append({"time": self.t0_wall + self._acc_idx * BUCKET_SEC,
                               "pred": self._acc[0] / n, "actual": self._acc[1] / n})

    def chart_points(self, last: Optional[int] = None) -> list:
        pts = list(self.chart)
        if self._acc_idx is not None and self._acc[2]:
            n = self._acc[2]
            pts.append({"time": self.t0_wall + self._acc_idx * BUCKET_SEC,
                        "pred": self._acc[0] / n, "actual": self._acc[1] / n})
        return pts[-last:] if last else pts

    # ---------- сводка точности ----------
    def accuracy(self) -> dict:
        n, sp, sa, spp, saa, spa = self._s
        corr = None
        if n > 5:
            vp, va = spp - sp * sp / n, saa - sa * sa / n
            if vp > 1e-12 and va > 1e-12:
                corr = (spa - sp * sa / n) / math.sqrt(vp * va)
        return {
            "n_dir": self.n_dir, "hits": self.hits,
            "pct": self.hits / self.n_dir * 100 if self.n_dir else None,
            "recent_n": len(self.recent),
            "recent_pct": sum(self.recent) / len(self.recent) * 100 if self.recent else None,
            "neutral": self.n_neutral, "total": self.rows_total, "corr": corr,
            "mae": self._abs_err / n if n else None, "mae_zero": self._abs_zero / n if n else None,
        }

    def view(self) -> Optional[dict]:
        r = self.cur
        if r is None:
            return None
        half = r["half"]
        return {
            "features": dict(zip(FEATURES, r["features"])), "mode": r["mode"],
            "pred_model": r["pred_raw"], "pred_used": r["pred_used"], "shift": r["shift"], "skew": r["skew"],
            "half": half, "spread": 2 * half if half is not None else None, "widen_pct": r["widen"],
            "bid": r["bid"], "ask": r["ask"], "bid_off": r["bid_off"], "ask_off": r["ask_off"],
            "pos": r["pos"], "acc": self.accuracy(), "rows": self.rows_written,
            "chart": self.chart_points(4),
        }
