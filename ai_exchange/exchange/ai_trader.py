"""ИИ-трейдер: маркет-мейкер (Avellaneda–Stoikov) + LightGBM-прогноз + риск-менеджмент.

Честность: ИИ работает только через `Gateway` — публичный стакан, лента сделок, собственные заявки и
собственный кошелёк. У него нет доступа к будущим ценам, к состоянию ботов и к «справедливой цене» симуляции.
"""
from __future__ import annotations

import json
import math
import os
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .engine import BUY, SELL, Exchange
from .features import FeatureBuilder, FEATURES, WARMUP_TICKS

AI_ID = "ai"
MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
MODEL_PATH = os.path.join(MODEL_DIR, "model.txt")
META_PATH = os.path.join(MODEL_DIR, "meta.json")
IDX = {n: i for i, n in enumerate(FEATURES)}


def fmt_px(p: float) -> str:
    return f"{p:,.1f}".replace(",", " ")


class Gateway:
    """Единственное окно ИИ в рынок: то же, что доступно любому участнику биржи."""

    def __init__(self, ex: Exchange, owner: str, clock):
        self._ex, self.owner, self._clock = ex, owner, clock
        self._tape: list = []
        ex.listeners.append(self._tape.append)

    @property
    def now(self) -> float:
        return self._clock()

    def levels(self, n: int):
        lv = self._ex.levels(n)
        return [(p, q) for p, q, _ in lv["bids"]], [(p, q) for p, q, _ in lv["asks"]]

    def drain_trades(self):
        t = list(self._tape)
        self._tape.clear()
        return t

    def wallet(self):
        return self._ex.wallets[self.owner]

    def own_orders(self):
        return self._ex.open_orders(self.owner)

    def get_order(self, oid: int):
        o = self._ex.orders.get(oid)
        return o if o is not None and o.owner == self.owner else None

    def place_limit(self, side: str, qty: float, price: float):
        return self._ex.place_order(self.owner, side, "limit", qty, price, post_only=True)[0]

    def market(self, side: str, qty: float):
        return self._ex.place_order(self.owner, side, "market", qty)

    def cancel(self, oid: int) -> bool:
        return self._ex.cancel_order(oid, self.owner)

    def cancel_all(self) -> int:
        return self._ex.cancel_all(self.owner)

    def round_price(self, p: float) -> float:
        return self._ex.round_price(p)

    @property
    def tick(self) -> float:
        return self._ex.tick

    @property
    def fee(self) -> float:
        return self._ex.taker_fee


class PriceModel:
    """Обёртка над LightGBM: прогноз изменения средней цены на горизонт (б.п.)."""

    def __init__(self, path: str = MODEL_PATH, meta_path: str = META_PATH):
        import lightgbm as lgb
        self.booster = lgb.Booster(model_file=path)
        with open(meta_path, "r", encoding="utf-8") as f:
            self.meta = json.load(f)
        if self.meta.get("features") != FEATURES:
            raise RuntimeError("Модель обучена на другом наборе признаков — запустите python train.py")

    def predict(self, x: np.ndarray) -> float:
        return float(self.booster.predict(x.reshape(1, -1), num_threads=1)[0])

    @staticmethod
    def load_default() -> Optional["PriceModel"]:
        if os.path.exists(MODEL_PATH) and os.path.exists(META_PATH):
            return PriceModel()
        return None


@dataclass
class AIConfig:
    start_usdt: float = 10_000.0
    max_pos: float = 0.5            # лимит позиции, BTC
    target_frac: float = 0.35       # доля капитала в BTC в «нейтральном» состоянии
    gamma: float = 0.02             # неприятие риска (Avellaneda–Stoikov)
    tau: float = 20.0               # горизонт, с
    k: float = 1.5                  # интенсивность потока заявок
    min_half_bps: float = 7.5       # полуспред не меньше (комиссия 5 б.п. + запас)
    max_half_bps: float = 70.0
    size_frac: float = 0.10         # объём котировки, доля капитала
    l2_extra_bps: float = 7.0
    pred_gain: float = 1.0          # доля прогноза, которой сдвигаем резервную цену
    pred_widen: float = 0.35
    pred_clip: float = 12.0
    vol_widen: float = 0.8
    requote_bps: float = 1.2
    emerg_ret10: float = -55.0      # б.п. за 10 с
    emerg_ret3: float = -35.0       # б.п. за 3 с
    up_caution_ret10: float = 55.0


class MarketMaker:
    def __init__(self, gw: Gateway, cfg: Optional[AIConfig] = None, model: Optional[PriceModel] = None):
        self.gw = gw
        self.cfg = cfg or AIConfig()
        self.model = model
        self.mode_ml = model is not None
        self.fb = FeatureBuilder()
        self.active = False
        self.mode = "warmup"           # warmup | quoting | caution | emergency | recovery
        self.mode_until = 0.0
        self.risk_scale = 1.0
        self.slots: dict[tuple, int] = {}
        self.var_slow = 9.0
        self.sigma_ref = 3.0
        self.pred = 0.0
        self.pred_raw = 0.0
        self.half = self.cfg.min_half_bps
        self.sigma = 3.0
        self.q = 0.0
        self.thoughts: deque = deque(maxlen=300)
        self._tid = 0
        self._last_say: dict[str, float] = {}
        self._sig_state = "flat"
        self._announced_half = self.cfg.min_half_bps
        self.last_x: Optional[np.ndarray] = None
        # статистика
        self.fills = 0
        self.sells = 0
        self.wins = 0
        self.volume = 0.0
        self.fees = 0.0
        self.realized = 0.0
        self.avg_cost = 0.0
        self.pos_tracked = 0.0
        self.new_fills: list[dict] = []
        self.quote_bid: Optional[float] = None
        self.quote_ask: Optional[float] = None
        self.imb5 = 0.0
        self.mid = 0.0
        self.equity = self.cfg.start_usdt
        self.target_pos = 0.0

    # ---------- мысли ----------
    def say(self, kind: str, text: str, tag: str = "info", gap: float = 0.0) -> None:
        now = self.gw.now
        if gap and now - self._last_say.get(kind, -1e9) < gap:
            return
        self._last_say[kind] = now
        self._tid += 1
        self.thoughts.append({"id": self._tid, "t": now, "text": text, "tag": tag})

    # ---------- исполнения ----------
    def _on_fill(self, t) -> None:
        fee_rate = self.gw.fee
        buy = t.buyer == AI_ID
        q, p = t.qty, t.price
        self.fills += 1
        self.volume += q * p
        self.fees += q * p * fee_rate
        pnl = None
        if buy:
            cost = p * (1 + fee_rate)
            tot = self.pos_tracked + q
            self.avg_cost = (self.avg_cost * self.pos_tracked + cost * q) / tot if tot > 0 else 0.0
            self.pos_tracked = tot
        else:
            pnl = q * (p * (1 - fee_rate) - self.avg_cost)
            self.realized += pnl
            self.sells += 1
            self.wins += pnl > 0
            self.pos_tracked = max(0.0, self.pos_tracked - q)
        self.new_fills.append({"t": t.ts, "side": "buy" if buy else "sell", "price": p, "qty": q})
        verb = "Купил" if buy else "Продал"
        extra = f" (результат {pnl:+.2f} USDT)" if pnl is not None else ""
        self.say("fill", f"{verb} {q:.4f} BTC по {fmt_px(p)} → позиция {self.pos_tracked:.4f} BTC{extra}",
                 "buy" if buy else "sell", gap=1.5)

    # ---------- основной цикл (раз в 100 мс симулированного времени) ----------
    def _strip(self, levels, side, own_at):
        out = []
        for p, q in levels:
            q -= own_at.get((side, p), 0.0)
            if q > 1e-9:
                out.append((p, q))
        return out

    def step(self) -> None:
        gw, cfg = self.gw, self.cfg
        now = gw.now
        bids_raw, asks_raw = gw.levels(16)
        own_at: dict = {}
        for o in gw.own_orders():
            own_at[(o.side, o.price)] = own_at.get((o.side, o.price), 0.0) + o.remaining
        bids = self._strip(bids_raw, BUY, own_at)
        asks = self._strip(asks_raw, SELL, own_at)
        public = []
        for t in gw.drain_trades():
            if t.buyer == AI_ID or t.seller == AI_ID:
                self._on_fill(t)
            else:
                public.append((t.price, t.qty, t.taker_side))
        if not bids or not asks:
            return
        mid = (bids[0][0] + asks[0][0]) / 2
        w = gw.wallet()
        pos = w.btc_total
        equity = w.usdt_total + pos * mid
        self.mid, self.equity = mid, equity
        self.fb.update(mid, bids, asks, public, pos / cfg.max_pos)
        x = self.fb.vector()
        self.last_x = x
        self.imb5 = float(x[IDX["imb5"]])

        # --- оценка волатильности (б.п. за √с) ---
        r1 = self.fb.r1[-1]
        self.var_slow += (r1 * r1 - self.var_slow) * (0.1 / 300.0)
        vol10 = float(x[IDX["vol_10s"]])
        sigma = max(1.5, math.sqrt(0.5 * vol10 ** 2 + 0.5 * self.var_slow))
        self.sigma = sigma
        vol_ratio = sigma / max(self.sigma_ref, 1e-9)

        # --- прогноз ML ---
        pred = 0.0
        if self.model is not None and self.fb.ready:
            self.pred_raw = self.model.predict(x)
            pred = float(np.clip(self.pred_raw, -cfg.pred_clip, cfg.pred_clip))
        self.pred = 0.6 * self.pred + 0.4 * pred if self.model is not None else 0.0

        if not self.active:
            return
        ret3, ret10 = float(x[IDX["ret_3s"]]), float(x[IDX["ret_10s"]])

        # --- риск: аварийный режим ---
        if self.mode != "emergency" and (ret10 <= cfg.emerg_ret10 or ret3 <= cfg.emerg_ret3):
            self._emergency(now, ret3 if ret3 <= cfg.emerg_ret3 else ret10, pos)
            return
        if self.mode in ("quoting",) and ret10 >= cfg.up_caution_ret10:
            self.mode, self.mode_until = "caution", now + 10.0
            self._cancel_all()
            self.say("mode", f"Резкий рост +{ret10:.0f} б.п. за 10 с → снимаю котировки, расширяю спред в 2.5 раза",
                     "warn")
            return
        if self.mode == "emergency":
            if now < self.mode_until:
                return
            if abs(ret3) > 15:  # падение ещё идёт — ждём
                self.mode_until = now + 2.0
                return
            self.mode, self.mode_until = "recovery", now + 40.0
            self.say("mode", "Пауза закончилась → возвращаюсь осторожно: спред в 3 раза шире, позиция пока нулевая", "info")
        if self.mode == "caution" and now >= self.mode_until:
            self.mode = "quoting"
        if self.mode == "recovery":
            frac = max(0.0, 1.0 - (self.mode_until - now) / 40.0)
            self.risk_scale = frac
            if now >= self.mode_until:
                self.mode, self.risk_scale = "quoting", 1.0
                self.say("mode", "Полностью вернулся к нормальному режиму котирования", "info")
        elif self.mode == "quoting":
            self.risk_scale = min(1.0, self.risk_scale + 0.002)

        self._quote(now, mid, bids, asks, w, pos, equity, sigma, vol_ratio, x)

    # ---------- котирование ----------
    def _quote(self, now, mid, bids, asks, w, pos, equity, sigma, vol_ratio, x) -> None:
        cfg, gw = self.cfg, self.gw
        inv_scale = max(cfg.target_frac * equity / mid, 0.01)
        target = self.risk_scale * cfg.target_frac * equity / mid
        self.target_pos = target
        q = (pos - target) / inv_scale
        self.q = q
        gs2t = cfg.gamma * sigma ** 2 * cfg.tau
        skew = gs2t * q
        half_as = 0.5 * (gs2t + (2 / cfg.gamma) * math.log(1 + cfg.gamma / cfg.k))
        half = max(cfg.min_half_bps, half_as)
        if vol_ratio > 1.3:
            half *= 1 + cfg.vol_widen * (vol_ratio - 1.3)
        half *= 1 + cfg.pred_widen * abs(self.pred) / 10.0
        if self.mode == "caution":
            half *= 2.5
        elif self.mode == "recovery":
            half *= 1 + 2.0 * (self.mode_until - now) / 40.0
        half = min(half, cfg.max_half_bps)
        self.half = half
        shift = cfg.pred_gain * self.pred
        r = shift - skew
        bid_bps, ask_bps = r - half, r + half

        S = cfg.size_frac * equity / mid
        bid_scale = float(np.clip(1 - 0.8 * q, 0.0, 1.4))
        ask_scale = float(np.clip(1 + 0.8 * q, 0.0, 1.6))
        if self.pred <= -1.5:
            bid_scale *= max(0.15, 1 - abs(self.pred) / 8.0)
        elif self.pred >= 1.5:
            ask_scale *= max(0.15, 1 - abs(self.pred) / 8.0)
        limit_hit = pos >= cfg.max_pos * 0.98
        if limit_hit:
            bid_scale = 0.0
        if self.mode == "recovery" and self.risk_scale < 0.3:
            bid_scale *= 0.5

        tick = gw.tick
        best_bid, best_ask = bids[0][0], asks[0][0]
        desired: dict = {}
        usdt_avail = w.usdt_total * 0.97
        for i, (mult, extra) in enumerate(((0.6, 0.0), (1.0, cfg.l2_extra_bps))):
            bp = min(mid * (1 + (bid_bps - extra) / 1e4), best_ask - tick)
            ap = max(mid * (1 + (ask_bps + extra) / 1e4), best_bid + tick)
            bq = S * mult * bid_scale
            aq = S * mult * ask_scale
            bq = min(bq, usdt_avail / (bp * 1.001))
            usdt_avail -= bq * bp * 1.001
            if bq * bp > 10:
                desired[(BUY, i)] = (gw.round_price(bp), round(bq, 5))
        ask_budget = pos
        for i, (mult, extra) in enumerate(((0.6, 0.0), (1.0, cfg.l2_extra_bps))):
            ap = max(mid * (1 + (ask_bps + extra) / 1e4), best_bid + tick)
            aq = min(S * mult * ask_scale, ask_budget)
            ask_budget -= aq
            if aq * ap > 10:
                desired[(SELL, i)] = (gw.round_price(ap), round(aq, 5))
        self._sync(desired)
        b = desired.get((BUY, 0))
        a = desired.get((SELL, 0))
        self.quote_bid, self.quote_ask = (b[0] if b else None), (a[0] if a else None)
        self._narrate(now, shift, half, vol_ratio, q, pos, target, limit_hit)

    def _sync(self, desired: dict) -> None:
        gw, cfg = self.gw, self.cfg
        for slot in list(self.slots):
            if slot not in desired:
                gw.cancel(self.slots.pop(slot))
        for slot, (price, qty) in desired.items():
            oid = self.slots.get(slot)
            o = gw.get_order(oid) if oid else None
            if o is not None:
                if (abs(o.price - price) / price * 1e4 < cfg.requote_bps
                        and 0.5 * qty <= o.remaining <= 1.25 * qty):
                    continue
                gw.cancel(o.id)
            o = gw.place_limit(slot[0], qty, price)
            if o.status in ("open", "partial"):
                self.slots[slot] = o.id
            else:
                self.slots.pop(slot, None)

    def _cancel_all(self) -> None:
        self.gw.cancel_all()
        self.slots.clear()

    # ---------- аварийное закрытие ----------
    def _emergency(self, now: float, move: float, pos: float) -> None:
        self._cancel_all()
        self.mode, self.mode_until = "emergency", now + 8.0
        self.risk_scale = 0.0
        txt = f"Падение {move:.0f} б.п. за секунды! Снимаю все котировки"
        if pos > 1e-4:
            o, tr = self.gw.market(SELL, pos)
            sold = sum(t.qty for t in tr)
            txt += f" и аварийно закрываю позицию: продал {sold:.4f} BTC"
        self.say("mode", txt, "alarm")

    # ---------- «мысли» ----------
    def _narrate(self, now, shift, half, vol_ratio, q, pos, target, limit_hit) -> None:
        imb = self.imb5
        up = shift > 0
        sig = "up" if self.pred >= 1.5 else "down" if self.pred <= -1.5 else "flat"
        x = self.last_x
        reasons = []
        if abs(imb) >= 0.15:
            reasons.append(f"дисбаланс книги {imb * 100:+.0f}% в {'покупки' if imb > 0 else 'продажи'}")
        flow3 = float(x[IDX["flow_3s"]]) if x is not None else 0.0
        if abs(flow3) >= 0.25:
            reasons.append(f"поток сделок {flow3 * 100:+.0f}% в сторону {'покупок' if flow3 > 0 else 'продаж'}")
        ret3 = float(x[IDX["ret_3s"]]) if x is not None else 0.0
        if abs(ret3) >= 4:
            reasons.append(f"цена за 3 с {ret3:+.0f} б.п.")
        why = ", ".join(reasons) if reasons else "модель увидела закономерность в стакане и ленте"
        if self.model is not None and sig != "flat":
            self.say("signal",
                     f"{why[0].upper() + why[1:]} → прогноз {self.pred:+.1f} б.п. за 3 с → "
                     f"сдвигаю котировки {'вверх' if up else 'вниз'} на {abs(shift):.1f} б.п.",
                     "signal", gap=4.0)
        elif self.model is None and abs(imb) > 0.35:
            side = "покупки" if imb > 0 else "продажи"
            self.say("signal", f"Дисбаланс {imb * 100:+.0f}% в {side} (модель не загружена, котирую по Avellaneda–Stoikov)",
                     "signal", gap=6.0)
        self._sig_state = sig
        if half > self._announced_half * 1.3 and vol_ratio > 1.3:
            self.say("spread", f"Волатильность выросла в {vol_ratio:.1f} раза → расширяю спред до {2 * half:.0f} б.п.",
                     "warn", gap=3.0)
            self._announced_half = half
        elif half < self._announced_half * 0.75:
            self.say("spread", f"Рынок спокойнее → сужаю спред до {2 * half:.0f} б.п.", "info", gap=3.0)
            self._announced_half = half
        if abs(q) > 0.7:
            if q > 0:
                self.say("inv", f"Позиция {pos:.4f} BTC выше цели {target:.4f} → опускаю котировки и урезаю покупки",
                         "info", gap=8.0)
            else:
                self.say("inv", f"Позиция {pos:.4f} BTC ниже цели {target:.4f} → поднимаю котировки, покупаю охотнее",
                         "info", gap=8.0)
        if limit_hit:
            self.say("limit", f"Лимит позиции {self.cfg.max_pos} BTC достигнут → покупки отключены", "warn", gap=10.0)
        self.say("idle", f"Спред {2 * half:.0f} б.п., сигнал {'нейтральный' if sig == 'flat' else 'есть'}, "
                         f"позиция {pos:.4f} BTC — котирую", "info", gap=15.0)

    # ---------- запуск ----------
    def activate(self) -> None:
        """Старт торговли: покупаем стартовую позицию (target_frac капитала) и начинаем котировать."""
        gw, cfg = self.gw, self.cfg
        self.active = True
        self.mode = "quoting"
        self.sigma_ref = max(2.0, math.sqrt(self.var_slow))
        self.say("start", f"Старт: баланс {cfg.start_usdt:,.0f} USDT. Изучил рынок 30 с — "
                          f"волатильность {self.sigma_ref:.1f} б.п./√с".replace(",", " "), "info")
        w = gw.wallet()
        qty = cfg.target_frac * w.usdt_total / max(self.mid, 1.0)
        o, tr = gw.market(BUY, qty)
        got = sum(t.qty for t in tr)
        if got > 0:
            self.say("start2", f"Покупаю стартовую позицию {got:.4f} BTC ({cfg.target_frac * 100:.0f}% капитала) "
                               f"— дальше зарабатываю на спреде", "buy")

    # ---------- данные для интерфейса ----------
    def stats(self) -> dict:
        return {
            "fills": self.fills,
            "win_rate": (self.wins / self.sells * 100.0) if self.sells else None,
            "volume": self.volume,
            "fees": self.fees,
            "realized": self.realized,
        }

    def view(self) -> dict:
        return {
            "mode": self.mode, "pred": self.pred, "imb5": self.imb5, "half_bps": self.half,
            "sigma": self.sigma, "pos": self.gw.wallet().btc_total, "target": self.target_pos,
            "max_pos": self.cfg.max_pos, "bid": self.quote_bid, "ask": self.quote_ask,
            "ml": self.model is not None, "q": self.q,
        }
