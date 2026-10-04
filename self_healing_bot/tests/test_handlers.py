"""Хэндлеры гоняем через настоящий Dispatcher aiogram, подменяя только HTTP-сессию к Telegram."""

from __future__ import annotations

import asyncio
import itertools
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendDocument, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from conftest import FakeNotifier

from agent import Diagnosis, FilePatch
from git_patch import ApplyResult
from handlers import build_guest_router, build_router
from monitor import Monitor
from system import HealthResult
from telegram_ui import FixCB, TelegramNotifier

ADMIN, STRANGER = 1001, 666


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.requests = []
        self._ids = itertools.count(100)

    async def make_request(self, bot, method, timeout=None):
        self.requests.append(method)
        if isinstance(method, SendMessage | SendDocument):
            chat = Chat(id=method.chat_id, type="private")
            text = getattr(method, "text", None)
            return Message(message_id=next(self._ids), date=datetime.now(), chat=chat, text=text)
        return True

    async def close(self):
        pass

    async def stream_content(self, *args, **kwargs):
        yield b""

    def sent_texts(self):
        return [r.text for r in self.requests if isinstance(r, SendMessage)]


class FakeApp:
    def __init__(self):
        self.restarts = 0

    async def restart(self):
        self.restarts += 1
        return HealthResult(True, "HTTP 200 за 5 мс")

    async def recent_logs(self, lines):
        return "\n".join(f"log line {i}" for i in range(lines))

    def uptime(self):
        return 125.0

    def pid(self):
        return 4242

    def describe(self):
        return "npm start"

    def probe_description(self):
        return "http://127.0.0.1:3000/health"


class FakePatcher:
    def __init__(self):
        self.applied = []

    async def apply(self, diag):
        self.applied.append(diag.id)
        return ApplyResult(ok=True, steps=["🌿 Создана ветка ai-hotfix/x", "🚀 Приложение поднялось"], healthy=True)


def make_env(make_settings, tmp_path, **env):
    settings = make_settings(tmp_path, APP_RESTART_CMD="true", HEALTH_CMD="true", ADMIN_IDS=str(ADMIN), **env)
    session = FakeSession()
    bot = Bot("42:TEST-TOKEN", session=session)
    patcher = FakePatcher()
    monitor = Monitor(settings, FakeApp(), None, patcher, FakeNotifier())
    dp = Dispatcher()
    dp.include_router(build_router(settings))
    dp.include_router(build_guest_router())
    return dp, bot, session, monitor, patcher


def message_update(text, user_id=ADMIN, update_id=1):
    user = User(id=user_id, is_bot=False, first_name="Test")
    msg = Message(
        message_id=update_id, date=datetime.now(), chat=Chat(id=user_id, type="private"), from_user=user, text=text
    )
    return Update(update_id=update_id, message=msg)


def callback_update(data, user_id=ADMIN):
    user = User(id=user_id, is_bot=False, first_name="Test")
    msg = Message(message_id=7, date=datetime.now(), chat=Chat(id=user_id, type="private"), text="Анализ ИИ")
    query = CallbackQuery(id="cb", from_user=user, chat_instance="ci", data=data, message=msg)
    return Update(update_id=99, callback_query=query)


def feed(dp, bot, monitor, *updates):
    async def scenario():
        for update in updates:
            await dp.feed_update(bot, update, monitor=monitor)

    asyncio.run(scenario())


def test_status_for_admin(make_settings, tmp_path):
    dp, bot, session, monitor, _ = make_env(make_settings, tmp_path)
    feed(dp, bot, monitor, message_update("/status"))
    text = session.sent_texts()[-1]
    assert "Приложение:" in text and "PID 4242" in text and "CPU" in text


def test_strangers_get_only_their_id(make_settings, tmp_path):
    dp, bot, session, monitor, _ = make_env(make_settings, tmp_path)
    feed(dp, bot, monitor, message_update("/cmd rm -rf /", STRANGER), message_update("/status", STRANGER, 2))
    assert session.requests == []  # ни команд, ни ответа
    feed(dp, bot, monitor, message_update("/start", STRANGER, 3))
    assert "Нет доступа" in session.sent_texts()[-1] and str(STRANGER) in session.sent_texts()[-1]


def test_cmd_runs_shell_in_app_dir(make_settings, tmp_path):
    (tmp_path / "marker.txt").write_text("x")
    dp, bot, session, monitor, _ = make_env(make_settings, tmp_path)
    feed(dp, bot, monitor, message_update("/cmd echo '<b>hi</b>' && ls"))
    reply = session.sent_texts()[-1]
    assert "&lt;b&gt;hi&lt;/b&gt;" in reply  # вывод экранирован для HTML-режима
    assert "marker.txt" in reply and "код выхода 0" in reply


def test_cmd_can_be_disabled(make_settings, tmp_path):
    dp, bot, session, monitor, _ = make_env(make_settings, tmp_path, SHELL_ENABLED="false")
    feed(dp, bot, monitor, message_update("/cmd echo hi"))
    assert "Консоль выключена" in session.sent_texts()[-1]


def test_long_logs_are_sent_as_file(make_settings, tmp_path):
    dp, bot, session, monitor, _ = make_env(make_settings, tmp_path)
    feed(dp, bot, monitor, message_update("/logs 500"))
    docs = [r for r in session.requests if isinstance(r, SendDocument)]
    assert len(docs) == 1 and docs[0].document.filename == "logs.txt"


def test_restart_command(make_settings, tmp_path):
    dp, bot, session, monitor, _ = make_env(make_settings, tmp_path)
    feed(dp, bot, monitor, message_update("/restart"))
    assert monitor.app.restarts == 1 and "Приложение работает" in session.sent_texts()[-1]


def test_apply_fix_button(make_settings, tmp_path):
    dp, bot, session, monitor, patcher = make_env(make_settings, tmp_path)
    diag = Diagnosis("abcd1234", "Опечатка", "NameError", "high", "", [], [FilePatch("a.py", None, "x", "y")], [], "m")
    monitor._remember_fix(diag)

    feed(dp, bot, monitor, callback_update(FixCB(action="apply", fix_id="abcd1234").pack()))
    assert patcher.applied == ["abcd1234"]
    assert "Фикс применён" in session.sent_texts()[-1]

    session.requests.clear()  # повторное нажатие на ту же кнопку ничего не применяет
    feed(dp, bot, monitor, callback_update(FixCB(action="apply", fix_id="abcd1234").pack()))
    answer = next(r for r in session.requests if isinstance(r, AnswerCallbackQuery))
    assert answer.show_alert and "не найден" in answer.text
    assert patcher.applied == ["abcd1234"]


def test_buttons_are_admin_only(make_settings, tmp_path):
    dp, bot, session, monitor, patcher = make_env(make_settings, tmp_path)
    monitor._remember_fix(Diagnosis("f1", "s", "r", "high", "", [], [FilePatch("a.py", None, "x", "y")], [], "m"))
    feed(dp, bot, monitor, callback_update(FixCB(action="apply", fix_id="f1").pack(), user_id=STRANGER))
    assert patcher.applied == [] and session.requests == []


def test_diagnosis_message_with_buttons(make_settings, tmp_path):
    dp, bot, session, monitor, _ = make_env(make_settings, tmp_path)
    diag = Diagnosis(
        "f2", "Опечатка <script>", "NameError", "high", "", ["npm install"],
        [FilePatch("server.py", None, "a = load_confg()\n", "a = load_config()\n")], [], "claude-opus-5-5",
    )
    asyncio.run(TelegramNotifier(bot, ADMIN).send_diagnosis(diag))
    sent = session.requests[-1]
    assert "Опечатка &lt;script&gt;" in sent.text and "<code>npm install</code>" in sent.text
    assert "+a = load_config()" in sent.text
    buttons = [b.callback_data for b in sent.reply_markup.inline_keyboard[0]]
    assert buttons == ["fix:apply:f2", "fix:ignore:f2"]


def test_alert_falls_back_to_plain_text_when_html_is_rejected(make_settings, tmp_path):
    from aiogram.exceptions import TelegramBadRequest

    class PickySession(FakeSession):
        async def make_request(self, bot, method, timeout=None):
            if isinstance(method, SendMessage) and method.parse_mode is not None and "<b>" in method.text:
                self.requests.append(method)
                raise TelegramBadRequest(method=method, message="can't parse entities")
            return await super().make_request(bot, method, timeout)

    session = PickySession()
    bot = Bot("42:TEST-TOKEN", session=session)
    asyncio.run(TelegramNotifier(bot, ADMIN).send("🚨 <b>Приложение недоступно</b> &amp; всё", actions=("logs",)))
    last = session.requests[-1]
    assert last.parse_mode is None and last.text == "🚨 Приложение недоступно & всё"
    assert last.reply_markup is not None
