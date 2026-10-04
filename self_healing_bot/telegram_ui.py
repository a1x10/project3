"""Внешний вид сообщений в Telegram: HTML-разметка, кнопки, длинные тексты, отправка алертов."""

from __future__ import annotations

import html
import logging
import re
import time
from collections.abc import Sequence
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
    from agent import Diagnosis
    from git_patch import ApplyResult
    from monitor import Monitor

log = logging.getLogger(__name__)

SAFE_LEN = 3500  # лимит Telegram — 4096 символов; оставляем запас под заголовки и теги

ACTION_LABELS = {"restart": "🔄 Перезапустить", "logs": "📜 Логи", "debug": "🧠 ИИ-анализ"}
CONFIDENCE = {"low": "низкая", "medium": "средняя", "high": "высокая"}
STATE_LABELS = {
    "unknown": "❔ ещё не проверялось",
    "up": "✅ работает",
    "recovering": "🔄 восстанавливается",
    "failed": "❌ недоступно, нужна помощь",
}


class FixCB(CallbackData, prefix="fix"):
    action: str  # apply | ignore
    fix_id: str


class ActionCB(CallbackData, prefix="act"):
    action: str  # restart | logs | debug


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "…" + text[-(limit - 1):]


def fmt_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    if minutes:
        return f"{minutes} мин {secs} с"
    return f"{secs} с"


def actions_keyboard(actions: Sequence[str]) -> InlineKeyboardMarkup | None:
    if not actions:
        return None
    row = [InlineKeyboardButton(text=ACTION_LABELS[a], callback_data=ActionCB(action=a).pack()) for a in actions]
    return InlineKeyboardMarkup(inline_keyboard=[row])


def fix_keyboard(fix_id: str) -> InlineKeyboardMarkup:
    apply = FixCB(action="apply", fix_id=fix_id).pack()
    ignore = FixCB(action="ignore", fix_id=fix_id).pack()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Применить фикс", callback_data=apply),
                InlineKeyboardButton(text="❌ Игнорировать", callback_data=ignore),
            ]
        ]
    )


def format_diagnosis(diag: Diagnosis) -> tuple[str, str | None]:
    """Текст сообщения и diff, который придётся отправить файлом (если он не влез в сообщение)."""
    lines = [
        f"🤖 <b>Анализ ИИ</b> · <i>{esc(diag.model)}</i>",
        "",
        f"<b>Что случилось:</b> {esc(clip(diag.summary, 400))}",
    ]
    if diag.root_cause:
        lines.append(f"<b>Причина:</b> {esc(clip(diag.root_cause, 900))}")
    lines.append(f"<b>Уверенность:</b> {CONFIDENCE.get(diag.confidence, esc(diag.confidence))}")
    if diag.notes:
        lines.append(f"<b>Заметки:</b> {esc(clip(diag.notes, 400))}")
    if diag.commands:
        lines += ["", "<b>Команды, которые могут помочь</b> (сами не выполняются — запусти через /cmd):"]
        lines += [f"<code>{esc(clip(c, 200))}</code>" for c in diag.commands[:5]]
    if diag.rejected:
        lines += ["", "⚠️ <b>Патч не прошёл проверку бота:</b>"]
        lines += [f"• {esc(clip(r, 200))}" for r in diag.rejected[:3]]

    diff_file = None
    if diag.patches:
        files = ", ".join(f"{p.rel_path} (+{p.stats()[0]} −{p.stats()[1]})" for p in diag.patches)
        lines += ["", f"<b>Патч:</b> {esc(files)}"]
        diff = diag.diff
        if len("\n".join(lines)) + len(diff) < SAFE_LEN:
            lines.append(f'<pre><code class="language-diff">{esc(diff)}</code></pre>')
        else:
            lines.append("<i>diff большой — он во вложенном файле выше</i>")
            diff_file = diff
    if diag.can_apply:
        lines += [
            "",
            "При нажатии «Применить» бот создаст git-ветку, проверит синтаксис, перезапустит приложение "
            "и сам откатит изменения, если фикс не поможет. <b>Сначала прочитай diff.</b>",
        ]
    elif not diag.patches and not diag.rejected:
        lines += ["", "Правок в коде ИИ не предлагает."]
    return "\n".join(lines), diff_file


def format_apply_result(result: ApplyResult) -> str:
    title = "✅ <b>Фикс применён, приложение работает</b>" if result.ok else "❌ <b>Фикс не применён</b>"
    body = clip("\n".join(clip(step, 600) for step in result.steps), SAFE_LEN - 200)
    return f"{title}\n\n{esc(body)}"


def format_status(monitor: Monitor, stats: dict[str, str]) -> str:
    now = time.time()
    app = monitor.app
    lines = [f"<b>Приложение:</b> {STATE_LABELS.get(monitor.state, monitor.state)}"]
    if monitor.paused:
        lines.append("⏸ Мониторинг на паузе (/resume — продолжить)")
    if monitor.busy:
        lines.append("⏳ Идёт перезапуск или применение фикса")
    if monitor.ai_busy:
        lines.append("🧠 Идёт ИИ-анализ")
    if monitor.last_health and monitor.last_check_at:
        icon = "🟢" if monitor.last_health.ok else "🔴"
        ago = fmt_duration(now - monitor.last_check_at)
        lines.append(f"{icon} Последняя проверка ({ago} назад): {esc(monitor.last_health.detail)}")
    if monitor.down_since:
        lines.append(f"Недоступно уже {fmt_duration(now - monitor.down_since)}")
    uptime = app.uptime()
    if uptime is not None:
        pid = app.pid()
        lines.append(f"Аптайм приложения: {fmt_duration(uptime)}" + (f" (PID {pid})" if pid else ""))
    lines += [
        f"Команда: <code>{esc(app.describe())}</code>",
        f"Проверка: <code>{esc(app.probe_description())}</code>",
        "",
        "<b>Сервер</b>",
    ]
    lines += [f"{esc(k)}: {esc(v)}" for k, v in stats.items()]
    lines.append(f"Бот работает {fmt_duration(now - monitor.started_at)}")
    return "\n".join(lines)


async def send_long(bot: Bot, chat_id: int, title: str, body: str, filename: str) -> None:
    """Короткий текст — сообщением в <pre>, длинный — файлом (Telegram не принимает больше 4096 символов)."""
    body = body.rstrip() or "(пусто)"
    if len(title) + len(body) < SAFE_LEN:
        await bot.send_message(chat_id, f"{title}\n<pre>{esc(body)}</pre>")
        return
    document = BufferedInputFile(body.encode("utf-8"), filename=filename)
    await bot.send_document(chat_id, document, caption=title)
    await bot.send_message(chat_id, f"Последние строки:\n<pre>{esc(tail(body, 1500))}</pre>")


class TelegramNotifier:
    """Отправляет алерты в ALERT_CHAT_ID. Никогда не бросает исключений: мониторинг важнее."""

    def __init__(self, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id

    async def send(self, text: str, actions: Sequence[str] = (), chat_id: int | None = None) -> None:
        target, markup = chat_id or self.chat_id, actions_keyboard(actions)
        try:
            await self.bot.send_message(target, text, reply_markup=markup)
        except TelegramBadRequest as e:
            log.warning("Telegram не принял сообщение (%s) — отправляю простым текстом", e)
            try:
                await self.bot.send_message(target, strip_html(text), reply_markup=markup, parse_mode=None)
            except Exception:
                log.exception("Не удалось отправить сообщение в Telegram")
        except Exception:
            log.exception("Не удалось отправить сообщение в Telegram")

    async def send_diagnosis(self, diag: Diagnosis, chat_id: int | None = None) -> None:
        target = chat_id or self.chat_id
        text, diff_file = format_diagnosis(diag)
        markup = fix_keyboard(diag.id) if diag.can_apply else actions_keyboard(("logs", "restart"))
        try:
            if diff_file:
                document = BufferedInputFile(diff_file.encode("utf-8"), filename=f"fix-{diag.id}.diff")
                await self.bot.send_document(target, document, caption="Предлагаемый патч")
            await self.bot.send_message(target, text, reply_markup=markup)
        except Exception:
            log.exception("Не удалось отправить результат ИИ-анализа в Telegram")
