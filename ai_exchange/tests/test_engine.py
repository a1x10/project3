import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exchange.engine import BUY, SELL, LIMIT, MARKET, Exchange, FEE_ACCOUNT  # noqa: E402

FEE = 0.0005


@pytest.fixture
def ex():
    e = Exchange(maker_fee=FEE, taker_fee=FEE)
    for name in ("a", "b", "c", "d"):
        e.create_wallet(name, usdt=1_000_000, btc=100)
    return e


def total_supply(e):
    usdt = sum(w.usdt_total for w in e.wallets.values())
    btc = sum(w.btc_total for w in e.wallets.values())
    return usdt, btc


def test_limit_rests_and_locks_funds(ex):
    o, tr = ex.place_order("a", BUY, LIMIT, 1.0, 100)
    assert tr == [] and o.status == "open"
    w = ex.wallets["a"]
    assert w.usdt_locked == pytest.approx(100 * (1 + FEE))
    assert ex.best_bid() == 100
    assert ex.balance("a")["usdt_total"] == pytest.approx(1_000_000)


def test_price_priority(ex):
    ex.place_order("a", SELL, LIMIT, 1, 101)
    ex.place_order("b", SELL, LIMIT, 1, 100)
    ex.place_order("c", SELL, LIMIT, 1, 102)
    _, tr = ex.place_order("d", BUY, MARKET, 2)
    assert [(t.price, t.seller) for t in tr] == [(100, "b"), (101, "a")]


def test_time_priority_within_level(ex):
    ex.place_order("a", SELL, LIMIT, 1, 100)
    ex.place_order("b", SELL, LIMIT, 1, 100)
    _, tr = ex.place_order("d", BUY, MARKET, 1.5)
    assert [(t.seller, t.qty) for t in tr] == [("a", 1.0), ("b", 0.5)]
    # остаток b остался первым в очереди
    assert ex.asks.top(1)[0][1] == pytest.approx(0.5)
    _, tr2 = ex.place_order("d", BUY, MARKET, 0.5)
    assert tr2[0].seller == "b"


def test_trade_executes_at_maker_price_and_refunds_difference(ex):
    ex.place_order("a", SELL, LIMIT, 1, 100)
    o, tr = ex.place_order("b", BUY, LIMIT, 1, 105)  # агрессивный лимит
    assert tr[0].price == 100 and tr[0].taker_side == BUY
    assert o.status == "filled"
    w = ex.wallets["b"]
    assert w.usdt_locked == pytest.approx(0)
    assert w.usdt == pytest.approx(1_000_000 - 100 * (1 + FEE))
    assert w.btc == pytest.approx(101)


def test_partial_fill_then_rest(ex):
    ex.place_order("a", SELL, LIMIT, 1, 100)
    o, tr = ex.place_order("b", BUY, LIMIT, 3, 100)
    assert len(tr) == 1 and tr[0].qty == 1
    assert o.status == "partial" and o.remaining == pytest.approx(2)
    assert ex.best_bid() == 100 and ex.best_ask() is None
    w = ex.wallets["b"]
    assert w.usdt_locked == pytest.approx(2 * 100 * (1 + FEE))


def test_fees_both_sides(ex):
    ex.place_order("a", SELL, LIMIT, 2, 100)
    ex.place_order("b", BUY, MARKET, 2)
    assert ex.wallets["b"].usdt == pytest.approx(1_000_000 - 200 * (1 + FEE))
    assert ex.wallets["a"].usdt == pytest.approx(1_000_000 + 200 * (1 - FEE))
    assert ex.wallets[FEE_ACCOUNT].usdt == pytest.approx(2 * 200 * FEE)
    assert ex.trades[-1].fee == pytest.approx(2 * 200 * FEE)


def test_conservation_after_random_activity():
    import random
    rng = random.Random(1)
    e = Exchange()
    ids = [f"p{i}" for i in range(6)]
    for i in ids:
        e.create_wallet(i, usdt=500_000, btc=10)
    before = total_supply(e)
    for _ in range(3000):
        who = rng.choice(ids)
        side = rng.choice([BUY, SELL])
        r = rng.random()
        if r < 0.15:
            e.cancel_all(who)
        elif r < 0.35:
            e.place_order(who, side, MARKET, rng.uniform(0.01, 2))
        else:
            e.place_order(who, side, LIMIT, rng.uniform(0.01, 2), 100 + rng.uniform(-3, 3))
    after = total_supply(e)
    assert after[0] == pytest.approx(before[0], rel=1e-9)
    assert after[1] == pytest.approx(before[1], rel=1e-9)
    for i in ids:
        e.cancel_all(i)
        w = e.wallets[i]
        assert w.usdt_locked == pytest.approx(0, abs=1e-6) and w.btc_locked == pytest.approx(0, abs=1e-9)
        assert w.usdt >= -1e-9 and w.btc >= -1e-9


def test_cancel_releases_funds_and_removes_level(ex):
    o, _ = ex.place_order("a", SELL, LIMIT, 1, 100)
    assert ex.wallets["a"].btc_locked == 1
    assert ex.cancel_order(o.id, "a") is True
    assert ex.best_ask() is None
    assert ex.wallets["a"].btc == 100 and ex.wallets["a"].btc_locked == 0
    assert ex.cancel_order(o.id) is False


def test_cancel_wrong_owner_denied(ex):
    o, _ = ex.place_order("a", BUY, LIMIT, 1, 100)
    assert ex.cancel_order(o.id, "b") is False
    assert ex.best_bid() == 100


def test_insufficient_funds_rejected():
    e = Exchange()
    e.create_wallet("poor", usdt=100, btc=0.1)
    o, _ = e.place_order("poor", BUY, LIMIT, 1, 100)
    assert o.status == "rejected" and o.reason == "insufficient_usdt"
    o, _ = e.place_order("poor", SELL, LIMIT, 1, 100)
    assert o.status == "rejected" and o.reason == "insufficient_btc"
    o, _ = e.place_order("nobody", BUY, LIMIT, 1, 100)
    assert o.reason == "unknown_participant"


def test_market_buy_limited_by_funds():
    e = Exchange()
    e.create_wallet("mm", usdt=0, btc=10)
    e.create_wallet("t", usdt=250, btc=0)
    e.place_order("mm", SELL, LIMIT, 5, 100)
    o, tr = e.place_order("t", BUY, MARKET, 5)
    assert sum(t.qty for t in tr) == pytest.approx(250 / (100 * (1 + FEE)), abs=1e-5)
    assert e.wallets["t"].usdt >= 0
    assert o.status == "partial"


def test_market_on_empty_book_does_nothing(ex):
    o, tr = ex.place_order("a", BUY, MARKET, 1)
    assert tr == [] and o.status == "cancelled"
    assert ex.wallets["a"].usdt == 1_000_000


def test_post_only_rejected_when_crossing(ex):
    ex.place_order("a", SELL, LIMIT, 1, 100)
    o, tr = ex.place_order("b", BUY, LIMIT, 1, 100, post_only=True)
    assert o.status == "rejected" and o.reason == "post_only_would_cross" and not tr
    o, _ = ex.place_order("b", BUY, LIMIT, 1, 99.9, post_only=True)
    assert o.status == "open"


def test_self_trade_prevention(ex):
    ex.place_order("a", SELL, LIMIT, 1, 100)
    ex.place_order("b", SELL, LIMIT, 1, 101)
    o, tr = ex.place_order("a", BUY, LIMIT, 1, 101)
    assert [t.seller for t in tr] == ["b"]  # собственная заявка снята, сделки с собой нет
    assert ex.wallets["a"].btc_locked == 0


def test_levels_aggregate_and_order(ex):
    ex.place_order("a", BUY, LIMIT, 1, 99)
    ex.place_order("b", BUY, LIMIT, 2, 99)
    ex.place_order("c", BUY, LIMIT, 1, 98)
    ex.place_order("a", SELL, LIMIT, 1, 101)
    lv = ex.levels(5)
    assert lv["bids"][0] == (99, 3, 2) and lv["bids"][1][0] == 98
    assert lv["asks"][0][0] == 101
    assert ex.mid() == 100


def test_sweep_multiple_levels_updates_last_price(ex):
    for p in (100, 101, 102):
        ex.place_order("a", SELL, LIMIT, 1, p)
    _, tr = ex.place_order("b", BUY, LIMIT, 2.5, 101.5)
    assert [t.price for t in tr] == [100, 101]
    assert ex.last_price == 101
    assert ex.best_bid() == 101.5 and ex.best_ask() == 102


def test_qty_rounding_and_tiny_rejected(ex):
    o, _ = ex.place_order("a", BUY, LIMIT, 1e-9, 100)
    assert o.status == "rejected" and o.reason == "qty_too_small"
