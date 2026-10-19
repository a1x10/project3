"""Панель управления: вход по двум паролям, защита от подбора, сессии, действия."""

import asyncio
import secrets
import time

import httpx
import pytest

from bot import admin
from bot.admin import AdminAuth
from bot.main import create_app

from .conftest import GROUP, PETYA, settle, upsert

ORIGIN = "https://a1x10.github.io"
# Пароли в тестах — случайные на каждый запуск: настоящих паролей в репозитории быть не должно
P1, P2 = secrets.token_hex(6), secrets.token_hex(6)


@pytest.fixture(autouse=True)
def fast_login(monkeypatch):
    monkeypatch.setattr(admin, "LOGIN_DELAY", 0)


@pytest.fixture
async def panel(brain):
    brain.s.panel_password_1, brain.s.panel_password_2 = P1, P2
    brain.s.panel_origins = [ORIGIN]
    brain.admin = AdminAuth(brain.s)
    app = create_app(brain.s, brain=brain)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://bot") as client:
            yield client


async def login(client, p1=None, p2=None, ip="1.2.3.4"):
    p1 = P1 if p1 is None else p1
    p2 = P2 if p2 is None else p2
    return await client.post("/admin/api/login", json={"p1": p1, "p2": p2}, headers={"cf-connecting-ip": ip})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def test_panel_disabled_without_passwords(brain):
    brain.s.panel_password_1, brain.s.panel_password_2 = P1, ""
    brain.admin = AdminAuth(brain.s)
    app = create_app(brain.s, brain=brain)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bot") as client:
            r = await login(client)
            assert r.status_code == 503 and r.json()["error"] == "disabled"
            assert (await client.get("/admin/api/status")).status_code == 503


async def test_two_passwords_and_session(panel, brain):
    assert (await panel.get("/admin/api/status")).status_code == 401
    r = await login(panel, P1, "0000")
    assert r.status_code == 401 and r.json() == {"error": "wrong"}  # не говорим, какой пароль неверный
    r = await login(panel, P2, P1)
    assert r.status_code == 401
    r = await login(panel)
    assert r.status_code == 200
    token = r.json()["token"]
    assert len(token) >= 40
    status = (await panel.get("/admin/api/status", headers=auth(token))).json()
    assert status["llm_model"] and "spend_today_usd" in status
    assert (await panel.get("/admin/api/status", headers=auth(token + "x"))).status_code == 401
    assert (await panel.post("/admin/api/logout", headers=auth(token))).status_code == 200
    assert (await panel.get("/admin/api/status", headers=auth(token))).status_code == 401
    await settle(brain)


async def test_bruteforce_lock_per_ip_and_global(panel, brain):
    for _ in range(admin.IP_MAX_FAILS):
        assert (await login(panel, "1111", "2222", ip="9.9.9.9")).status_code == 401
    r = await login(panel, ip="9.9.9.9")  # даже верные пароли не пускают, пока блок
    assert r.status_code == 429 and r.json()["retry_after"] > 0
    assert (await login(panel, ip="8.8.8.8")).status_code == 200  # другой адрес — пускает
    # распределённый подбор: много адресов — общий замок для всех
    for i in range(admin.GLOBAL_MAX_FAILS):
        await login(panel, "1", "2", ip=f"10.0.{i // 250}.{i % 250}")
    r = await login(panel, ip="7.7.7.7")
    assert r.status_code == 429
    await settle(brain)


def test_session_expires_when_idle():
    t = [0.0]
    s = type("S", (), {"panel_password_1": "1", "panel_password_2": "2", "panel_session_hours": 8,
                       "panel_idle_minutes": 30})()
    a = AdminAuth(s, clock=lambda: t[0])
    token = a.new_session("ip")
    t[0] = 29 * 60
    assert a.verify(token)
    t[0] += 31 * 60
    assert a.verify(token) is None
    token = a.new_session("ip")
    for _ in range(20):  # активна, но дольше 8 часов — всё равно выход
        t[0] += 25 * 60
        a.verify(token)
    assert a.verify(token) is None


async def test_cors_only_for_allowed_site(panel):
    r = await panel.options("/admin/api/login", headers={
        "Origin": ORIGIN, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"})
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    r = await panel.options("/admin/api/login", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") is None
    r = await panel.get("/admin/api/status")
    assert r.headers["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in r.headers["content-security-policy"]


async def test_chat_actions_and_settings(panel, brain):
    brain.llm.queue = ["привет"]
    await brain.handle_payload(upsert("стелла привет"))
    await brain.handle_payload(upsert("я петя", sender=PETYA, name="Петя"))
    await settle(brain)
    token = (await login(panel)).json()["token"]
    h = auth(token)
    chats = (await panel.get("/admin/api/chats", headers=h)).json()["chats"]
    chat = next(c for c in chats if c["is_group"])
    cid = chat["id"]
    msgs = (await panel.get(f"/admin/api/chats/{cid}/messages", headers=h)).json()["messages"]
    assert {"стелла привет", "привет", "я петя"} <= {m["text"] for m in msgs}
    assert any(m["role"] == "assistant" and m["sender"] == "Стелла" for m in msgs)

    assert (await panel.post(f"/admin/api/chats/{cid}/send", json={"text": "всем ку\nкак дела"},
                             headers=h)).status_code == 200
    await settle(brain)
    assert brain.evo.texts()[-2:] == ["всем ку", "как дела"]

    r = await panel.post(f"/admin/api/chats/{cid}/pause", json={"minutes": 60}, headers=h)
    assert r.json()["paused_until"]
    chats = (await panel.get("/admin/api/chats", headers=h)).json()["chats"]
    assert next(c for c in chats if c["id"] == cid)["paused_until"]
    await panel.post(f"/admin/api/chats/{cid}/unpause", headers=h)
    assert (await panel.post(f"/admin/api/chats/{cid}/chime", json={"level": "loud"}, headers=h)).status_code == 422

    people = (await panel.get(f"/admin/api/chats/{cid}/people", headers=h)).json()["people"]
    petya = next(p for p in people if p["name"] == "Петя")
    r = await panel.put(f"/admin/api/chats/{cid}/people/{petya['id']}/profile", json={"fields": {"игры": "майн"}},
                        headers=h)
    assert r.json()["profile"]["игры"] == "майн"
    assert (await panel.put(f"/admin/api/chats/{cid}/people/99999/profile", json={"fields": {"a": "b"}},
                            headers=h)).status_code == 404

    r = await panel.put("/admin/api/settings", json={"llm_model": "claude-sonnet-5-5", "media_per_day": 5}, headers=h)
    assert r.status_code == 200 and brain.s.llm_model == "claude-sonnet-5-5" and brain.s.media_per_day == 5
    assert (await panel.put("/admin/api/settings", json={"panel_password_1": "x"}, headers=h)).status_code == 400
    assert (await panel.put("/admin/api/settings", json={"daily_budget_usd": -5}, headers=h)).status_code == 400
    # настройки из панели переживают перезапуск
    brain.s.llm_model = "claude-opus-5-5"
    await admin.load_overrides(brain)
    assert brain.s.llm_model == "claude-sonnet-5-5"

    log = (await panel.get("/admin/api/log", headers=h)).json()["lines"]
    assert any("настройки" in line["text"] for line in log)
    await settle(brain)


async def test_subscriptions_from_panel(panel, brain):
    await brain.handle_payload(upsert("я петя", sender=PETYA, name="Петя"))
    await settle(brain)
    h = auth((await login(panel)).json()["token"])
    cid = next(c for c in (await panel.get("/admin/api/chats", headers=h)).json()["chats"] if c["is_group"])["id"]
    r = await panel.put("/admin/api/settings", json={"free_replies_per_day": 10, "support_contact": "@help",
                                                     "limit_message": "Лимит кончился. " + "о" * 500}, headers=h)
    assert r.status_code == 200 and brain.s.free_replies_per_day == 10 and len(brain.s.limit_message) > 500

    people = (await panel.get(f"/admin/api/chats/{cid}/people", headers=h)).json()["people"]
    petya = next(p for p in people if p["name"] == "Петя")
    assert petya["plan"]["kind"] == "free" and petya["plan"]["daily"] == 10
    path = f"/admin/api/chats/{cid}/people/{petya['id']}/plan"
    r = await panel.put(path, json={"kind": "unlimited", "days": 30}, headers=h)
    plan = r.json()["plan"]
    assert plan["kind"] == "unlimited" and plan["daily"] == 0 and plan["until"] > time.time() + 29 * 86400
    plan = (await panel.put(path, json={"kind": "limit", "limit": 3}, headers=h)).json()["plan"]
    assert plan["kind"] == "limit" and plan["daily"] == 3 and plan["until"] is None
    assert (await panel.put(path, json={"kind": "limit", "limit": 0}, headers=h)).status_code == 400
    assert (await panel.put(path, json={"kind": "vip"}, headers=h)).status_code == 422
    assert (await panel.put(path, json={"kind": "unlimited", "days": -1}, headers=h)).status_code == 422
    assert (await panel.put(f"/admin/api/chats/{cid}/people/99999/plan", json={"kind": "free"},
                            headers=h)).status_code == 404
    assert (await panel.put(path, json={"kind": "free"}, headers=h)).json()["plan"]["kind"] == "free"
    assert (await panel.put(path, json={"kind": "free"})).status_code == 401


async def test_tunnel_exposes_only_the_panel(panel):
    tunnel = {"cf-connecting-ip": "5.5.5.5"}
    assert (await panel.get("/health", headers=tunnel)).status_code == 404
    assert (await panel.post("/webhook", json={}, headers=tunnel)).status_code == 404
    assert (await panel.post("/webhook/messages-upsert", json={}, headers=tunnel)).status_code == 404
    assert (await login(panel, ip="5.5.5.5")).status_code == 200  # панель — доступна
    assert "spend_today_usd" in (await panel.get("/health")).json()  # с самого сервера — подробно


async def test_huge_body_is_rejected_before_parsing(panel):
    big = "x" * (200 * 1024)
    r = await panel.post("/admin/api/login", json={"p1": big, "p2": big}, headers={"cf-connecting-ip": "6.6.6.6"})
    assert r.status_code == 413

    async def chunks():
        for _ in range(100):
            yield b"[" * 1024

    r = await panel.post("/admin/api/login", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code in (400, 413, 422)


async def test_parallel_guesses_cannot_skip_the_lock(panel, monkeypatch):
    monkeypatch.setattr(admin, "LOGIN_DELAY", 0.01)
    results = await asyncio.gather(*[login(panel, "0", str(i), ip="4.4.4.4") for i in range(30)])
    codes = [r.status_code for r in results]
    assert codes.count(401) == admin.IP_MAX_FAILS and codes.count(429) == 30 - admin.IP_MAX_FAILS


async def test_owner_is_not_locked_out_and_can_unlock(panel, brain):
    from .conftest import OWNER

    for i in range(admin.GLOBAL_MAX_FAILS):
        await login(panel, "1", "2", ip=f"10.1.{i // 250}.{i % 250}")
    assert (await login(panel, ip="7.7.7.7")).status_code == 429
    # с самого сервера (SSH-туннель) общий замок не мешает
    r = await panel.post("/admin/api/login", json={"p1": P1, "p2": P2})
    assert r.status_code == 200
    # блокировка сохранилась в базе — переживёт перезапуск
    saved = await brain.db.kv_get(admin.LOCKS_KV)
    fresh = AdminAuth(brain.s)
    fresh.import_locks(__import__("json").loads(saved[0]))
    assert fresh.locked("7.7.7.7") is not None
    # владелец пишет Стелле в личку — замок снят
    await brain.handle_payload(upsert("стелла разблокируй панель", chat=f"{OWNER}@s.whatsapp.net",
                                      sender=f"{OWNER}@s.whatsapp.net"))
    await settle(brain)
    assert "снова открыт" in brain.evo.texts()[-1]
    assert (await login(panel, ip="7.7.7.7")).status_code == 200


async def test_stranger_cannot_unlock_panel(brain):
    brain.llm.queue = ["что?"]
    await brain.handle_payload(upsert("стелла разблокируй панель", chat=PETYA, sender=PETYA))
    await settle(brain)
    assert brain.evo.texts() == ["что?"]  # не команда для чужих — просто разговор


def test_group_jid_is_masked():
    from bot.util import mask_phone

    assert GROUP not in mask_phone(GROUP)
