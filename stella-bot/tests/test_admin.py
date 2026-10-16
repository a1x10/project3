"""Панель управления: вход по двум паролям, защита от подбора, сессии, действия."""

import httpx
import pytest

from bot import admin
from bot.admin import AdminAuth
from bot.main import create_app

from .conftest import GROUP, PETYA, settle, upsert

ORIGIN = "https://a1x10.github.io"


@pytest.fixture(autouse=True)
def fast_login(monkeypatch):
    monkeypatch.setattr(admin, "LOGIN_DELAY", 0)


@pytest.fixture
async def panel(brain):
    brain.s.panel_password_1, brain.s.panel_password_2 = "1010", "2013"
    brain.s.panel_origins = [ORIGIN]
    brain.admin = AdminAuth(brain.s)
    app = create_app(brain.s, brain=brain)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://bot") as client:
            yield client


async def login(client, p1="1010", p2="2013", ip="1.2.3.4"):
    return await client.post("/admin/api/login", json={"p1": p1, "p2": p2}, headers={"cf-connecting-ip": ip})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


async def test_panel_disabled_without_passwords(brain):
    brain.s.panel_password_1, brain.s.panel_password_2 = "1010", ""
    brain.admin = AdminAuth(brain.s)
    app = create_app(brain.s, brain=brain)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bot") as client:
            r = await login(client)
            assert r.status_code == 503 and r.json()["error"] == "disabled"
            assert (await client.get("/admin/api/status")).status_code == 503


async def test_two_passwords_and_session(panel, brain):
    assert (await panel.get("/admin/api/status")).status_code == 401
    r = await login(panel, "1010", "0000")
    assert r.status_code == 401 and r.json() == {"error": "wrong"}  # не говорим, какой пароль неверный
    r = await login(panel, "2013", "1010")
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


async def test_health_hides_details_through_tunnel(panel):
    r = await panel.get("/health", headers={"cf-connecting-ip": "5.5.5.5"})
    assert r.json() == {"ok": True}
    assert "spend_today_usd" in (await panel.get("/health")).json()


def test_group_jid_is_masked():
    from bot.util import mask_phone

    assert GROUP not in mask_phone(GROUP)
