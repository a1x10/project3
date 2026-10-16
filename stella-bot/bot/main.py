"""FastAPI: POST /webhook (от Evolution API), GET /health, панель управления (/panel/ и /admin/api)."""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .admin import build_router, install_ring_log
from .brain import Brain
from .config import Settings, settings
from .db import DB
from .evolution import Evolution
from .llm import SwitchingLLM

PANEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "panel")
PANEL_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
             "connect-src 'self' https: http://localhost:* http://127.0.0.1:*; base-uri 'none'; "
             "form-action 'none'; frame-ancestors 'none'")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    install_ring_log()


def _is_local(request: Request) -> bool:
    """Запрос изнутри сервера (docker-сеть / localhost), а не через туннель или nginx."""
    if request.headers.get("cf-connecting-ip") or request.headers.get("x-real-ip") \
            or request.headers.get("x-forwarded-for"):
        return False
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("testclient", "localhost")


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

    app = FastAPI(title="Stella bot", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    install_ring_log()  # последние строки лога — для вкладки «Журнал» в панели

    # Панель с GitHub Pages ходит сюда с другого сайта — разрешаем только перечисленные (PANEL_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.panel_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False,
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith(("/admin", "/panel")):
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = PANEL_CSP
            if request.headers.get("x-forwarded-proto") == "https" or request.headers.get("cf-connecting-ip"):
                response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": str(exc.detail), "detail": str(exc.detail)}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "invalid", "detail": "неверные данные в запросе"}, status_code=422)

    app.include_router(build_router(lambda request: request.app.state.brain))
    if os.path.isdir(PANEL_DIR):
        app.mount("/panel", StaticFiles(directory=PANEL_DIR, html=True), name="panel")

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
        if not _is_local(request):
            return {"ok": True}  # через туннель — без подробностей
        return {
            "ok": True,
            "whatsapp": b.connection_state,
            "llm": getattr(b.llm, "name", "?"),
            "spend_today_usd": round(await b.refresh_spend(), 4),
            "over_budget": b.over_budget(),
        }

    return app


app = create_app()
