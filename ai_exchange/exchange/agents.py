"""Толпа ботов. Каждый бот действует через ту же биржу, что и ИИ, и видит только стакан, ленту сделок
и историю цены. Исключение — «ценовые» трейдеры (ValueTrader): у них есть шумная и запаздывающая оценка
«справедливой цены» — это моделирует информированных участников, чьи сделки утекают в публичный поток ордеров.
ИИ-трейдер доступа к этой информации не имеет — он может лишь выучить её следы из стакана и ленты.
"""
from __future__ import annotations

import math
import random

from .engine import BUY, SELL, LIMIT, MARKET

DT = 0.1


class Agent:
    kind = "agent"

    def __init__(self, aid: str, sim, rate: float, rng: random.Random):
        self.id = aid
        self.sim = sim
        self.rng = rng
        self.p = 1.0 - math.exp(-rate * DT)

    def act(self) -> None:  # pragma: no cover
        raise NotImplementedError

    # вспомогательное
    def market(self, side: str, qty: float):
        return self.sim.ex.place_order(self.id, side, MARKET, qty)

    def limit(self, side: str, qty: float, price: float, post_only: bool = False):
        return self.sim.ex.place_order(self.id, side, LIMIT, qty, price, post_only)


class LiquidityProvider(Agent):
    """Классический котировщик: лесенка заявок вокруг рыночной цены, периодически обновляется."""
    kind = "liquidity"

    def __init__(self, aid, sim, rng):
        super().__init__(aid, sim, 0.45, rng)
        self.base = rng.uniform(9.0, 15.0)
        self.step = rng.uniform(4.0, 8.0)
        self.size = rng.uniform(0.07, 0.2)
        self.deep = [(90, rng.uniform(0.5, 1.2)), (170, rng.uniform(0.8, 1.6)),
                     (300, rng.uniform(1.0, 2.0)), (500, rng.uniform(1.2, 2.4))]

    def act(self) -> None:
        ex, rng = self.sim.ex, self.rng
        ex.cancel_all(self.id)
        ref = 0.7 * self.sim.ref_price() + 0.3 * self.sim.ema_mid
        jitter = rng.gauss(0, 1.2)
        # в быстром рынке котировщики отходят: шире и тоньше (реалистичное «исчезновение ликвидности»)
        stress = min(3.0, max(1.0, abs(self.sim.ret(5)) / 25.0))
        for i in range(5):
            off = (self.base + self.step * i + jitter + rng.uniform(0, 1.5)) * stress
            q = self.size * (1 + 0.55 * i) * rng.uniform(0.7, 1.3) / stress ** 0.5
            self.limit(BUY, q, ref * (1 - off / 1e4), True)
            self.limit(SELL, q, ref * (1 + off / 1e4), True)
        for off, q in self.deep:
            off *= rng.uniform(0.9, 1.1) * stress
            q /= stress ** 0.5
            self.limit(BUY, q, ref * (1 - off / 1e4), True)
            self.limit(SELL, q, ref * (1 + off / 1e4), True)


class NoiseTrader(Agent):
    kind = "noise"

    def __init__(self, aid, sim, rng):
        super().__init__(aid, sim, rng.uniform(0.25, 0.5), rng)
        self.mkt_share = rng.uniform(0.4, 0.65)
        self.med = rng.uniform(0.008, 0.016)
        self.ttl = rng.uniform(4, 14)
        self.mine: list[tuple[int, float]] = []

    def act(self) -> None:
        rng, sim = self.rng, self.sim
        now = sim.now
        if self.mine:  # снимаем протухшие лимитки
            keep = []
            for oid, t in self.mine:
                if now - t > self.ttl:
                    sim.ex.cancel_order(oid, self.id)
                else:
                    keep.append((oid, t))
            self.mine = keep
        side = BUY if rng.random() < 0.5 else SELL
        qty = min(self.med * math.exp(rng.gauss(0, 0.9)), 0.15)
        if rng.random() < self.mkt_share:
            self.market(side, qty)
        else:
            ref = sim.ref_price()
            off = rng.expovariate(1 / 10.0) + 1.0
            px = ref * (1 - off / 1e4) if side == BUY else ref * (1 + off / 1e4)
            o, _ = self.limit(side, qty, px, True)
            if o.status in ("open", "partial"):
                self.mine.append((o.id, now))


class TrendFollower(Agent):
    kind = "trend"

    def __init__(self, aid, sim, rng):
        super().__init__(aid, sim, rng.uniform(0.2, 0.4), rng)
        self.window = rng.choice([10, 20, 30, 60])
        self.thr = rng.uniform(4.0, 9.0) * math.sqrt(self.window / 10)
        self.size = rng.uniform(0.01, 0.045)

    def act(self) -> None:
        mom = self.sim.ret(self.window)
        if abs(mom) < self.thr:
            return
        strength = min(abs(mom) / self.thr, 3.0)
        if self.rng.random() < 0.5 * strength:
            self.market(BUY if mom > 0 else SELL, self.size * strength)


class PanicSeller(Agent):
    kind = "panic"

    def __init__(self, aid, sim, rng):
        super().__init__(aid, sim, 2.0, rng)
        self.thr5 = rng.uniform(14.0, 28.0)
        self.thr30 = rng.uniform(45.0, 90.0)
        self.size = rng.uniform(0.05, 0.22)
        self.cool = 0.0

    def act(self) -> None:
        sim = self.sim
        if sim.now < self.cool:
            return
        r5, r30 = sim.ret(5), sim.ret(30)
        if r5 < -self.thr5 or r30 < -self.thr30:
            self.market(SELL, self.size * self.rng.uniform(0.7, 1.4))
            self.cool = sim.now + self.rng.uniform(2.0, 6.0)
        elif r5 > self.thr5 * 1.6 and self.rng.random() < 0.3:  # FOMO на росте — слабее
            self.market(BUY, self.size * 0.3)
            self.cool = sim.now + self.rng.uniform(3.0, 8.0)


class ValueTrader(Agent):
    """Информированный участник: видит «справедливую цену» с задержкой и шумом, торгует в сторону расхождения."""
    kind = "value"

    def __init__(self, aid, sim, rng):
        super().__init__(aid, sim, rng.uniform(0.3, 0.6), rng)
        self.lag = rng.choice([10, 15, 25, 40])  # тиков (1–4 с)
        self.noise_bps = rng.uniform(1.5, 4.0)
        self.thr = rng.uniform(5.0, 9.0)
        self.size = rng.uniform(0.015, 0.05)

    def act(self) -> None:
        sim = self.sim
        mid = sim.ref_price()
        f = sim.fundamental_lagged(self.lag) * (1 + self.rng.gauss(0, self.noise_bps) / 1e4)
        gap = (f / mid - 1) * 1e4
        if abs(gap) < self.thr:
            return
        side = BUY if gap > 0 else SELL
        scale = min(abs(gap) / 10.0, 3.0)
        if abs(gap) > 2 * self.thr:
            self.market(side, self.size * scale)
        else:
            px = mid * (1 + gap / 2e4)
            self.limit(side, self.size * scale, px, True)


class Whale(Agent):
    """Крупный игрок: время от времени запускает «программу» выкупа/слива, двигая рынок. Умеет устраивать шок."""
    kind = "whale"

    def __init__(self, aid, sim, rng, mean_gap: float = 150.0, scale: float = 1.0):
        super().__init__(aid, sim, 10.0, rng)
        self.mean_gap = mean_gap
        self.scale = scale
        self.side = BUY
        self.remaining = 0.0
        self.next_slice = 0.0
        self.next_start = rng.expovariate(1 / mean_gap) if mean_gap else math.inf
        self.dump = False

    def start_program(self, side: str, total: float, dump: bool = False) -> None:
        self.side, self.remaining, self.dump = side, total, dump
        self.next_slice = self.sim.now

    def act(self) -> None:
        sim, rng = self.sim, self.rng
        now = sim.now
        if self.remaining <= 1e-9:
            if now >= self.next_start:
                self.start_program(BUY if rng.random() < 0.5 else SELL, rng.uniform(0.8, 3.0) * self.scale)
                self.next_start = now + rng.expovariate(1 / self.mean_gap)
            return
        if now < self.next_slice:
            return
        if self.dump:
            q = min(self.remaining, rng.uniform(0.8, 2.0))
            gap = rng.uniform(0.2, 0.5)
        else:
            q = min(self.remaining, rng.uniform(0.04, 0.2))
            gap = rng.uniform(0.3, 1.2)
        self.market(self.side, q)
        self.remaining -= q
        self.next_slice = now + gap


def build_crowd(sim, rng_seed: int, whale_gap: float = 150.0) -> tuple[list[Agent], Whale]:
    """~50 агентов: 4 котировщика, 24 шумовых, 8 трендовых, 6 паникёров, 7 ценовых, 1 крупный игрок."""
    r = random.Random(rng_seed)
    agents: list[Agent] = []
    spec = [(LiquidityProvider, 4, "lp"), (NoiseTrader, 24, "noise"), (TrendFollower, 8, "trend"),
            (PanicSeller, 6, "panic"), (ValueTrader, 7, "value")]
    for cls, n, tag in spec:
        for i in range(n):
            agents.append(cls(f"{tag}_{i}", sim, random.Random(r.random())))
    whale = Whale("whale", sim, random.Random(r.random()), mean_gap=whale_gap)
    agents.append(whale)
    return agents, whale
