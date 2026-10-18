"""FastAPI: POST /webhook (от Evolution API), GET /health, панель управления (/panel/ и /admin/api),
страница розыгрыша (/giveaway/)."""

from __future__ import annotations

import hmac
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

from .admin import build_router, install_ring_log, is_local_request
from .brain import Brain
from .config import Settings, settings
from .db import DB
from .evolution import Evolution
from .giveaway import build_router as build_giveaway_router
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


ADMIN_BODY_LIMIT = 64 * 1024
WEBHOOK_BODY_LIMIT = 20 * 1024 * 1024
# что видно из интернета через туннель Cloudflare: панель, её API и страница розыгрыша
PUBLIC_PREFIXES = ("/panel", "/admin/api", "/giveaway")
SMALL_BODY_PREFIXES = ("/admin", "/giveaway")


class BodyTooLarge(Exception):
    pass


class GuardMiddleware:
    """1) Через туннель (есть CF-Connecting-IP) наружу видны только панель и её API — вебхук и health нет.
    2) Ограничение размера тела запроса: огромный JSON не должен уронить бота ещё до проверки пароля."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if "cf-connecting-ip" in headers and not path.startswith(PUBLIC_PREFIXES):
            return await self._reply(send, 404, b'{"error":"not found"}')
        limit = ADMIN_BODY_LIMIT if path.startswith(SMALL_BODY_PREFIXES) else WEBHOOK_BODY_LIMIT
        try:
            if int(headers.get("content-length") or 0) > limit:
                return await self._reply(send, 413, b'{"error":"too large"}')
        except ValueError:
            return await self._reply(send, 400, b'{"error":"bad length"}')
        seen = 0
        started = False

        async def limited_receive():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:  # тело без Content-Length (чанками) — считаем сами
                    raise BodyTooLarge()
            return message

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except BodyTooLarge:
            if not started:
                await self._reply(send, 413, b'{"error":"too large"}')

    @staticmethod
    async def _reply(send, status: int, body: bytes) -> None:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


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
            if s.telegram_bot_token:  # та же Стелла и в Telegram: отправка — туда, откуда чат
                from .telegram import Messenger, Telegram

                evo = Messenger(evo, Telegram(s.telegram_bot_token))
            brain = Brain(s, db, evo, SwitchingLLM(s))
            await brain.start()
        app.state.brain = brain
        yield
        if own_brain:
            await brain.evo.close()
            await brain.db.close()

    app = FastAPI(title="Stella bot", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    install_ring_log()  # последние строки лога — для вкладки «Журнал» в панели
    app.add_middleware(GuardMiddleware)

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
        elif path.startswith("/giveaway"):
            from .giveaway import CSP as GIVEAWAY_CSP

            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Content-Security-Policy"] = GIVEAWAY_CSP
            if path.startswith(("/giveaway/api", "/giveaway/admin")):
                response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"error": str(exc.detail), "detail": str(exc.detail)}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "invalid", "detail": "неверные данные в запросе"}, status_code=422)

    app.include_router(build_router(lambda request: request.app.state.brain))
    def giveaway_of(request: Request) -> Any:
        b: Brain = request.app.state.brain
        return b.giveaway if b.s.giveaway_enabled else None

    app.include_router(build_giveaway_router(giveaway_of))
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
        if not is_local_request(request):
            return {"ok": True}  # не с самого сервера — без подробностей
        return {
            "ok": True,
            "whatsapp": b.connection_state,
            "llm": getattr(b.llm, "name", "?"),
            "spend_today_usd": round(await b.refresh_spend(), 4),
            "over_budget": b.over_budget(),
        }

    return app


app = create_app()
