"""Симуляция рынка: часы, «справедливая цена», толпа ботов, ИИ-трейдер, свечи и учёт результатов ИИ."""
from __future__ import annotations

import math
import random
import time as _time
from collections import deque
from typing import Optional

from .agents import DT, build_crowd
from .ai_trader import AI_ID, AIConfig, Gateway, MarketMaker, PriceModel
from .engine import Exchange
from .explain import ExplainTracker

START_PRICE = 65000.0
CANDLE_SEC = 5
WARMUP_TICKS = 300


class Simulation:
    def __init__(self, seed: int = 1, ai_mode: str = "ml", model: Optional[PriceModel] = None,
                 start_price: float = START_PRICE, whale_gap: float = 150.0,
                 random_shocks_per_hour: float = 0.0, ai_cfg: Optional[AIConfig] = None,
                 maker_fee: float = 0.0005, taker_fee: float = 0.0005,
                 shock_size: float = 20.0, wall_t0: Optional[float] = None,
                 explain: bool = False, log_path: Optional[str] = None):
        self.seed = seed
        self.rng = random.Random(seed)
        self.now = 0.0
        self.tick_i = 0
        self.t0_wall = int(wall_t0 if wall_t0 is not None else _time.time())
        self.p0 = start_price
        self.shock_size = shock_size
        self.random_shock_p = random_shocks_per_hour / 3600.0 * DT

        self.ex = Exchange(maker_fee=maker_fee, taker_fee=taker_fee, clock=lambda: self.now)
        self.tick_trades: list = []
        self.ex.listeners.append(self.tick_trades.append)

        # скрытая «справедливая цена» (участникам напрямую не доступна)
        self._F = start_price
        self._F_hist = [start_price]
        self._logsig = 0.0
        self._mu = 0.0
        self.sig0 = 2.0

        self.mid_hist: list[float] = [start_price]
        self.ema_mid = start_price
        self.agents, self.whale = build_crowd(self, seed * 7919 + 13, whale_gap)
        for a in self.agents:
            if a.kind == "liquidity":
                self.ex.create_wallet(a.id, 5e7, 800)
            elif a.kind == "whale":
                self.ex.create_wallet(a.id, 1e8, 1500)
            else:
                self.ex.create_wallet(a.id, 3e6, 40)
        self.ex.create_wallet("user", 10_000.0, 0.1)  # демо-кошелёк для ручных заявок по REST

        self.ai: Optional[MarketMaker] = None
        if ai_mode != "none":
            self.ex.create_wallet(AI_ID, (ai_cfg or AIConfig()).start_usdt, 0.0)
            self.ai = MarketMaker(Gateway(self.ex, AI_ID, lambda: self.now), ai_cfg,
                                  model if ai_mode == "ml" else None)

        # прозрачность модели: журнал прогнозов и живая статистика (только наблюдает за ИИ)
        self.explain: Optional[ExplainTracker] = None
        if explain and self.ai is not None:
            meta = getattr(model, "meta", None) or {}
            self.explain = ExplainTracker(horizon_sec=float(meta.get("horizon_sec", 3.0)), log_path=log_path,
                                          t0_wall=self.t0_wall)

        # свечи и учёт
        self.candles: list[dict] = []
        self.ui_trades: deque = deque(maxlen=600)
        self.eq_curve: list[dict] = []
        self.marks: dict[int, dict] = {}
        self.shocks: list[float] = []
        self.started = False
        self.start_equity = (ai_cfg or AIConfig()).start_usdt
        self.bh_qty = 0.0
        self.peak = self.start_equity
        self.max_dd = 0.0
        self.eq = self.start_equity
        self.bh_eq = self.start_equity
        self.session_p0: Optional[float] = None
        self._eq_bucket = -1

    # ---------- публичная информация, доступная ботам ----------
    def ref_price(self) -> float:
        m = self.ex.mid()
        if m is not None:
            return m
        return self.ex.last_price or self.p0

    def ret(self, seconds: float) -> float:
        h = self.mid_hist
        k = int(seconds / DT)
        j = max(0, len(h) - 1 - k)
        return (h[-1] / h[j] - 1) * 1e4

    def fundamental_lagged(self, lag_ticks: int) -> float:
        h = self._F_hist
        return h[max(0, len(h) - 1 - lag_ticks)]

    # ---------- события ----------
    def shock(self) -> None:
        """Рыночный шок: крупный игрок сливает позицию в рынок + плохие новости слегка опускают «справедливую цену»."""
        self.whale.start_program("sell", self.shock_size, dump=True)
        self._F *= 0.985
        self.shocks.append(self.now)

    # ---------- шаг симуляции (0.1 с) ----------
    def _advance_fundamental(self) -> None:
        r = self.rng
        s = math.sqrt(DT)
        self._logsig += -self._logsig * DT / 120.0 + 0.05 * s * r.gauss(0, 1)
        self._mu += -self._mu * DT / 60.0 + 0.073 * s * r.gauss(0, 1)
        sigma = self.sig0 * math.exp(self._logsig)
        ret = self._mu * 1e-4 * DT + sigma * 1e-4 * s * r.gauss(0, 1)
        if r.random() < DT / 400.0:
            ret += r.gauss(0, 20) * 1e-4
        self._F *= math.exp(ret)
        self._F_hist.append(self._F)
        if len(self._F_hist) > 3000:
            del self._F_hist[:1000]

    def step(self) -> None:
        self.tick_i += 1
        self.now += DT
        self._advance_fundamental()
        if self.random_shock_p and self.rng.random() < self.random_shock_p:
            self.shock()
        self.tick_trades.clear()
        first = self.tick_i == 1
        act = [a for a in self.agents if first or self.rng.random() < a.p]
        self.rng.shuffle(act)
        for a in act:
            a.act()
        if self.ai is not None:
            self.ai.step()
        price = self.ref_price()
        self.mid_hist.append(price)
        self.ema_mid += (price - self.ema_mid) * (DT / 15.0)
        if len(self.mid_hist) > 3000:
            del self.mid_hist[:1000]
        self._update_candle()
        self._update_account(price)
        if self.explain is not None and self.started:
            self.explain.on_tick(self)

    def run(self, ticks: int) -> None:
        for _ in range(ticks):
            self.step()

    # ---------- свечи ----------
    def _update_candle(self) -> None:
        bucket = int(self.now // CANDLE_SEC)
        t = self.t0_wall + bucket * CANDLE_SEC
        c = self.candles[-1] if self.candles else None
        if c is None or c["time"] != t:
            o = c["close"] if c else (self.ex.last_price or self.p0)
            c = {"time": t, "open": o, "high": o, "low": o, "close": o, "volume": 0.0}
            self.candles.append(c)
            if len(self.candles) > 4000:
                del self.candles[:1000]
        for tr in self.tick_trades:
            p = tr.price
            c["high"] = max(c["high"], p)
            c["low"] = min(c["low"], p)
            c["close"] = p
            c["volume"] += tr.qty
            ai_buy, ai_sell = tr.buyer == AI_ID, tr.seller == AI_ID
            self.ui_trades.append({
                "id": tr.id, "t": self.t0_wall + tr.ts, "p": p, "q": tr.qty, "s": tr.taker_side,
                "ai": ai_buy or ai_sell,
            })
            if ai_buy or ai_sell:
                m = self.marks.setdefault(t, {"time": t, "bq": 0.0, "bv": 0.0, "sq": 0.0, "sv": 0.0})
                k = "b" if ai_buy else "s"
                m[k + "q"] += tr.qty
                m[k + "v"] += tr.qty * p
        if self.session_p0 is None and self.ex.last_price:
            self.session_p0 = self.ex.last_price

    # ---------- учёт результатов ИИ ----------
    def start_ai(self) -> None:
        """Прогрев закончен: ИИ начинает торговать, фиксируем точку отсчёта для Buy&Hold."""
        ai = self.ai
        if ai is None or self.started:
            return
        ex = self.ex
        ask = ex.best_ask() or self.ref_price()
        self.bh_qty = self.start_equity * (1 - ex.taker_fee) / ask  # Buy&Hold платит и спред, и комиссию
        ai.activate()
        self.started = True
        self.peak = self.start_equity

    def _update_account(self, price: float) -> None:
        if not self.started:
            return
        w = self.ex.wallets[AI_ID]
        self.eq = w.usdt_total + w.btc_total * price
        self.bh_eq = self.bh_qty * price
        self.peak = max(self.peak, self.eq)
        self.max_dd = max(self.max_dd, (self.peak - self.eq) / self.peak * 100.0)
        bucket = int(self.now // CANDLE_SEC)
        t = self.t0_wall + bucket * CANDLE_SEC
        pt = {"time": t, "ai": (self.eq / self.start_equity - 1) * 100, "bh": (self.bh_eq / self.start_equity - 1) * 100}
        if self.eq_curve and self.eq_curve[-1]["time"] == t:
            self.eq_curve[-1] = pt
        else:
            self.eq_curve.append(pt)
            if len(self.eq_curve) > 4000:
                del self.eq_curve[:1000]

    def ai_summary(self) -> dict:
        """Итоговые показатели ИИ (для интерфейса, evaluate.py и тестов)."""
        if self.ai is None or not self.started:
            return {}
        s = self.ai.stats()
        ai_pct = (self.eq / self.start_equity - 1) * 100
        bh_pct = (self.bh_eq / self.start_equity - 1) * 100
        w = self.ex.wallets[AI_ID]
        return {
            "equity": self.eq, "profit_pct": ai_pct, "bh_pct": bh_pct, "edge_pct": ai_pct - bh_pct,
            "fills": s["fills"], "win_rate": s["win_rate"], "max_dd": self.max_dd,
            "pos": w.btc_total, "usdt": w.usdt_total, "volume": s["volume"], "fees": s["fees"],
            "realized": s["realized"],
        }


def book_view(sim: "Simulation", depth: int = 12) -> dict:
    """Стакан для интерфейса: [цена, объём, объём заявок ИИ на уровне]."""
    ai_at: dict = {}
    for o in sim.ex.open_orders(AI_ID):
        ai_at[(o.side, o.price)] = ai_at.get((o.side, o.price), 0.0) + o.remaining
    lv = sim.ex.levels(depth)
    return {
        "bids": [[p, q, ai_at.get(("buy", p), 0.0)] for p, q, _ in lv["bids"]],
        "asks": [[p, q, ai_at.get(("sell", p), 0.0)] for p, q, _ in lv["asks"]],
    }
