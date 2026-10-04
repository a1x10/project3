"""Команды и кнопки бота. Всё, кроме /start для чужих, доступно только пользователям из ADMIN_IDS."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from agent import AIError
from config import Settings
from monitor import Busy, Monitor
from shell import run_shell
from system import server_stats
from telegram_ui import ActionCB, FixCB, clip, esc, format_apply_result, format_status, send_long

log = logging.getLogger(__name__)

HELP = """\
🤖 <b>Self-Healing Bot</b>

Слежу за приложением: если оно перестаёт отвечать — перезапускаю, а если не помогло — \
прошу ИИ найти причину по логам и коду и присылаю патч с кнопкой «Применить».

/status — состояние приложения и сервера
/logs [N] — последние N строк логов (по умолчанию 50)
/restart — перезапустить приложение
/debug — ИИ-анализ текущих логов
/pause, /resume — приостановить/возобновить мониторинг (например, на время деплоя)
/cmd &lt;команда&gt; — выполнить команду на сервере в папке проекта, например <code>/cmd git status</code>"""

DEFAULT_LOG_LINES = 50
MAX_LOG_LINES = 2000


def build_router(settings: Settings) -> Router:
    router = Router(name="admin")
    is_admin = F.from_user.id.in_(settings.admin_ids)
    router.message.filter(is_admin)
    router.callback_query.filter(is_admin)

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await message.answer(HELP)

    @router.message(Command("status"))
    async def cmd_status(message: Message, monitor: Monitor) -> None:
        stats = await asyncio.to_thread(server_stats)
        await message.answer(format_status(monitor, stats))

    @router.message(Command("logs"))
    async def cmd_logs(message: Message, command: CommandObject, bot: Bot, monitor: Monitor) -> None:
        try:
            lines = int(command.args) if command.args else DEFAULT_LOG_LINES
        except ValueError:
            await message.answer("Использование: <code>/logs 100</code>")
            return
        await show_logs(bot, message.chat.id, monitor, max(1, min(lines, MAX_LOG_LINES)))

    @router.message(Command("restart"))
    async def cmd_restart(message: Message, monitor: Monitor) -> None:
        await restart_app(message, monitor)

    @router.message(Command("debug"))
    async def cmd_debug(message: Message, monitor: Monitor) -> None:
        await run_debug(message, monitor)

    @router.message(Command("pause"))
    async def cmd_pause(message: Message, monitor: Monitor) -> None:
        monitor.pause()
        await message.answer("⏸ Мониторинг на паузе. Не забудь /resume после деплоя.")

    @router.message(Command("resume"))
    async def cmd_resume(message: Message, monitor: Monitor) -> None:
        monitor.resume()
        await message.answer("▶️ Мониторинг возобновлён.")

    @router.message(Command("cmd"))
    async def cmd_shell(message: Message, command: CommandObject, bot: Bot) -> None:
        if not settings.shell_enabled:
            await message.answer("Консоль выключена (SHELL_ENABLED=false).")
            return
        body = (command.args or "").strip()
        if not body:
            await message.answer("Напиши команду, например: <code>/cmd pm2 status</code>")
            return
        user = message.from_user.id if message.from_user else "?"
        log.warning("Пользователь %s выполняет команду: %s", user, body)
        await message.answer(f"🏃 Выполняю: <code>{esc(clip(body, 300))}</code>")
        result = await run_shell(body, cwd=settings.app_dir, timeout=settings.shell_timeout)
        if result.timed_out:
            status = f"⏱ прервано по таймауту {settings.shell_timeout:g} с"
        else:
            status = f"{'✅' if result.ok else '⚠️'} код выхода {result.returncode}"
        title = f"<code>$ {esc(clip(body, 200))}</code>\n{status} · {result.duration:.1f} с"
        await send_long(bot, message.chat.id, title, result.output or "(нет вывода)", "output.txt")

    @router.callback_query(FixCB.filter())
    async def on_fix(callback: CallbackQuery, callback_data: FixCB, bot: Bot, monitor: Monitor) -> None:
        diag = monitor.take_fix(callback_data.fix_id)
        if diag is None:
            await callback.answer("Фикс не найден: он устарел или уже обработан", show_alert=True)
            return
        chat_id = callback.message.chat.id if callback.message else callback.from_user.id
        await callback.answer("Применяю…" if callback_data.action == "apply" else "Ок, игнорирую")
        if isinstance(callback.message, Message):
            with contextlib.suppress(TelegramBadRequest):
                await callback.message.edit_reply_markup(reply_markup=None)  # чтобы не нажать дважды
        if callback_data.action != "apply":
            await bot.send_message(chat_id, "❌ Фикс отклонён. Посмотреть логи: /logs, повторить анализ: /debug")
            return
        await bot.send_message(chat_id, "⏳ Применяю фикс: ветка → патч → проверка → перезапуск…")
        result = await monitor.apply_fix(diag)
        await bot.send_message(chat_id, format_apply_result(result))

    @router.callback_query(ActionCB.filter())
    async def on_action(callback: CallbackQuery, callback_data: ActionCB, bot: Bot, monitor: Monitor) -> None:
        await callback.answer()
        if not isinstance(callback.message, Message):
            return
        if callback_data.action == "restart":
            await restart_app(callback.message, monitor)
        elif callback_data.action == "logs":
            await show_logs(bot, callback.message.chat.id, monitor, DEFAULT_LOG_LINES)
        elif callback_data.action == "debug":
            await run_debug(callback.message, monitor)

    return router


def build_guest_router() -> Router:
    """Для чужих — только подсказка с их Telegram ID (удобно при первой настройке ADMIN_IDS)."""
    router = Router(name="guest")

    @router.message(CommandStart())
    async def guest_start(message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        log.warning("Посторонний пользователь %s (@%s) написал боту", user.id, user.username)
        await message.answer(
            f"⛔ Нет доступа.\nТвой Telegram ID: <code>{user.id}</code>\n"
            "Если это твой бот — добавь этот ID в ADMIN_IDS в файле .env и перезапусти бота."
        )

    return router


async def show_logs(bot: Bot, chat_id: int, monitor: Monitor, lines: int) -> None:
    text = await monitor.app.recent_logs(lines)
    await send_long(bot, chat_id, f"📜 Последние {lines} строк логов", text, "logs.txt")


async def restart_app(message: Message, monitor: Monitor) -> None:
    if monitor.busy:
        await message.answer("⏳ Уже идёт перезапуск или применение фикса — подожди.")
        return
    await message.answer("🔄 Перезапускаю…")
    try:
        result = await monitor.manual_restart()
    except Busy:
        await message.answer("⏳ Уже идёт перезапуск или применение фикса — подожди.")
        return
    icon = "✅ Приложение работает" if result.ok else "❌ Не поднялось"
    await message.answer(f"{icon}: {esc(result.detail)}")


async def run_debug(message: Message, monitor: Monitor) -> None:
    if monitor.agent is None:
        await message.answer("ИИ выключен (AI_PROVIDER=none).")
        return
    if monitor.ai_busy:
        await message.answer("🧠 ИИ уже анализирует логи — результат скоро придёт.")
        return
    await message.answer("🧠 Отправляю логи и код ИИ на анализ…")
    health = monitor.last_health
    reason = health.detail if health and not health.ok else "ручной запуск /debug"
    try:
        diag = await monitor.diagnose(reason)
    except Busy:
        await message.answer("🧠 ИИ уже анализирует логи — результат скоро придёт.")
        return
    except AIError as e:
        await message.answer(f"⚠️ ИИ-анализ не удался: {esc(e)}")
        return
    await monitor.notifier.send_diagnosis(diag, chat_id=message.chat.id)
