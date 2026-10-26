"""Animated loaders, typewriter text and the boot sequence."""
import asyncio
import html
import math
import random
import time

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
BLOCKS = "▁▂▃▄▅▆▇█"

EFFECT_FIRE = "5104841245755180586"
EFFECT_PARTY = "5046509860389126442"
EFFECT_HEART = "5159385139981059251"
EFFECT_LIKE = "5107584321108051014"


def _wave(tick, width=18, speed=0.9, freq=0.55):
    return "".join(
        BLOCKS[int((math.sin(i * freq + tick * speed) * 0.5 + 0.5) * (len(BLOCKS) - 1))] for i in range(width)
    )


def _eq(tick, width=14):
    rnd = random.Random(tick)
    bars = "".join(BLOCKS[rnd.randint(1, 7)] for _ in range(width))
    notes = "♪♫♬♩"
    return f"{notes[tick % 4]} {bars} {notes[(tick + 2) % 4]}"


def _film(tick, width=9):
    cells = ["▫"] * width
    cells[tick % width] = "▶"
    return "🎞 " + "".join(cells) + " 🎬"


def _pixels(tick, progress, width=12, rows=3):
    lines = []
    filled = int(progress * width * rows)
    shades = "░▒▓█"
    for r in range(rows):
        row = ""
        for c in range(width):
            idx = r * width + c
            if idx < filled:
                row += "█"
            elif idx == filled:
                row += shades[tick % 4]
            else:
                row += "░"
        lines.append(row)
    return "\n".join(lines)


def _neural(tick, width=11):
    pos = tick % (2 * width - 2)
    pos = pos if pos < width else 2 * width - 2 - pos
    return "◦ " + "".join("●" if i == pos else ("•" if abs(i - pos) == 1 else "·") for i in range(width)) + " ◦"


def _burst(tick):
    seq = ["·", "∗", "✧", "✦", "✺", "✹", "❋", "✹", "✺", "✦", "✧", "∗"]
    return "  ".join(seq[(tick + k * 2) % len(seq)] for k in range(7))


def _scan(tick, width=16):
    beam = "░▒▓█▓▒░"
    pos = tick % (width + len(beam)) - len(beam)
    row = ["·"] * width
    for i, ch in enumerate(beam):
        if 0 <= pos + i < width:
            row[pos + i] = ch
    return "".join(row)


def _dna(tick, width=14):
    top = "".join("●" if (i + tick) % 4 == 0 else "─" for i in range(width))
    bot = "".join("●" if (i + tick + 2) % 4 == 0 else "─" for i in range(width))
    return f"{top}\n{bot}"


THEMES = {
    "tts": dict(icon="🗣", art=lambda t, p: _wave(t), action="record_voice",
                stages=["Анализирую текст", "Расставляю интонации", "Синтезирую голос", "Шлифую звучание"]),
    "music": dict(icon="🎵", art=lambda t, p: _eq(t), action="upload_voice",
                  stages=["Читаю ваш замысел", "Сочиняю мелодию", "Пишу аранжировку", "Записываю вокал", "Свожу и мастерю трек"]),
    "video": dict(icon="🎬", art=lambda t, p: _film(t), action="upload_video",
                  stages=["Раскадровка сцены", "Ставлю свет и камеру", "Рендерю кадры", "Добавляю звук", "Финальный монтаж"]),
    "image": dict(icon="🎨", art=lambda t, p: _pixels(t, p), action="upload_photo",
                  stages=["Изучаю промпт", "Набрасываю композицию", "Прорисовываю детали", "Цветокоррекция"]),
    "sfx": dict(icon="💥", art=lambda t, p: _burst(t), action="record_voice",
                stages=["Представляю звук", "Синтезирую волну", "Добавляю объём"]),
    "stt": dict(icon="📝", art=lambda t, p: _scan(t), action="typing",
                stages=["Слушаю запись", "Распознаю речь", "Расставляю пунктуацию"]),
    "sts": dict(icon="🎙", art=lambda t, p: _wave(t, speed=1.4, freq=0.9), action="record_voice",
                stages=["Слушаю оригинал", "Переношу эмоции", "Меняю тембр"]),
    "isolate": dict(icon="🎧", art=lambda t, p: _scan(t), action="record_voice",
                    stages=["Анализирую спектр", "Отделяю голос от шума", "Очищаю дорожку"]),
    "voice": dict(icon="🧬", art=lambda t, p: _dna(t), action="record_voice",
                  stages=["Считываю описание", "Собираю тембр", "Генерирую образцы"]),
    "dub": dict(icon="🌍", art=lambda t, p: _wave(t, width=16, speed=0.6), action="upload_video",
                stages=["Загружаю медиа", "Расшифровываю речь", "Перевожу", "Озвучиваю на новом языке", "Свожу дорожки"]),
    "agent": dict(icon="🤖", art=lambda t, p: _neural(t), action="typing",
                  stages=["Подключаю нейросеть", "Настраиваю личность", "Оживляю агента"]),
    "generic": dict(icon="✨", art=lambda t, p: _neural(t), action="typing", stages=["Обрабатываю"]),
}


def bar(p: float, width: int = 12) -> str:
    full = int(p * width)
    return "▰" * full + "▱" * (width - full)


async def safe_edit(msg: Message, text: str, **kw) -> bool:
    try:
        await msg.edit_text(text, **kw)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
    except TelegramBadRequest:
        pass
    return False


class Loader:
    """An animated progress message that runs while an API call is in flight."""

    def __init__(self, bot: Bot, chat_id: int, theme: str, title: str, eta: float = 20, interval: float = 1.1):
        self.bot = bot
        self.chat_id = chat_id
        self.theme = THEMES.get(theme, THEMES["generic"])
        self.title = title
        self.eta = eta
        self.interval = interval
        self.msg: Message | None = None
        self.started = time.monotonic()
        self.stage_override: str | None = None
        self.real_progress: float | None = None
        self._tasks: list[asyncio.Task] = []
        self._finished = False

    def stage(self, text: str):
        self.stage_override = text

    def progress(self, p: float):
        self.real_progress = max(0.0, min(1.0, p))

    def _progress(self, elapsed: float) -> float:
        if self.real_progress is not None:
            return self.real_progress
        return 0.96 * (1 - math.exp(-elapsed / max(self.eta / 2.3, 1)))

    def render(self, tick: int) -> str:
        elapsed = time.monotonic() - self.started
        p = self._progress(elapsed)
        stages = self.theme["stages"]
        stage = self.stage_override or stages[min(int(p * len(stages)), len(stages) - 1)]
        dots = "." * (tick % 3 + 1)
        m, s = divmod(int(elapsed), 60)
        return (
            f"{self.theme['icon']} <b>{html.escape(self.title)}</b>  {SPIN[tick % len(SPIN)]}\n\n"
            f"<code>{self.theme['art'](tick, p)}</code>\n\n"
            f"<i>{html.escape(stage)}{dots}</i>\n"
            f"<code>{bar(p)}</code> <b>{int(p * 100)}%</b>\n"
            f"⏱ <code>{m}:{s:02d}</code>"
        )

    async def _animate(self):
        tick = 1
        while not self._finished:
            await asyncio.sleep(self.interval)
            if self._finished:
                break
            await safe_edit(self.msg, self.render(tick))
            tick += 1

    async def _action(self):
        while not self._finished:
            try:
                await self.bot.send_chat_action(self.chat_id, self.theme["action"])
            except Exception:
                pass
            await asyncio.sleep(4.5)

    async def __aenter__(self):
        self.msg = await self.bot.send_message(self.chat_id, self.render(0))
        self._tasks = [asyncio.create_task(self._animate()), asyncio.create_task(self._action())]
        return self

    async def _stop(self):
        self._finished = True
        for t in self._tasks:
            t.cancel()

    async def done(self, text: str = "Готово!"):
        if self._finished:
            return
        await self._stop()
        await safe_edit(
            self.msg,
            f"{self.theme['icon']} <b>{html.escape(self.title)}</b>  ✅\n\n"
            f"<code>{bar(1)}</code> <b>100%</b>\n<i>{html.escape(text)}</i>",
        )
        await asyncio.sleep(0.8)
        try:
            await self.msg.delete()
        except TelegramBadRequest:
            pass

    async def fail(self, err: str):
        if self._finished:
            return
        await self._stop()
        await safe_edit(
            self.msg,
            f"⚠️ <b>{html.escape(self.title)}</b> — не получилось\n\n"
            f"<blockquote>{html.escape(err)[:700]}</blockquote>\n"
            "<i>Проверьте настройки или попробуйте ещё раз.</i>",
        )

    async def __aexit__(self, exc_type, exc, tb):
        if exc is not None:
            await self.fail(getattr(exc, "message", None) or str(exc) or exc_type.__name__)
            return True  # the error is shown to the user in the loader itself
        await self.done()
        return False


async def typewrite(msg: Message, plain: str, final_html: str, steps: int = 8, delay: float = 0.3):
    """Reveals plain text gradually with a cursor, then swaps in the formatted version."""
    words = plain.split(" ")
    per = max(1, math.ceil(len(words) / steps))
    for i in range(per, len(words), per):
        await safe_edit(msg, html.escape(" ".join(words[:i])) + " ▌")
        await asyncio.sleep(delay)
    await safe_edit(msg, final_html)


BOOT_LINES = [
    "Подключение к ядру STELLS",
    "Загрузка нейромодулей",
    "Синхронизация голосовых моделей",
    "Проверка протокола защиты",
]


async def boot(bot: Bot, chat_id: int) -> Message:
    """The terminal-style boot animation shown on /start."""
    msg = await bot.send_message(chat_id, "<code>◇ STELLS OS v2.6 · β</code>")
    done_lines: list[str] = []
    for line in BOOT_LINES:
        for k in range(2):
            body = "\n".join(f"<code>▸ {l} </code>✅" for l in done_lines)
            await safe_edit(
                msg,
                f"<code>◇ STELLS OS v2.6 · β</code>\n\n{body}\n<code>▸ {line} {SPIN[k * 3]}</code>".replace("\n\n\n", "\n\n"),
            )
            await asyncio.sleep(0.35)
        done_lines.append(line)
    body = "\n".join(f"<code>▸ {l} </code>✅" for l in done_lines)
    await safe_edit(msg, f"<code>◇ STELLS OS v2.6 · β</code>\n\n{body}\n\n<b>✦ Система готова ✦</b>")
    await asyncio.sleep(0.6)
    return msg
