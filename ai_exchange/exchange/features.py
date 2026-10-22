"""Признаки для ML-модели ИИ-трейдера.

Используются ТОЛЬКО публичные данные, доступные любому участнику в момент t:
стакан (без собственных заявок ИИ), лента сделок (без собственных сделок), история
средней цены, собственная позиция. Один и тот же класс применяется и при обучении
(train.py), и в живой работе — поэтому расхождений между ними нет.
"""
from __future__ import annotations

import numpy as np

TICKS_PER_SEC = 10
FEATURES = [
    "imb1", "imb5", "imb10", "micro_bps", "spread_bps",
    "flow_1s", "flow_3s", "flow_10s", "signed_vol_3s",
    "ret_1s", "ret_3s", "ret_10s", "ret_30s",
    "vol_10s", "vol_60s", "vol_ratio", "trade_rate_3s", "depth_log", "pos_norm",
]
N_FEATURES = len(FEATURES)
WARMUP_TICKS = 300  # 30 с истории


def _imb(a: float, b: float) -> float:
    s = a + b
    return (a - b) / s if s > 1e-12 else 0.0


class FeatureBuilder:
    def __init__(self):
        self.mids: list[float] = []
        self.r1: list[float] = []  # 1-секундные доходности в б.п. (перекрывающиеся)
        self.cum_buy: list[float] = [0.0]
        self.cum_sell: list[float] = [0.0]
        self.cum_cnt: list[float] = [0.0]
        self._last: dict = {}
        self.n_updates = 0  # число обработанных шагов (нужно журналу прогнозов)

    @property
    def ready(self) -> bool:
        return len(self.mids) >= WARMUP_TICKS

    def update(self, mid: float, bid_lv, ask_lv, trades, pos_norm: float) -> None:
        """bid_lv/ask_lv: [(цена, объём), ...] от лучшей; trades: [(price, qty, taker_side), ...] чужие сделки тика."""
        self.n_updates += 1
        m = self.mids
        m.append(mid)
        n = len(m)
        k = TICKS_PER_SEC
        self.r1.append((mid / m[n - 1 - k] - 1) * 1e4 if n > k else 0.0)
        buy = sell = 0.0
        for _, q, side in trades:
            if side == "buy":
                buy += q
            else:
                sell += q
        self.cum_buy.append(self.cum_buy[-1] + buy)
        self.cum_sell.append(self.cum_sell[-1] + sell)
        self.cum_cnt.append(self.cum_cnt[-1] + len(trades))
        if n > 6000:  # периодическая обрезка истории
            del m[:3000]
            del self.r1[:3000]
            del self.cum_buy[:3000]
            del self.cum_sell[:3000]
            del self.cum_cnt[:3000]

        b1, a1 = bid_lv[0][1], ask_lv[0][1]
        bp, ap = bid_lv[0][0], ask_lv[0][0]
        bsum5 = sum(q for _, q in bid_lv[:5])
        asum5 = sum(q for _, q in ask_lv[:5])
        bsum10 = sum(q for _, q in bid_lv[:10])
        asum10 = sum(q for _, q in ask_lv[:10])
        micro = (bp * a1 + ap * b1) / (a1 + b1) if (a1 + b1) > 0 else mid
        self._last = {
            "imb1": _imb(b1, a1), "imb5": _imb(bsum5, asum5), "imb10": _imb(bsum10, asum10),
            "micro_bps": (micro / mid - 1) * 1e4, "spread_bps": (ap - bp) / mid * 1e4,
            "depth_log": float(np.log1p(bsum10 + asum10)),
            "pos_norm": pos_norm,
        }

    def _flow(self, ticks: int) -> tuple[float, float]:
        n = len(self.cum_buy)
        j = max(0, n - 1 - ticks)
        b = self.cum_buy[-1] - self.cum_buy[j]
        s = self.cum_sell[-1] - self.cum_sell[j]
        return b, s

    def _ret(self, ticks: int) -> float:
        m = self.mids
        j = max(0, len(m) - 1 - ticks)
        return (m[-1] / m[j] - 1) * 1e4

    def _vol(self, seconds: int) -> float:
        k = TICKS_PER_SEC
        arr = self.r1[-(seconds * k) :: k] if len(self.r1) > seconds * k else self.r1[::k]
        if len(arr) < 3:
            return 0.0
        return float(np.std(arr))

    def vector(self) -> np.ndarray:
        f = self._last
        b1, s1 = self._flow(10)
        b3, s3 = self._flow(30)
        b10, s10 = self._flow(100)
        cnt3 = self.cum_cnt[-1] - self.cum_cnt[max(0, len(self.cum_cnt) - 1 - 30)]
        v10, v60 = self._vol(10), self._vol(60)
        v = [
            f["imb1"], f["imb5"], f["imb10"], f["micro_bps"], f["spread_bps"],
            _imb(b1, s1), _imb(b3, s3), _imb(b10, s10), b3 - s3,
            self._ret(10), self._ret(30), self._ret(100), self._ret(300),
            v10, v60, v10 / v60 if v60 > 1e-9 else 1.0, cnt3, f["depth_log"], f["pos_norm"],
        ]
        return np.asarray(v, dtype=np.float64)
