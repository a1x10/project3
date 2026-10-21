"""FastAPI-сервер: REST-интерфейс биржи + WebSocket для сайта + цикл симуляции."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analyst import Analyst
from .ai_trader import AI_ID, PriceModel
from .sim import CANDLE_SEC, WARMUP_TICKS, Simulation, book_view

log = logging.getLogger("server")
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
TICK_SEC = 0.1
DEMO_USER = "user"  # единственный участник, которым можно управлять через REST


class OrderIn(BaseModel):
    participant: str = DEMO_USER
    side: Literal["buy", "sell"]
    type: Literal["limit", "market"] = "limit"
    price: Optional[float] = Field(None, gt=0)
    qty: float = Field(..., gt=0)
    post_only: bool = False


def order_dict(o) -> dict:
    return {"id": o.id, "owner": o.owner, "side": o.side, "type": o.type, "price": o.price, "qty": o.qty,
            "remaining": o.remaining, "status": o.status, "reason": o.reason}


def trade_dict(t, t0: int = 0) -> dict:
    return {"id": t.id, "ts": t0 + t.ts, "price": t.price, "qty": t.qty, "taker_side": t.taker_side,
            "buyer": t.buyer, "seller": t.seller, "fee": t.fee}


class Context:
    def __init__(self, sim: Simulation, analyst: Analyst):
        self.sim = sim
        self.analyst = analyst
        self.paused = False
        self.speed = 1
        self.clients: dict[WebSocket, dict] = {}
        self.task: Optional[asyncio.Task] = None
        self.errors = 0

    # ---------- данные для сайта ----------
    def init_message(self) -> dict:
        s = self.sim
        n = 720
        times = {c["time"] for c in s.candles[-n:]}
        return {
            "type": "init", "candle_sec": CANDLE_SEC, "candles": s.candles[-n:],
            "equity": s.eq_curve[-n:], "marks": [m for t, m in s.marks.items() if t in times],
            "thoughts": list(s.ai.thoughts)[-30:] if s.ai else [], "trades": list(s.ui_trades)[-40:],
            "shocks": [s.t0_wall + t for t in s.shocks], "t0": s.t0_wall,
            "model": getattr(s.ai.model, "meta", None) and {
                "corr": s.ai.model.meta["metrics_valid"]["corr"],
                "dir_acc": s.ai.model.meta["metrics_valid"]["dir_acc"],
                "horizon": s.ai.model.meta["horizon_sec"]} if s.ai and s.ai.model else None,
        }

    def tick_message(self, last_trade: int, last_thought: int) -> dict:
        s = self.sim
        price = s.ex.last_price or s.p0
        base = s.session_p0 or s.p0
        ai = s.ai
        summ = s.ai_summary()
        msg = {
            "type": "tick", "paused": self.paused, "speed": self.speed, "sim_t": s.now,
            "price": price, "change_pct": (price / base - 1) * 100,
            "candle": s.candles[-1] if s.candles else None,
            "book": book_view(s, 12),
            "trades": [t for t in list(s.ui_trades)[-80:] if t["id"] > last_trade],
            "eq": s.eq_curve[-1] if s.eq_curve else None,
            "marks": [s.marks[t] for t in (s.candles[-1]["time"], s.candles[-2]["time"] if len(s.candles) > 1 else -1)
                      if t in s.marks],
            "shocks": len(s.shocks),
            "analyst": self.analyst.view(),
        }
        if ai is not None:
            msg["ai"] = {**summ, **ai.view()}
            msg["thoughts"] = [t for t in ai.thoughts if t["id"] > last_thought]
        return msg

    async def broadcast(self) -> None:
        if not self.clients:
            return
        dead = []
        for ws, cur in list(self.clients.items()):
            msg = self.tick_message(cur["trade"], cur["thought"])
            if msg["trades"]:
                cur["trade"] = msg["trades"][-1]["id"]
            if msg.get("thoughts"):
                cur["thought"] = msg["thoughts"][-1]["id"]
            try:
                await ws.send_text(json.dumps(msg))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.pop(ws, None)

    # ---------- управление ----------
    def command(self, cmd: str, value=None) -> None:
        if cmd == "pause":
            self.paused = True
        elif cmd == "resume":
            self.paused = False
        elif cmd == "toggle_pause":
            self.paused = not self.paused
        elif cmd == "speed":
            self.speed = 10 if int(value or 1) >= 10 else 1
        elif cmd == "shock":
            self.sim.shock()

    def analyst_stats(self) -> dict:
        s = self.sim
        d = s.ai_summary()
        ai = s.ai
        return {
            "цена": round(s.ex.last_price or s.p0, 1),
            "изменение_с_начала_%": round(((s.ex.last_price or s.p0) / (s.session_p0 or s.p0) - 1) * 100, 2),
            "прибыль_ИИ_%": round(d.get("profit_pct", 0), 3), "Buy_and_Hold_%": round(d.get("bh_pct", 0), 3),
            "сделок_ИИ": d.get("fills"), "прибыльных_%": None if d.get("win_rate") is None else round(d["win_rate"]),
            "макс_просадка_%": round(d.get("max_dd", 0), 3), "позиция_BTC": round(d.get("pos", 0), 4),
            "режим_ИИ": ai.mode if ai else None, "прогноз_модели_б.п.": round(ai.pred, 2) if ai else None,
            "спред_ИИ_б.п.": round(2 * ai.half, 1) if ai else None, "рыночных_шоков": len(s.shocks),
            "последние_мысли_ИИ": [t["text"] for t in list(ai.thoughts)[-6:]] if ai else [],
        }

    async def loop(self) -> None:
        loop = asyncio.get_running_loop()
        nxt = loop.time()
        while True:
            try:
                if not self.paused:
                    for _ in range(self.speed):
                        self.sim.step()
                await self.broadcast()
                if self.analyst.due():
                    asyncio.create_task(self.analyst.run(self.analyst_stats))
            except Exception:
                self.errors += 1
                log.exception("Ошибка в цикле симуляции")
                await asyncio.sleep(0.5)
            nxt += TICK_SEC
            delay = nxt - loop.time()
            if delay < 0:
                nxt = loop.time()
                delay = 0
            await asyncio.sleep(delay)


def make_sim(seed: Optional[int] = None, model: Optional[PriceModel] = None, **kw) -> Simulation:
    seed = seed if seed is not None else random.randint(1, 10_000)
    sim = Simulation(seed=seed, ai_mode="ml" if model else "baseline", model=model,
                     wall_t0=int(time.time()) - int(WARMUP_TICKS * 0.1), **kw)
    sim.run(WARMUP_TICKS)
    sim.start_ai()
    return sim


def create_app(sim: Optional[Simulation] = None, autostart: bool = True) -> FastAPI:
    if sim is None:
        try:
            model = PriceModel.load_default()
        except Exception as e:  # повреждённая/устаревшая модель
            log.warning("Модель не загружена: %s", e)
            model = None
        sim = make_sim(model=model)
    ctx = Context(sim, Analyst())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if autostart:
            ctx.task = asyncio.create_task(ctx.loop())
        yield
        if ctx.task:
            ctx.task.cancel()

    app = FastAPI(title="AI Exchange", lifespan=lifespan)
    app.state.ctx = ctx
    ex = sim.ex

    @app.get("/")
    def index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))

    @app.post("/order")
    def post_order(o: OrderIn):
        if o.participant != DEMO_USER:
            raise HTTPException(403, f"Через REST можно торговать только участником '{DEMO_USER}'")
        if o.type == "limit" and o.price is None:
            raise HTTPException(422, "Для лимитной заявки нужна цена")
        order, trades = ex.place_order(o.participant, o.side, o.type, o.qty, o.price, o.post_only)
        if order.status == "rejected":
            return JSONResponse(status_code=400, content={"order": order_dict(order), "error": order.reason})
        return {"order": order_dict(order), "trades": [trade_dict(t, sim.t0_wall) for t in trades]}

    @app.delete("/order/{order_id}")
    def delete_order(order_id: int, participant: str = DEMO_USER):
        if participant != DEMO_USER:
            raise HTTPException(403, "Нельзя снимать чужие заявки")
        if not ex.cancel_order(order_id, participant):
            raise HTTPException(404, "Открытая заявка не найдена")
        return {"cancelled": order_id}

    @app.get("/orderbook")
    def get_orderbook(depth: int = 20):
        lv = ex.levels(max(1, min(depth, 100)))
        return {"bids": [[p, q, n] for p, q, n in lv["bids"]], "asks": [[p, q, n] for p, q, n in lv["asks"]],
                "mid": ex.mid(), "last": ex.last_price}

    @app.get("/balance/{pid}")
    def get_balance(pid: str):
        b = ex.balance(pid)
        if b is None:
            raise HTTPException(404, "Участник не найден")
        return {"participant": pid, **b}

    @app.get("/trades")
    def get_trades(limit: int = 50):
        limit = max(1, min(limit, 500))
        return [trade_dict(t, sim.t0_wall) for t in list(ex.trades)[-limit:]][::-1]

    @app.get("/api/summary")
    def summary():
        return {"ai": sim.ai_summary(), "ai_view": sim.ai.view() if sim.ai else None, "price": ex.last_price,
                "sim_time": sim.now, "paused": ctx.paused, "speed": ctx.speed, "errors": ctx.errors,
                "shocks": len(sim.shocks), "agents": len(sim.agents), "analyst": ctx.analyst.view(),
                "ml": bool(sim.ai and sim.ai.model)}

    @app.post("/control/{cmd}")
    def control(cmd: str, value: Optional[int] = None):
        if cmd not in ("pause", "resume", "toggle_pause", "speed", "shock"):
            raise HTTPException(404, "Неизвестная команда")
        ctx.command(cmd, value)
        return {"paused": ctx.paused, "speed": ctx.speed}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        cur = {"trade": 0, "thought": 0}
        init = ctx.init_message()
        if init["trades"]:
            cur["trade"] = init["trades"][-1]["id"]
        if init["thoughts"]:
            cur["thought"] = init["thoughts"][-1]["id"]
        await ws.send_text(json.dumps(init))
        ctx.clients[ws] = cur
        try:
            while True:
                data = json.loads(await ws.receive_text())
                ctx.command(data.get("cmd", ""), data.get("value"))
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            ctx.clients.pop(ws, None)

    app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static")
    return app
