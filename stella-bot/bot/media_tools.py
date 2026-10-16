"""Инструменты модели «сделать самой»: стикер, картинка, мем, документ, презентация, таблица, видео.

Файл готовится сразу (ошибку в рисунке модель увидит и поправит), а уходит в чат после её сообщения.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from . import media
from .config import Settings
from .db import DB
from .llm.base import ToolSpec

if TYPE_CHECKING:
    from .tools import ToolContext

log = logging.getLogger("stella.media")

MAX_MEDIA_PER_REPLY = 2

SVG_RULES = (
    "SVG пишешь сама: корневой <svg> с viewBox, простые крупные формы, толстая обводка, сочные цвета. "
    "Текст — <text> с font-family=\"DejaVu Sans\" (кириллица работает, эмодзи — нет, рисуй их фигурами). "
    "Нельзя: <image>, <script>, ссылки на внешние файлы и шрифты."
)

BLOCKS_SCHEMA = {
    "type": "array",
    "description": "содержимое по порядку: {type: heading (text, level 1-3) | paragraph (text) | bullets (items) | "
                   "numbered (items) | table (rows: [[...], ...], первая строка — шапка) | quote (text)}",
    "items": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": ["heading", "paragraph", "bullets", "numbered", "table", "quote"]},
            "text": {"type": "string"},
            "level": {"type": "integer"},
            "items": {"type": "array", "items": {"type": "string"}},
            "rows": {"type": "array", "items": {"type": "array", "items": {}}},
        },
        "required": ["type"],
    },
}


class _Budget:
    """Не больше MAX_MEDIA_PER_REPLY файлов за ответ и MEDIA_PER_DAY на чат в сутки."""

    def __init__(self, db: DB, settings: Settings, ctx: "ToolContext"):
        self.db, self.s, self.ctx = db, settings, ctx

    async def take(self) -> None:
        from .tools import ToolError

        if not self.s.media_enabled:
            raise ToolError("создание файлов сейчас выключено владельцем")
        if self.ctx.actions is None:
            raise ToolError("здесь файлы отправить нельзя")
        if self.ctx.media_queued >= MAX_MEDIA_PER_REPLY:
            raise ToolError("за один ответ хватит двух файлов")
        used = await self.db.kv_get(f"media:{self.ctx.chat_id}:{date.today().isoformat()}")
        if used and used[1] >= self.s.media_per_day:
            raise ToolError("на сегодня в этом чате лимит файлов исчерпан, давай завтра")

    async def queue(self, file: media.MediaFile, caption: str = "") -> str:
        self.ctx.media_queued += 1
        await self.db.kv_add(f"media:{self.ctx.chat_id}:{date.today().isoformat()}", 1)
        actions = self.ctx.actions

        async def send() -> None:
            await actions.send_file(file, caption)

        self.ctx.after.append(send)
        return "готово — уйдёт в чат сразу после твоего сообщения"


def build_media_tools(db: DB, settings: Settings, ctx: "ToolContext") -> list[ToolSpec]:
    from .tools import ToolError

    budget = _Budget(db, settings, ctx)

    async def run(fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except media.MediaError as exc:
            raise ToolError(str(exc)) from exc

    async def make_sticker(args: dict[str, Any]) -> str:
        await budget.take()
        file = await run(media.sticker_from_svg, str(args.get("svg") or ""))
        mood = str(args.get("mood") or "").strip().lower()[:40]
        if mood and ctx.actions is not None:
            await ctx.actions.learn_sticker(file.data, mood)  # потом можно снова: [стикер: mood]
        return await budget.queue(file)

    async def make_picture(args: dict[str, Any]) -> str:
        await budget.take()
        file = await run(media.picture_from_svg, str(args.get("svg") or ""), str(args.get("shape") or "square"))
        return await budget.queue(file, str(args.get("caption") or "")[:500])

    async def make_meme(args: dict[str, Any]) -> str:
        await budget.take()
        if ctx.quoted_media is None:
            raise ToolError("мем делается из фото или стикера: пусть ответят на него или пришлют с подписью")
        key, message = ctx.quoted_media
        data = await ctx.actions.fetch_media(key, message)
        if not data:
            raise ToolError("не получилось скачать картинку")
        file = await run(media.meme, data, str(args.get("top") or ""), str(args.get("bottom") or ""),
                         bool(args.get("as_sticker")))
        return await budget.queue(file)

    async def make_document(args: dict[str, Any]) -> str:
        await budget.take()
        fmt = str(args.get("format") or "docx").lower()
        fn = media.document_pdf if fmt == "pdf" else media.document_docx
        file = await run(fn, str(args.get("title") or ""), args.get("blocks"))
        return await budget.queue(file, str(args.get("caption") or "")[:500])

    async def make_presentation(args: dict[str, Any]) -> str:
        await budget.take()
        file = await run(media.presentation, str(args.get("title") or ""), str(args.get("subtitle") or ""),
                         args.get("slides"))
        return await budget.queue(file, str(args.get("caption") or "")[:500])

    async def make_spreadsheet(args: dict[str, Any]) -> str:
        await budget.take()
        file = await run(media.spreadsheet, str(args.get("title") or ""), args.get("sheets"))
        return await budget.queue(file, str(args.get("caption") or "")[:500])

    async def make_video(args: dict[str, Any]) -> str:
        await budget.take()
        scenes = args.get("scenes")
        shape = str(args.get("shape") or "square")
        if not isinstance(scenes, list) or not scenes:
            raise ToolError("scenes: список сцен")
        # рисунки проверяем сразу (ошибку модель поправит), а ролик собирается уже после её сообщения
        for s in scenes[: media.VIDEO_MAX_SCENES]:
            if isinstance(s, dict) and s.get("svg"):
                await run(media.render_svg, str(s["svg"]), 64, 64)
        ready: dict[str, media.MediaFile] = {}

        async def build() -> None:
            ready["file"] = await media.video(scenes, shape)

        caption = str(args.get("caption") or "")[:500]
        ctx.media_queued += 1
        await db.kv_add(f"media:{ctx.chat_id}:{date.today().isoformat()}", 1)
        actions = ctx.actions

        async def send() -> None:
            try:
                await build()
            except media.MediaError as exc:
                log.warning("видео не собралось: %s", exc)
                await actions.say("видео не получилось собрать 😕")
                return
            await actions.send_file(ready["file"], caption)

        ctx.after.append(send)
        return "ролик соберётся и уйдёт в чат сразу после твоего сообщения (секунд 10–30)"

    shape = {"type": "string", "enum": ["square", "wide", "tall"], "description": "квадрат, 16:9 или вертикальное"}
    return [
        ToolSpec(
            "make_sticker",
            "Нарисовать СВОЙ стикер и отправить его в чат. " + SVG_RULES +
            " viewBox=\"0 0 512 512\", прозрачный фон, персонаж или предмет крупно по центру. "
            "mood — настроение, под которым сохранить (потом можно снова: [стикер: mood]).",
            {"type": "object", "properties": {"svg": {"type": "string"}, "mood": {"type": "string"}},
             "required": ["svg"]},
            make_sticker,
        ),
        ToolSpec(
            "make_picture",
            "Нарисовать картинку (иллюстрацию, схему, открытку, график) и отправить в чат. " + SVG_RULES +
            " viewBox под форму: square 0 0 1080 1080, wide 0 0 1280 720, tall 0 0 720 1280; фон закрась сама.",
            {"type": "object", "properties": {"svg": {"type": "string"}, "shape": shape,
                                              "caption": {"type": "string"}}, "required": ["svg"]},
            make_picture,
        ),
        ToolSpec(
            "make_meme",
            "Сделать мем из фото или стикера, на которое ответили (или которое прислали с подписью): "
            "текст сверху и/или снизу. as_sticker — отправить как стикер.",
            {"type": "object", "properties": {"top": {"type": "string"}, "bottom": {"type": "string"},
                                              "as_sticker": {"type": "boolean"}}},
            make_meme,
        ),
        ToolSpec(
            "make_document",
            "Сделать документ (доклад, реферат, конспект, письмо…) и отправить файлом. format: docx (Word) "
            "или pdf.",
            {"type": "object", "properties": {
                "format": {"type": "string", "enum": ["docx", "pdf"]},
                "title": {"type": "string"},
                "blocks": BLOCKS_SCHEMA,
                "caption": {"type": "string"},
            }, "required": ["title", "blocks"]},
            make_document,
        ),
        ToolSpec(
            "make_presentation",
            "Сделать презентацию PowerPoint (.pptx) и отправить файлом. Слайды: {title, bullets: [3–6 коротких "
            "пунктов], notes?: что говорить, svg?: картинка к слайду (" + SVG_RULES + " viewBox 0 0 900 900)}.",
            {"type": "object", "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "slides": {"type": "array", "items": {"type": "object", "properties": {
                    "title": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                    "svg": {"type": "string"},
                }, "required": ["title"]}},
                "caption": {"type": "string"},
            }, "required": ["title", "slides"]},
            make_presentation,
        ),
        ToolSpec(
            "make_spreadsheet",
            "Сделать таблицу Excel (.xlsx) и отправить файлом: расписание, оценки, список, бюджет… "
            "Листы: {name, rows: [[...], ...]}, первая строка — шапка. Числа пиши числами.",
            {"type": "object", "properties": {
                "title": {"type": "string"},
                "sheets": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string"},
                    "rows": {"type": "array", "items": {"type": "array", "items": {}}},
                }, "required": ["rows"]}},
                "caption": {"type": "string"},
            }, "required": ["title", "sheets"]},
            make_spreadsheet,
        ),
        ToolSpec(
            "make_video",
            "Сделать короткое видео (до 40 с, без звука) — слайдшоу из сцен с плавным приближением и затуханием, "
            "и отправить в чат. Сцена: {svg?: рисунок (" + SVG_RULES + " viewBox под форму видео: square "
            "0 0 720 720, wide 0 0 1280 720, tall 0 0 720 1280), text?: крупный текст, если нет рисунка, "
            "caption?: подпись снизу, seconds: 1–8, bg?: цвет фона #RRGGBB}. До 12 сцен.",
            {"type": "object", "properties": {
                "scenes": {"type": "array", "items": {"type": "object", "properties": {
                    "svg": {"type": "string"},
                    "text": {"type": "string"},
                    "caption": {"type": "string"},
                    "seconds": {"type": "number"},
                    "bg": {"type": "string"},
                }}},
                "shape": shape,
                "caption": {"type": "string"},
            }, "required": ["scenes"]},
            make_video,
        ),
    ]
