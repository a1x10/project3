"""Матчинг-движок спотовой биржи BTC/USDT.

* лимитные и рыночные заявки, приоритет «цена → время»;
* кошельки (USDT, BTC) с резервированием средств под открытые заявки;
* комиссия (по умолчанию 0.05 % от оборота сделки с каждой стороны);
* защита от самосделок (STP): встречная заявка того же участника снимается.

Движок не знает ничего о ботах и ИИ — только о заявках и кошельках.
"""
from __future__ import annotations

import bisect
import itertools
import math
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional

BUY, SELL = "buy", "sell"
LIMIT, MARKET = "limit", "market"
FEE_ACCOUNT = "__fees__"


@dataclass(slots=True)
class Order:
    id: int
    owner: str
    side: str
    type: str
    price: Optional[float]
    qty: float
    remaining: float
    ts: float
    post_only: bool = False
    status: str = "new"  # new | open | partial | filled | cancelled | rejected
    reason: str = ""
    locked: float = 0.0  # зарезервировано: USDT для покупки, BTC для продажи


@dataclass(slots=True)
class Trade:
    id: int
    ts: float
    price: float
    qty: float
    taker_side: str  # сторона агрессора: buy = покупатель забрал аск
    buyer: str
    seller: str
    buy_order_id: int
    sell_order_id: int
    fee: float  # суммарная комиссия сделки (USDT)


class Wallet:
    __slots__ = ("usdt", "usdt_locked", "btc", "btc_locked")

    def __init__(self, usdt: float = 0.0, btc: float = 0.0):
        self.usdt = usdt
        self.usdt_locked = 0.0
        self.btc = btc
        self.btc_locked = 0.0

    @property
    def usdt_total(self) -> float:
        return self.usdt + self.usdt_locked

    @property
    def btc_total(self) -> float:
        return self.btc + self.btc_locked

    def as_dict(self) -> dict:
        return {
            "usdt": self.usdt, "usdt_locked": self.usdt_locked, "usdt_total": self.usdt_total,
            "btc": self.btc, "btc_locked": self.btc_locked, "btc_total": self.btc_total,
        }


class _Side:
    """Одна сторона книги: уровни цен с очередями заявок (FIFO)."""

    def __init__(self, is_bid: bool):
        self.is_bid = is_bid
        self.levels: dict[float, deque] = {}
        self.qty: dict[float, float] = {}
        self.prices: list[float] = []  # по возрастанию

    def best(self) -> Optional[float]:
        if not self.prices:
            return None
        return self.prices[-1] if self.is_bid else self.prices[0]

    def add(self, o: Order) -> None:
        p = o.price
        q = self.levels.get(p)
        if q is None:
            q = self.levels[p] = deque()
            self.qty[p] = 0.0
            bisect.insort(self.prices, p)
        q.append(o)
        self.qty[p] += o.remaining

    def _drop_level(self, p: float) -> None:
        del self.levels[p]
        del self.qty[p]
        i = bisect.bisect_left(self.prices, p)
        del self.prices[i]

    def remove(self, o: Order) -> None:
        p = o.price
        q = self.levels[p]
        q.remove(o)
        self.qty[p] -= o.remaining
        if not q:
            self._drop_level(p)

    def reduce(self, o: Order, filled: float) -> None:
        """Уменьшить объём уровня после (частичного) исполнения o. Полностью исполненную снимает с очереди."""
        p = o.price
        self.qty[p] -= filled
        if o.remaining <= 1e-12:
            q = self.levels[p]
            if q and q[0] is o:
                q.popleft()
            else:
                q.remove(o)
            if not q:
                self._drop_level(p)

    def top(self, n: int) -> list[tuple[float, float, int]]:
        pr = reversed(self.prices) if self.is_bid else iter(self.prices)
        out = []
        for p in itertools.islice(pr, n):
            out.append((p, self.qty[p], len(self.levels[p])))
        return out


class Exchange:
    def __init__(self, maker_fee: float = 0.0005, taker_fee: float = 0.0005,
                 tick: float = 0.1, min_qty: float = 1e-6,
                 clock: Callable[[], float] = lambda: 0.0):
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.lock_fee = max(maker_fee, taker_fee)
        self.tick = tick
        self.min_qty = min_qty
        self.clock = clock
        self.bids = _Side(True)
        self.asks = _Side(False)
        self.orders: dict[int, Order] = {}
        self.by_owner: dict[str, dict[int, Order]] = {}
        self.wallets: dict[str, Wallet] = {FEE_ACCOUNT: Wallet()}
        self.trades: deque[Trade] = deque(maxlen=50000)
        self.last_price: Optional[float] = None
        self._oid = itertools.count(1)
        self._tid = itertools.count(1)
        self.listeners: list[Callable[[Trade], None]] = []

    # ---------- кошельки ----------
    def create_wallet(self, pid: str, usdt: float = 0.0, btc: float = 0.0) -> Wallet:
        w = self.wallets[pid] = Wallet(usdt, btc)
        self.by_owner.setdefault(pid, {})
        return w

    def balance(self, pid: str) -> Optional[dict]:
        w = self.wallets.get(pid)
        return w.as_dict() if w else None

    # ---------- округление ----------
    def round_price(self, p: float) -> float:
        return round(round(p / self.tick) * self.tick, 8)

    def round_qty(self, q: float) -> float:
        return round(math.floor(q / self.min_qty + 1e-9) * self.min_qty, 8)

    # ---------- книга ----------
    def best_bid(self) -> Optional[float]:
        return self.bids.best()

    def best_ask(self) -> Optional[float]:
        return self.asks.best()

    def mid(self) -> Optional[float]:
        b, a = self.bids.best(), self.asks.best()
        return (b + a) / 2 if b is not None and a is not None else None

    def levels(self, depth: int = 20) -> dict:
        return {"bids": self.bids.top(depth), "asks": self.asks.top(depth)}

    # ---------- заявки ----------
    def _reject(self, o: Order, reason: str) -> Order:
        o.status, o.reason = "rejected", reason
        return o

    def place_order(self, owner: str, side: str, otype: str, qty: float,
                    price: Optional[float] = None, post_only: bool = False) -> tuple[Order, list[Trade]]:
        ts = self.clock()
        oid = next(self._oid)
        w = self.wallets.get(owner)
        o = Order(oid, owner, side, otype, None, 0.0, 0.0, ts, post_only)
        if w is None or owner == FEE_ACCOUNT:
            return self._reject(o, "unknown_participant"), []
        if side not in (BUY, SELL) or otype not in (LIMIT, MARKET):
            return self._reject(o, "bad_params"), []
        q = self.round_qty(qty)
        if q < self.min_qty:
            return self._reject(o, "qty_too_small"), []
        o.qty = o.remaining = q
        if otype == LIMIT:
            if price is None or price <= 0:
                return self._reject(o, "bad_price"), []
            o.price = self.round_price(price)
            if o.price <= 0:
                return self._reject(o, "bad_price"), []
            if post_only:
                opp = self.asks.best() if side == BUY else self.bids.best()
                if opp is not None and ((side == BUY and o.price >= opp) or (side == SELL and o.price <= opp)):
                    return self._reject(o, "post_only_would_cross"), []
            if side == BUY:
                need = q * o.price * (1 + self.lock_fee)
                if w.usdt + 1e-9 < need:
                    return self._reject(o, "insufficient_usdt"), []
                w.usdt -= need
                w.usdt_locked += need
                o.locked = need
            else:
                if w.btc + 1e-12 < q:
                    return self._reject(o, "insufficient_btc"), []
                w.btc -= q
                w.btc_locked += q
                o.locked = q
        else:
            if (side == BUY and w.usdt <= 0) or (side == SELL and w.btc < self.min_qty):
                return self._reject(o, "insufficient_funds"), []

        trades = self._match(o, w)
        if o.remaining > 1e-12 and o.type == LIMIT:
            o.status = "open" if o.remaining >= o.qty - 1e-12 else "partial"
            (self.bids if side == BUY else self.asks).add(o)
            self.orders[o.id] = o
            self.by_owner.setdefault(owner, {})[o.id] = o
        else:
            self._release(o, w)
            if o.remaining <= 1e-12:
                o.status = "filled"
            else:  # остаток рыночной заявки отбрасывается
                o.status = "partial" if o.remaining < o.qty else "cancelled"
                o.reason = "no_liquidity_or_funds"
        return o, trades

    def _release(self, o: Order, w: Wallet) -> None:
        """Вернуть остаток резерва заявки в свободный баланс."""
        if o.locked > 0:
            if o.side == BUY:
                w.usdt_locked -= o.locked
                w.usdt += o.locked
            else:
                w.btc_locked -= o.locked
                w.btc += o.locked
            o.locked = 0.0

    def cancel_order(self, order_id: int, owner: Optional[str] = None) -> bool:
        o = self.orders.get(order_id)
        if o is None or (owner is not None and o.owner != owner):
            return False
        (self.bids if o.side == BUY else self.asks).remove(o)
        self._forget(o)
        self._release(o, self.wallets[o.owner])
        o.status = "cancelled"
        return True

    def cancel_all(self, owner: str) -> int:
        ids = list(self.by_owner.get(owner, ()))
        return sum(self.cancel_order(i, owner) for i in ids)

    def open_orders(self, owner: str) -> list[Order]:
        return list(self.by_owner.get(owner, {}).values())

    def _forget(self, o: Order) -> None:
        self.orders.pop(o.id, None)
        self.by_owner.get(o.owner, {}).pop(o.id, None)

    # ---------- матчинг ----------
    def _match(self, taker: Order, tw: Wallet) -> list[Trade]:
        trades: list[Trade] = []
        book = self.asks if taker.side == BUY else self.bids
        while taker.remaining > 1e-12:
            best = book.best()
            if best is None:
                break
            if taker.type == LIMIT and ((taker.side == BUY and best > taker.price) or
                                        (taker.side == SELL and best < taker.price)):
                break
            maker = book.levels[best][0]
            if maker.owner == taker.owner:  # STP: снимаем свою старую заявку
                book.remove(maker)
                self._forget(maker)
                self._release(maker, self.wallets[maker.owner])
                maker.status = "cancelled"
                maker.reason = "self_trade_prevented"
                continue
            q = min(taker.remaining, maker.remaining)
            if taker.type == MARKET:
                if taker.side == BUY:
                    q = min(q, self.round_qty(tw.usdt / (best * (1 + self.taker_fee))))
                else:
                    q = min(q, self.round_qty(tw.btc))
                if q < self.min_qty:
                    break
            trades.append(self._execute(taker, maker, best, q))
        return trades

    def _execute(self, taker: Order, maker: Order, price: float, qty: float) -> Trade:
        buy_o, sell_o = (taker, maker) if taker.side == BUY else (maker, taker)
        bw, sw = self.wallets[buy_o.owner], self.wallets[sell_o.owner]
        cost = qty * price
        fee_b = cost * (self.taker_fee if buy_o is taker else self.maker_fee)
        fee_s = cost * (self.taker_fee if sell_o is taker else self.maker_fee)

        if buy_o.type == LIMIT:
            used = min(buy_o.locked, qty * buy_o.price * (1 + self.lock_fee))
            buy_o.locked -= used
            bw.usdt_locked -= used
            bw.usdt += used - (cost + fee_b)
        else:
            bw.usdt -= cost + fee_b
        bw.btc += qty

        if sell_o.type == LIMIT:
            sell_o.locked -= qty
            sw.btc_locked -= qty
        else:
            sw.btc -= qty
        sw.usdt += cost - fee_s
        self.wallets[FEE_ACCOUNT].usdt += fee_b + fee_s

        taker.remaining = max(0.0, taker.remaining - qty)
        maker.remaining = max(0.0, maker.remaining - qty)
        if taker.remaining < 1e-12:
            taker.remaining = 0.0
        if maker.remaining < 1e-12:
            maker.remaining = 0.0
        mside = self.asks if maker.side == SELL else self.bids
        mside.reduce(maker, qty)
        if maker.remaining == 0.0:
            maker.status = "filled"
            self._release(maker, self.wallets[maker.owner])
            self._forget(maker)
        else:
            maker.status = "partial"

        t = Trade(next(self._tid), self.clock(), price, qty, taker.side, buy_o.owner, sell_o.owner,
                  buy_o.id, sell_o.id, fee_b + fee_s)
        self.trades.append(t)
        self.last_price = price
        for cb in self.listeners:
            cb(t)
        return t
