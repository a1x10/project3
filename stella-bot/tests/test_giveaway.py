"""Розыгрыш: страница участника, вход в админку по одноразовой ссылке от Стеллы, рассылка в личку Telegram."""

import re

import httpx
import pytest

from bot.giveaway import DEFAULT_BUTTON, STOP_DATA, csv_safe, normalize_contact
from bot.main import create_app
from bot.telegram import TelegramError

from .conftest import GROUP, OWNER, settle, upsert

OWNER_JID = f"{OWNER}@s.whatsapp.net"
TUNNEL = "https://quiet-river.trycloudflare.com"


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


class FakeTg:
    """Telegram Bot API: запоминает вызовы; чатам из blocked — «бот заблокирован»; flood — сколько раз подряд
    ответить «слишком часто»."""

    def __init__(self, blocked=(), flood=0):
        self.calls = []
        self.blocked = set(blocked)
        self.flood = flood
        self.n = 100

    async def call(self, method, *, data=None, files=None, timeout=60):
        self.calls.append((method, data))
        if method == "sendMessage":
            if data["chat_id"] in self.blocked:
                raise TelegramError("Telegram sendMessage: Forbidden: bot was blocked by the user")
            if self.flood:
                self.flood -= 1
                raise TelegramError("Telegram sendMessage: слишком часто, подождать 35 с", retry_after=35)
            self.n += 1
            return {"message_id": self.n}
        return True

    def sent_to(self):
        return [d["chat_id"] for m, d in self.calls if m == "sendMessage"]


@pytest.fixture
async def web(brain):
    brain.giveaway.clock = Clock()
    app = create_app(brain.s, brain=brain)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://bot") as client:
            yield client


async def register(web, brain, contact="@vasya_pupkin", name="Вася", answer=None):
    cap = (await web.get("/giveaway/api/captcha")).json()
    brain.giveaway.clock.t += 5  # человек думает пару секунд
    right = brain.giveaway.captchas[cap["id"]][0]
    return await web.post("/giveaway/api/register", json={
        "first_name": name, "contact": contact, "consent": True, "captcha_id": cap["id"],
        "captcha_answer": right if answer is None else answer})


async def owner_link(brain) -> str:
    brain.tunnel_url = TUNNEL
    await brain.handle_payload(upsert("/розыгрыш", chat=OWNER_JID, sender=OWNER_JID, name="Хозяин"))
    await settle(brain)
    text = "\n".join(brain.evo.texts())
    m = re.search(r"#t=([\w-]+)", text)
    assert m, text
    return m.group(1)


async def login(web, brain) -> None:
    token = await owner_link(brain)
    r = await web.post("/giveaway/api/admin/enter", json={"token": token})
    assert r.status_code == 200, r.text


# ---------- участник ----------
def test_contact_and_csv_rules():
    assert normalize_contact("8 (701) 123-45-67") == ("+77011234567", "phone:77011234567", "phone")
    assert normalize_contact("https://t.me/Vasya_P") == ("@Vasya_P", "tg:vasya_p", "telegram")
    assert normalize_contact("@ab") is None and normalize_contact("привет") is None
    # тот же номер другими цифрами или через 00 — тот же ключ (одна заявка на контакт)
    assert normalize_contact("+７ ７０１ １２３ ４５ ６７") is None
    assert normalize_contact("007 701 123 45 67")[1] == "phone:77011234567"
    assert csv_safe("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")" and csv_safe("Вася") == "Вася"


async def test_participant_registers_once_with_captcha(web, brain):
    page = await web.get("/giveaway/")
    assert page.status_code == 200 and "Безлимитный" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert (await web.get("/giveaway", follow_redirects=False)).headers["location"] == "/giveaway/"

    r = await register(web, brain, answer="неверно")
    assert r.status_code == 400 and "Неверный" in r.json()["error"]
    r = await register(web, brain)
    assert r.status_code == 200 and r.json()["number"] == 1
    again = await register(web, brain, contact="https://t.me/VASYA_PUPKIN")
    assert again.status_code == 409  # один контакт — одна заявка
    mail = await web.post("/giveaway/api/email", json={"token": r.json()["token"], "email": "v@mail.kz"})
    assert mail.status_code == 200
    state = (await web.get("/giveaway/api/state")).json()
    assert state["count"] == 1 and state["round"] == 1 and not state["closed"]


async def test_too_fast_answer_is_a_robot(web, brain):
    cap = (await web.get("/giveaway/api/captcha")).json()
    right = brain.giveaway.captchas[cap["id"]][0]
    r = await web.post("/giveaway/api/register", json={
        "first_name": "Бот", "contact": "+77010000000", "consent": True, "captcha_id": cap["id"],
        "captcha_answer": right})
    assert r.status_code == 400 and "быстро" in r.json()["error"]


async def test_page_is_reachable_through_the_tunnel(web):
    tunnel = {"cf-connecting-ip": "5.6.7.8"}
    assert (await web.get("/giveaway/", headers=tunnel)).status_code == 200
    assert (await web.get("/health", headers=tunnel)).status_code == 404  # остальное бота — по-прежнему нет


async def test_disabled_giveaway_is_not_found(web, brain):
    brain.s.giveaway_enabled = False
    assert (await web.get("/giveaway/")).status_code == 404


# ---------- админка ----------
async def test_admin_only_by_one_time_link_from_stella(web, brain):
    assert (await web.get("/giveaway/api/admin/entries")).status_code == 401
    admin_page = await web.get("/giveaway/admin")
    assert "/розыгрыш" in admin_page.text and "Выбрать победителя" not in admin_page.text

    token = await owner_link(brain)
    assert f"{TUNNEL}/giveaway/" in "\n".join(brain.evo.texts())
    assert (await web.post("/giveaway/api/admin/enter", json={"token": "x" * 32})).status_code == 401
    r = await web.post("/giveaway/api/admin/enter", json={"token": token})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "path=/giveaway" in cookie and "samesite=lax" in cookie
    assert (await web.get("/giveaway/api/admin/entries")).status_code == 200
    assert "Выбрать победителя" in (await web.get("/giveaway/admin")).text

    web.cookies.clear()
    assert (await web.post("/giveaway/api/admin/enter", json={"token": token})).status_code == 401  # одноразовая


async def test_logout_closes_every_session_and_bad_cookies_are_just_401(web, brain):
    await login(web, brain)
    stolen = web.cookies.get("gw_admin")
    assert (await web.post("/giveaway/api/admin/logout", json={})).status_code == 200
    web.cookies.set("gw_admin", stolen, domain="bot", path="/giveaway")
    assert (await web.get("/giveaway/api/admin/entries")).status_code == 401  # «Выйти» — везде
    for bad in ("1.é", "9999999999.zz", "1.1." + "0" * 64):
        web.cookies.set("gw_admin", bad, domain="bot", path="/giveaway")
        assert (await web.get("/giveaway/api/admin/entries")).status_code == 401


async def test_link_expires(web, brain):
    token = await owner_link(brain)
    brain.giveaway.clock.t += 16 * 60
    assert (await web.post("/giveaway/api/admin/enter", json={"token": token})).status_code == 401


async def test_not_owner_and_groups_get_no_link(web, brain):
    from .conftest import VASYA

    brain.tunnel_url = TUNNEL
    await brain.handle_payload(upsert("/розыгрыш", chat=VASYA, sender=VASYA))
    await settle(brain)
    hint = " ".join(brain.evo.texts())
    assert "команда владельца" in hint and "OWNER_PHONE=" in hint  # подсказка, кого вписать владельцем
    brain.llm.queue = ["что?"]
    await brain.handle_payload(upsert("стелла розыгрыш", chat=GROUP, sender=OWNER_JID, name="Хозяин"))
    await settle(brain)
    assert not any("#t=" in t for t in brain.evo.texts())


async def test_admin_actions_need_json(web, brain):
    await login(web, brain)
    form = {"content-type": "application/x-www-form-urlencoded"}
    # чужой сайт формой ничего не поменяет: и там, где тела нет вовсе, и там, где ждём JSON
    assert (await web.post("/giveaway/api/admin/new_round", content=b"x=1", headers=form)).status_code == 415
    assert (await web.post("/giveaway/api/admin/entries/1/winner", content=b"", headers=form)).status_code == 415
    assert (await web.post("/giveaway/api/admin/settings", content=b"closed=true", headers=form)).status_code in (
        415, 422)
    assert (await web.get("/giveaway/api/state")).json()["round"] == 1


async def test_draw_export_and_new_round(web, brain):
    await login(web, brain)
    assert (await register(web, brain, contact="+77011112233", name="=HYPERLINK(1)")).status_code == 200
    assert (await register(web, brain, contact="@petya_petrov", name="Петя")).status_code == 200
    win = (await web.post("/giveaway/api/admin/draw", json={})).json()
    assert win["pool"] == 2 and win["winner"]["is_winner"] == 1 and "token" not in win["winner"]
    csv = (await web.get("/giveaway/api/admin/export.csv")).text
    assert "'=HYPERLINK(1)" in csv

    assert (await web.post("/giveaway/api/admin/settings", json={"closed": True})).status_code == 200
    assert (await register(web, brain, contact="@late_comer")).status_code == 400

    r = await web.post("/giveaway/api/admin/new_round", json={})
    assert r.json()["round"] == 2
    state = (await web.get("/giveaway/api/state")).json()
    assert state["count"] == 0 and not state["closed"]
    assert (await register(web, brain, contact="+77011112233")).status_code == 200  # в новом круге — снова можно


# ---------- рассылка ----------
async def tg_dm(brain, user_id: int) -> dict:
    return await brain.db.get_or_create_chat(brain.s.evolution_instance, f"{user_id}@tg.chat", False)


async def test_broadcast_goes_once_to_telegram_dms_with_buttons(web, brain):
    brain.evo.tg = tg = FakeTg(blocked={333})
    for uid in (111, 222, 333):
        await tg_dm(brain, uid)
    await brain.db.get_or_create_chat(brain.s.evolution_instance, "-100500@tg.chat", True)  # группа — не трогаем
    await login(web, brain)

    info = (await web.get("/giveaway/api/admin/broadcast")).json()
    assert info["recipients"] == 3 and info["url"] == f"{TUNNEL}/giveaway/"
    assert info["default_text"].startswith("Добрый вечер")
    r = await web.post("/giveaway/api/admin/broadcast", json={"text": "Розыгрыш! Жмите 👇", "button": DEFAULT_BUTTON})
    assert r.status_code == 200, r.text
    await settle(brain)

    assert sorted(tg.sent_to()) == [111, 222, 333]
    first = next(d for m, d in tg.calls if m == "sendMessage")
    rows = first["reply_markup"]["inline_keyboard"]
    assert rows[0] == [{"text": DEFAULT_BUTTON, "url": f"{TUNNEL}/giveaway/"}]
    assert rows[1][0]["callback_data"] == STOP_DATA
    progress = (await web.get("/giveaway/api/admin/broadcast")).json()["progress"]
    assert progress["state"] == "done" and progress["sent"] == 2 and progress["blocked"] == 1
    state = (await web.get("/giveaway/api/state")).json()
    assert state["draw_at"]  # таймер на 30 минут запустился вместе с рассылкой

    chat = await brain.db.get_chat_by_jid(brain.s.evolution_instance, "111@tg.chat")
    history = await brain.db.recent_messages(chat["id"], 5)
    # Стелла знает, что писала, — и даст настоящую ссылку, если спросят
    assert any("Розыгрыш! Жмите" in (m["text"] or "") and f"{TUNNEL}/giveaway/" in m["text"] for m in history)

    # второй раз — никому: получившие и заблокировавшие бота отмечены
    tg.calls.clear()
    r = await web.post("/giveaway/api/admin/broadcast", json={"text": "ещё раз", "button": DEFAULT_BUTTON})
    assert r.status_code == 400 and tg.sent_to() == []
    # новенький написал Стелле — ему одному; таймер и регистрацию повторная рассылка не трогает
    draw_at = state["draw_at"]
    await web.post("/giveaway/api/admin/settings", json={"closed": True})
    await tg_dm(brain, 444)
    r = await web.post("/giveaway/api/admin/broadcast", json={"text": "ещё раз", "button": DEFAULT_BUTTON})
    await settle(brain)
    assert tg.sent_to() == [444]
    after = (await web.get("/giveaway/api/state")).json()
    assert after["draw_at"] == draw_at and after["closed"]


async def test_double_click_sends_once(web, brain):
    import asyncio

    brain.evo.tg = tg = FakeTg()
    for uid in (111, 222, 333):
        await tg_dm(brain, uid)
    await login(web, brain)
    body = {"text": "привет", "button": DEFAULT_BUTTON}
    rs = await asyncio.gather(*(web.post("/giveaway/api/admin/broadcast", json=body) for _ in range(2)))
    await settle(brain)
    assert sorted(r.status_code for r in rs) == [200, 409]
    assert sorted(tg.sent_to()) == [111, 222, 333]


async def test_flood_wait_is_respected_not_skipped(web, brain, monkeypatch):
    import asyncio

    import bot.giveaway as gmod

    slept = []
    real_sleep = asyncio.sleep

    async def fast_sleep(s):
        slept.append(s)
        await real_sleep(0)

    monkeypatch.setattr(gmod.asyncio, "sleep", fast_sleep)
    brain.evo.tg = FakeTg(flood=1)
    for uid in (111, 222):
        await tg_dm(brain, uid)
    await login(web, brain)
    await web.post("/giveaway/api/admin/broadcast", json={"text": "привет", "button": DEFAULT_BUTTON})
    await settle(brain)
    progress = (await web.get("/giveaway/api/admin/broadcast")).json()["progress"]
    assert progress["sent"] == 2 and progress["failed"] == 0 and 36 in slept  # подождала, сколько просил Telegram


async def test_link_is_rechecked_before_sending(web, brain):
    brain.evo.tg = tg = FakeTg()
    await tg_dm(brain, 111)
    await login(web, brain)
    brain.s.tunnel_metrics_url = "http://tunnel:2000"

    async def tunnel_restarted():  # cloudflared перезапустился — у туннеля новый адрес
        brain.tunnel_url = "https://new-host.trycloudflare.com"
        return brain.tunnel_url

    brain.check_tunnel = tunnel_restarted
    await web.post("/giveaway/api/admin/broadcast", json={"text": "привет", "button": DEFAULT_BUTTON})
    await settle(brain)
    url = next(d for m, d in tg.calls if m == "sendMessage")["reply_markup"]["inline_keyboard"][0][0]["url"]
    assert url == "https://new-host.trycloudflare.com/giveaway/"

    async def tunnel_down():
        raise OSError("нет туннеля")

    brain.check_tunnel = tunnel_down
    await tg_dm(brain, 222)
    r = await web.post("/giveaway/api/admin/broadcast", json={"text": "привет", "button": DEFAULT_BUTTON})
    assert r.status_code == 400 and "туннель" in r.json()["error"]  # мёртвую кнопку не рассылаем


async def test_stop_button_unsubscribes_and_removes_itself(web, brain):
    brain.evo.tg = tg = FakeTg()
    for uid in (111, 222):
        await tg_dm(brain, uid)
    markup = brain.giveaway._markup(DEFAULT_BUTTON, f"{TUNNEL}/giveaway/")
    await brain.giveaway.on_callback(tg, {"id": "cb1", "data": STOP_DATA, "message": {
        "message_id": 7, "chat": {"id": 222, "type": "private"}, "reply_markup": markup}})
    edit = next(d for m, d in tg.calls if m == "editMessageReplyMarkup")
    assert edit["reply_markup"]["inline_keyboard"] == [markup["inline_keyboard"][0]]
    answer = next(d for m, d in tg.calls if m == "answerCallbackQuery")
    assert answer["callback_query_id"] == "cb1" and "не пришлю" in answer["text"]

    await login(web, brain)
    tg.calls.clear()
    info = (await web.get("/giveaway/api/admin/broadcast")).json()
    assert info["recipients"] == 1 and info["optout"] == 1
    await web.post("/giveaway/api/admin/broadcast", json={"text": "привет", "button": DEFAULT_BUTTON})
    await settle(brain)
    assert tg.sent_to() == [111]


async def test_test_message_goes_only_to_the_owner(web, brain):
    brain.evo.tg = tg = FakeTg()
    brain.s.telegram_owner_id = "999"
    await tg_dm(brain, 999)
    await tg_dm(brain, 111)
    await login(web, brain)
    r = await web.post("/giveaway/api/admin/broadcast", json={"text": "проба", "button": "Го", "test": True})
    assert r.status_code == 200 and tg.sent_to() == [999]
    info = (await web.get("/giveaway/api/admin/broadcast")).json()
    assert info["recipients"] == 2  # пробное не считается — настоящая рассылка дойдёт и до владельца


async def test_broadcast_needs_https_link_and_telegram(web, brain):
    await login(web, brain)
    r = await web.post("/giveaway/api/admin/broadcast", json={"text": "x", "button": "Го"})
    assert r.status_code == 400 and "Telegram" in r.json()["error"]
    brain.evo.tg = FakeTg()
    brain.tunnel_url = None
    r = await web.post("/giveaway/api/admin/broadcast", json={"text": "x", "button": "Го"})
    assert r.status_code == 400 and "туннель" in r.json()["error"]
