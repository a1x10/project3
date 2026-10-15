"""FastAPI: POST /webhook (от Evolution API) и GET /health."""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request

from .brain import Brain
from .config import Settings, settings
from .db import DB
from .evolution import Evolution
from .llm import SwitchingLLM


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def create_app(s: Settings = settings, brain: Brain | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal brain
        own_brain = brain is None
        if own_brain:
            setup_logging(s.log_level)
            if not s.webhook_secret:
                logging.getLogger("stella").warning("WEBHOOK_SECRET не задан — вебхук без проверки!")
            db = DB(s.database_url)
            evo = Evolution(s.evolution_url, s.evolution_api_key, s.evolution_instance)
            brain = Brain(s, db, evo, SwitchingLLM(s))
            await brain.start()
        app.state.brain = brain
        yield
        if own_brain:
            await brain.evo.close()
            await brain.db.close()

    app = FastAPI(title="Stella bot", lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.post("/webhook")
    @app.post("/webhook/{event_path:path}")  # если в Evolution включат byEvents
    async def webhook(request: Request, x_webhook_secret: str | None = Header(default=None),
                      event_path: str = "") -> dict[str, Any]:
        if s.webhook_secret and not hmac.compare_digest(x_webhook_secret or "", s.webhook_secret):
            raise HTTPException(status_code=401)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(status_code=400) from None
        if isinstance(payload, dict):
            if event_path and not payload.get("event"):
                payload["event"] = event_path
            # Отвечаем 200 сразу, всё остальное — в фоне
            request.app.state.brain.spawn(request.app.state.brain.handle_payload(payload))
        return {"ok": True}

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        b: Brain = request.app.state.brain
        return {
            "ok": True,
            "whatsapp": b.connection_state,
            "llm": getattr(b.llm, "name", "?"),
            "spend_today_usd": round(await b.refresh_spend(), 4),
            "over_budget": b.over_budget(),
        }

    return app


app = create_app()
