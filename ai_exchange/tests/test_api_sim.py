import inspect
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exchange import ai_trader, features  # noqa: E402
from exchange.server import create_app, make_sim  # noqa: E402
from exchange.sim import Simulation, WARMUP_TICKS  # noqa: E402


@pytest.fixture(scope="module")
def sim():
    return make_sim(seed=3, model=None)


@pytest.fixture
def client(sim):
    return TestClient(create_app(sim, autostart=False))


def test_rest_order_flow(client, sim):
    ob = client.get("/orderbook?depth=5").json()
    assert ob["bids"] and ob["asks"] and ob["bids"][0][0] < ob["asks"][0][0]
    bal0 = client.get("/balance/user").json()
    best_bid = ob["bids"][0][0]
    r = client.post("/order", json={"participant": "user", "side": "buy", "type": "limit", "price": best_bid - 50, "qty": 0.01})
    assert r.status_code == 200 and r.json()["order"]["status"] == "open"
    oid = r.json()["order"]["id"]
    bal1 = client.get("/balance/user").json()
    assert bal1["usdt_locked"] > 0 and bal1["usdt_total"] == pytest.approx(bal0["usdt_total"])
    assert client.delete(f"/order/{oid}").status_code == 200
    assert client.delete(f"/order/{oid}").status_code == 404
    assert client.get("/balance/user").json()["usdt_locked"] == pytest.approx(0)


def test_rest_market_order_and_trades(client):
    r = client.post("/order", json={"participant": "user", "side": "buy", "type": "market", "qty": 0.01})
    assert r.status_code == 200 and r.json()["trades"]
    tr = client.get("/trades?limit=5").json()
    assert len(tr) == 5 and tr[0]["id"] > tr[-1]["id"]


def test_rest_validation_and_permissions(client):
    assert client.post("/order", json={"participant": "ai", "side": "buy", "type": "market", "qty": 1}).status_code == 403
    assert client.post("/order", json={"participant": "user", "side": "buy", "type": "limit", "qty": 1}).status_code == 422
    assert client.post("/order", json={"participant": "user", "side": "buy", "type": "limit", "price": 1, "qty": 1e9}).status_code == 400
    assert client.get("/balance/nobody").status_code == 404
    assert client.get("/balance/ai").json()["usdt_total"] > 0


def test_websocket_init_tick_and_commands():
    app = create_app(make_sim(seed=4, model=None), autostart=True)
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            init = ws.receive_json()
            assert init["type"] == "init" and len(init["candles"]) > 3
            tick = ws.receive_json()
            for key in ("price", "book", "ai", "candle", "eq", "trades", "thoughts"):
                assert key in tick
            assert tick["ai"]["mode"] in ("quoting", "caution", "emergency", "recovery")
            ws.send_json({"cmd": "speed", "value": 10})
            ws.send_json({"cmd": "shock"})
            for _ in range(15):
                tick = ws.receive_json()
                if tick["speed"] == 10 and tick["shocks"] == 1:
                    break
            assert tick["speed"] == 10 and tick["shocks"] == 1
            ws.send_json({"cmd": "pause"})
            for _ in range(5):
                tick = ws.receive_json()
            assert tick["paused"] is True
        assert app.state.ctx.errors == 0


def test_simulation_is_deterministic_and_balances_valid():
    def run():
        s = Simulation(seed=11, ai_mode="baseline")
        s.run(WARMUP_TICKS)
        s.start_ai()
        s.run(1500)
        return s
    a, b = run(), run()
    assert [(t.price, t.qty) for t in a.ex.trades] == [(t.price, t.qty) for t in b.ex.trades]
    for pid, w in a.ex.wallets.items():
        assert w.usdt >= -1e-6 and w.btc >= -1e-9 and w.usdt_locked >= -1e-6 and w.btc_locked >= -1e-9, pid
    usdt = sum(w.usdt_total for w in a.ex.wallets.values())
    assert usdt == pytest.approx(sum(5e7 if k.startswith("lp_") else 1e8 if k == "whale" else 3e6 if k not in ("ai", "user", "__fees__") else 0
                                      for k in a.ex.wallets) + 10_000 + 10_000, rel=1e-9)


def test_ai_does_not_see_the_future():
    """Если после момента T изменить «будущее» мира (скрытую цену), всё, что ИИ и рынок делали до T, остаётся тем же."""
    T = 1800

    class Altered(Simulation):
        def _advance_fundamental(self):
            super()._advance_fundamental()
            if self.tick_i > T:  # после T мир резко меняется, но до T — идентичен
                self._F *= 0.97 if self.tick_i % 2 else 1.02

    def run(cls):
        s = cls(seed=21, ai_mode="baseline")
        s.run(WARMUP_TICKS)
        s.start_ai()
        s.run(T - WARMUP_TICKS)
        return [(t.id, t.price, t.qty, t.buyer, t.seller) for t in s.ex.trades], s.ai.fills, s.eq

    assert run(Simulation) == run(Altered)


def test_ai_code_has_no_backdoor_to_simulation_internals():
    src = inspect.getsource(ai_trader) + inspect.getsource(features)
    import re
    for bad in (r"\b_F\b", "fundamental", r"from \.sim", r"import sim", "ref_price", "mid_hist", r"\bagents\b", r"self\.sim"):
        assert not re.search(bad, src), bad
    assert "Gateway" in src


def test_shock_makes_ai_react():
    reacted = 0
    for seed in (1, 2, 3):
        s = Simulation(seed=seed, ai_mode="baseline")
        s.run(WARMUP_TICKS)
        s.start_ai()
        s.run(1800)
        pos0, half0 = s.ex.wallets["ai"].btc_total, s.ai.half
        modes, half_max, pos1 = set(), 0.0, pos0
        s.shock()
        for _ in range(900):
            s.step()
            modes.add(s.ai.mode)
            half_max = max(half_max, s.ai.half)
            pos1 = min(pos1, s.ex.wallets["ai"].btc_total)  # минимальная позиция за 90 с после шока
        if "emergency" in modes and pos1 < pos0 * 0.2 and half_max > half0 * 1.5:
            reacted += 1
        for w in s.ex.wallets.values():
            assert w.usdt >= -1e-6 and w.btc >= -1e-9
    assert reacted >= 2
