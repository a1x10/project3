"""Инструменты модели «сделать самой»: стикер, картинка, мем, документ, презентация, таблица, видео.

Файл готовится сразу (ошибку в рисунке модель увидит и поправит), а уходит в чат после её сообщения.
"""

from __future__ import annotations

import asyncio
import logging
import time
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


STUDIO_WORDS = {
    "page": {"one": "страница", "acc": "страницу", "many": "страниц", "off": "HTML-страницы сейчас выключены владельцем",
             "brief": "brief: опиши подробно, что сделать (повод, тексты, стиль, что двигается и нажимается)",
             "almost": "ещё чуть-чуть, страница почти готова ⏳", "fail": "страница не получилась 😕",
             "doing": "делаю страницу ✨", "arrives": "файл придёт", "skip": "Код писать не нужно."},
    "deck": {"one": "презентация", "acc": "презентацию", "many": "презентаций",
             "off": "презентации из студии сейчас выключены владельцем",
             "brief": "brief: опиши подробно (тема, для кого, сколько слайдов, факты и цифры, стиль)",
             "almost": "ещё чуть-чуть, презентация почти готова ⏳", "fail": "презентация не получилась 😕",
             "doing": "делаю презентацию 🎨", "arrives": "PowerPoint и PDF придут",
             "skip": "Слайды писать не нужно."},
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
        if self.s.media_per_day > 0 and used and used[1] >= self.s.media_per_day and not self.ctx.is_admin:  # владельцу, админам и друзьям — без лимита
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

    async def studio_job(args: dict[str, Any], kind: str) -> str:
        """Страница или презентация из студии: проверить лимиты, сказать «делаю, будет через N», сделать в фоне,
        прислать файлы ответом на просьбу (неудача — сообщение и возврат лимитов)."""
        from . import html_studio, weblibs
        from .sandbox import is_owner

        w = STUDIO_WORDS[kind]
        if not getattr(settings, "html_enabled", True):
            raise ToolError(w["off"])
        if ctx.sender is None:
            raise ToolError(f"{w['one']} — только когда о ней просят")
        if getattr(ctx, "html_queued", False):
            raise ToolError(f"за один ответ — одна {w['one']}")
        title = " ".join(str(args.get("title") or "").split())[:80] or w["one"]
        brief = str(args.get("brief") or "").strip()
        if len(brief) < 20:
            raise ToolError(w["brief"])
        await budget.take()
        owner = is_owner(settings, ctx)
        today = date.today().isoformat()
        day_key, all_key = f"html:{ctx.chat_id}:{today}", f"html:all:{today}"
        used = await db.kv_get(day_key)
        if settings.html_per_day > 0 and not ctx.is_admin and used and used[1] >= settings.html_per_day:
            raise ToolError(f"на сегодня {w['many']} в этом чате хватит, давай завтра")
        used_all = await db.kv_get(all_key)
        if (settings.html_per_day_total > 0 and not (owner or ctx.is_admin) and used_all
                and used_all[1] >= settings.html_per_day_total):
            raise ToolError(f"на сегодня {w['many']} хватит, давай завтра")
        spent = await db.kv_get(f"spend:{today}")
        # учитываем и то, что ещё делается: расходы записываются только по готовности, через минуты
        projected = (spent[1] if spent else 0.0) + html_studio.STATE.reserved_usd
        if not owner and settings.daily_budget_usd > 0 and projected >= settings.daily_budget_usd:
            raise ToolError(f"на сегодня бюджет кончился — {w['acc']} сделаю завтра")
        if ctx.chat_id in html_studio.STATE.busy_chats:
            raise ToolError(f"я уже делаю {w['acc']} для этого чата — подожди, пока пришлю")
        photo = seen = None
        if args.get("use_photo"):
            if ctx.quoted_media is None:
                raise ToolError("фото нет: пусть ответят на фото или пришлют его с просьбой")
            raw = await ctx.actions.fetch_media(*ctx.quoted_media)
            photo = await asyncio.to_thread(media.photo_for_page, raw) if raw else None
            seen = await asyncio.to_thread(media.image_for_model, raw) if raw else None
            if photo is None or seen is None:
                raise ToolError("не получилось скачать фото")
        eta_s = html_studio.estimate_seconds(settings.html_concurrency)
        eta = html_studio.human_eta(eta_s)
        caption = str(args.get("caption") or "")[:500]
        ctx.html_queued = True
        ctx.media_queued += 1
        media_key = f"media:{ctx.chat_id}:{today}"
        for key in (media_key, day_key, all_key):
            await db.kv_add(key, 1)
        html_studio.STATE.busy_chats.add(ctx.chat_id)  # сразу: второй заказ в этот чат не встанет в очередь
        reserve = html_studio.expected_cost(settings)
        html_studio.STATE.reserved_usd += reserve
        actions = ctx.actions
        released = asyncio.Event()

        async def wait_reply() -> None:
            try:
                await asyncio.wait_for(released.wait(), 120)
            except asyncio.TimeoutError:
                pass  # её ответ так и не ушёл — шлём всё равно

        async def refund() -> None:  # файл не дошёл — лимиты не тратим
            for key in (media_key, day_key, all_key):
                await db.kv_add(key, -1)

        async def is_paused() -> bool:
            check = getattr(actions, "paused", None)
            try:
                return bool(check and await check())
            except Exception:
                return False

        async def fail(text: str) -> None:
            await refund()
            await wait_reply()
            if not await is_paused():
                await actions.say(text)

        async def deliver() -> None:
            libs = asyncio.ensure_future(weblibs.ensure())  # библиотеки докачиваются, пока пишется код
            task = asyncio.ensure_future(html_studio.run(
                settings, brief, title, seen, build=lambda html: media.html_page(title, html, photo).data,
                kind=kind))
            try:
                done, _ = await asyncio.wait({task}, timeout=eta_s * 1.5 + 30)
                if not done:
                    await wait_reply()
                    if not await is_paused():
                        await actions.say(w["almost"])
                result = await task
            except html_studio.StudioError as exc:
                if exc.cost_usd and ctx.on_cost is not None:
                    await ctx.on_cost(exc.cost_usd)
                await fail(f"{w['fail']} {exc}")
                return
            except Exception as exc:
                log.exception("студия (%s): ошибка", kind)
                await fail(f"{w['fail']} ({type(exc).__name__}) попробуй ещё раз")
                return
            finally:
                if not task.done():
                    task.cancel()
                html_studio.STATE.busy_chats.discard(ctx.chat_id)
                html_studio.STATE.reserved_usd = max(0.0, html_studio.STATE.reserved_usd - reserve)
            if ctx.on_cost is not None:
                await ctx.on_cost(result.cost_usd)
            try:
                await asyncio.wait_for(asyncio.shield(libs), 60)
            except Exception:
                log.warning("библиотеки для страницы не скачались — подключатся с CDN", exc_info=True)
            try:
                if kind == "deck":
                    files = list(await asyncio.to_thread(media.deck_files, title, result.shots.slides))
                else:
                    files = [await asyncio.to_thread(media.html_page, title, result.html, photo)]
            except media.MediaError as exc:
                await fail(f"{w['fail']} {exc}")
                return
            await wait_reply()
            if await is_paused():  # пока делалось, чат поставили на паузу — молчим
                await refund()
                return
            sent = await actions.send_file(files[0], caption, reply=True)
            if sent is False:
                await refund()
                return
            for extra in files[1:]:  # у презентации ещё PDF — чтобы листать прямо в телефоне
                await actions.send_file(extra, "")

        async def release() -> None:  # сразу после её сообщения; очередь ответов чата не ждёт студию
            if not getattr(ctx, "replied", 0):
                await actions.say(f"{w['doing']} будет готова {eta}")
            released.set()

        ctx.after.append(release)
        actions.spawn(deliver())
        return (f"{w['one']} «{title}» уже делается в студии, будет готова {eta}. Обязательно скажи в ответе своими "
                f"словами, что делаешь и сколько ждать ({eta}); {w['arrives']} отдельным сообщением. {w['skip']}")

    async def make_html(args: dict[str, Any]) -> str:
        return await studio_job(args, "page")

    async def make_deck(args: dict[str, Any]) -> str:
        return await studio_job(args, "deck")

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

    async def make_cartoon(args: dict[str, Any]) -> str:
        from .anim_beta import runner
        from .anim_beta import spec as anim_spec

        if not getattr(settings, "anim_enabled", True):
            raise ToolError("мультики сейчас выключены владельцем")
        if ctx.sender is None:
            raise ToolError("мультик — только когда о нём просят")
        if getattr(ctx, "cartoon_queued", False):
            raise ToolError("за один ответ — один мультик")
        await budget.take()
        day_key = f"anim:{ctx.chat_id}:{date.today().isoformat()}"
        used = await db.kv_get(day_key)
        limit = getattr(settings, "anim_per_day", 0)
        if limit > 0 and not ctx.is_admin and used and used[1] >= limit:
            raise ToolError("на сегодня мультиков в этом чате хватит, давай завтра")
        busy = runner.can_start(ctx.chat_id)
        if busy:
            raise ToolError(busy)
        try:
            plan, warnings, caption = await asyncio.to_thread(anim_spec.parse, args)
        except anim_spec.SpecError as exc:
            raise ToolError(str(exc)) from exc
        eta_s = runner.estimate_seconds(plan)
        eta = runner.human_eta(eta_s)
        ctx.cartoon_queued = True
        ctx.media_queued += 1
        media_key = f"media:{ctx.chat_id}:{date.today().isoformat()}"
        await db.kv_add(media_key, 1)
        await db.kv_add(day_key, 1)
        runner.STATE.busy_chats.add(ctx.chat_id)  # сразу: второй мультик в этот чат не встанет в очередь
        actions = ctx.actions
        released = asyncio.Event()

        async def wait_reply() -> None:
            try:
                await asyncio.wait_for(released.wait(), 120)
            except asyncio.TimeoutError:
                pass  # её ответ так и не ушёл — шлём всё равно

        async def deliver() -> None:
            task = asyncio.ensure_future(runner.render(plan, ctx.chat_id))  # рисует, пока она пишет ответ
            started = time.monotonic()
            try:
                done, _ = await asyncio.wait({task}, timeout=eta_s * 1.5 + 10)
                if not done:
                    await wait_reply()
                    if not await is_paused():
                        await actions.say("ещё чуть-чуть, мультик почти готов ⏳")
                data = await task
            except runner.RenderError as exc:
                await refund()
                await wait_reply()
                if not await is_paused():
                    await actions.say(f"мультик не получился 😕 {exc}")
                return
            except Exception:
                log.exception("мультик: ошибка")
                await refund()
                await wait_reply()
                if not await is_paused():
                    await actions.say("мультик не получился 😕 попробуй ещё раз")
                return
            finally:
                if not task.done():
                    task.cancel()
                runner.STATE.busy_chats.discard(ctx.chat_id)
            await wait_reply()
            log.info("мультик готов за %.0f с (обещала %.0f)", time.monotonic() - started, eta_s)
            if await is_paused():  # пока рисовался, чат поставили на паузу — молчим
                await refund()
                return
            sent = await actions.send_file(media.MediaFile("video", data, media.MIME["mp4"], "cartoon.mp4"), caption)
            if sent is False:
                await refund()

        async def refund() -> None:  # ролик не дошёл — дневной лимит не тратим
            await db.kv_add(day_key, -1)
            await db.kv_add(media_key, -1)

        async def is_paused() -> bool:
            check = getattr(actions, "paused", None)
            try:
                return bool(check and await check())
            except Exception:
                return False

        async def release() -> None:  # сразу после её сообщения; очередь ответов чата не ждёт рендер
            if not getattr(ctx, "replied", 0):
                await actions.say(f"делаю мультик 🎬 будет готов {eta}")
            released.set()

        ctx.after.append(release)
        actions.spawn(deliver())
        total = sum(s["dur"] for s in plan["scenes"])
        note = f" Поправила в сценарии: {'; '.join(warnings)}." if warnings else ""
        return (f"мультик ({total:.0f} с) уже рисуется, будет готов {eta}. Обязательно скажи в ответе своими "
                f"словами, что делаешь мультик и что ждать примерно {eta}; сам ролик придёт отдельным сообщением."
                + note)

    from . import page_shots

    # презентации 10/10 делает студия (слайды рисуются в браузере); нет браузера — простая из списка слайдов
    deck_studio = settings.html_enabled and settings.deck_studio and page_shots.available()
    deck_tool = ToolSpec(
        "make_presentation",
        "Сделать презентацию уровня Apple Keynote: дизайн-студия (Opus) по твоему заданию придумывает историю, "
        "рисует каждый слайд (иллюстрации, диаграммы, 3D, красивые шрифты), проверяет и доводит его, пишет текст "
        "выступления в заметки. Придут PowerPoint (.pptx) и PDF отдельными сообщениями через несколько минут. Ты "
        "пишешь только brief — подробное задание.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "название (и имя файла)"},
            "brief": {"type": "string", "description": (
                "подробное задание: тема и цель, для кого (класс, работа, друзья), сколько слайдов, что обязательно "
                "должно быть (факты, цифры, имена, планы, требования учителя — студия чата не видит; свежие факты "
                "сначала найди в интернете и положи сюда), стиль и цвета, если просили, автор для обложки")},
            "use_photo": {"type": "boolean",
                          "description": "встроить фото, на которое ответили или которое прислали с просьбой"},
            "caption": {"type": "string", "description": "подпись к файлу (необязательно)"},
        }, "required": ["title", "brief"]},
        make_deck,
    )
    shape = {"type": "string", "enum": ["square", "wide", "tall"], "description": "квадрат, 16:9 или вертикальное"}
    from .anim_beta import spec as anim_spec

    color = {"type": "string", "description": "#RRGGBB"}
    cartoon_schema = {"type": "object", "properties": {
        "format": shape,
        "caption": {"type": "string"},
        "cast": {"type": "object", "description": "id -> персонаж (до 4)", "additionalProperties": {
            "type": "object", "properties": {"kind": {"type": "string", "enum": list(anim_spec.KINDS)},
                                             "color": color, "eyes": color}, "required": ["kind"]}},
        "things": {"type": "object", "description": "id -> 3D-предмет (до 3)", "additionalProperties": {
            "type": "object", "properties": {"shape": {"type": "string", "enum": list(anim_spec.SHAPES)},
                                             "color": color, "size": {"type": "number"}}, "required": ["shape"]}},
        "scenes": {"type": "array", "items": {"type": "object", "properties": {
            "seconds": {"type": "number"},
            "background": {"type": "string", "enum": list(anim_spec.BACKGROUNDS)},
            "zoom": {"type": "number"},
            "place": {"type": "object", "additionalProperties": {"type": "object", "properties": {
                "x": {"type": "number"}, "y": {"type": "number"},
                "facing": {"type": "string", "enum": ["left", "right"]}}}},
            "events": {"type": "array", "items": {"type": "object", "properties": {
                "t": {"type": "number"}, "who": {"type": "string"},
                "do": {"type": "string", "enum": list(anim_spec.ACTS)}, "to": {"type": "number"},
                "say": {"type": "string"}, "emotion": {"type": "string", "enum": list(anim_spec.EMOTIONS)},
                "dur": {"type": "number"}, "fx": {"type": "string", "enum": ["confetti"]},
                "x": {"type": "number"}, "y": {"type": "number"}}}},
        }, "required": ["events"]}},
    }, "required": ["scenes"]}
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
        deck_tool if deck_studio else ToolSpec(
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
            "make_html",
            "Сделать HTML-страницу и прислать файлом .html (открывается в браузере телефона): игру, викторину, "
            "открытку-поздравление с 3D и анимацией, сайт, лендинг, шпаргалку, калькулятор, таймер. Код пишешь НЕ "
            "ты: отдельная дизайн-студия (Opus) делает и доводит страницу несколько минут (3D, анимации, шрифты), а "
            "ты пишешь только brief — подробное задание. Файл придёт отдельным сообщением.",
            {"type": "object", "properties": {
                "title": {"type": "string", "description": "короткое название (и имя файла)"},
                "brief": {"type": "string", "description": (
                    "подробное задание для дизайнера: что за страница и для кого, повод; все имена, факты, шутки и "
                    "тексты из чата, которые нужны (дизайнер чата не видит); вопросы и ответы для викторины; правила "
                    "для игры; настроение, стиль, цвета, если просили; что должно двигаться и что можно нажимать")},
                "use_photo": {"type": "boolean",
                              "description": "встроить фото, на которое ответили или которое прислали с просьбой"},
                "caption": {"type": "string", "description": "подпись к файлу (необязательно)"},
            }, "required": ["title", "brief"]},
            make_html,
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
            "Сделать короткое видео (до 40 с, без звука) — слайдшоу из картинок с плавным приближением и затуханием, "
            "и отправить в чат (мультик с движением — make_cartoon). Сцена: {svg?: рисунок (" + SVG_RULES + " viewBox под форму видео: square "
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
        ToolSpec(
            "make_cartoon",
            "Сделать МУЛЬТИК с настоящим движением (до 20 с, без звука): персонажи ходят, машут, прыгают, танцуют, "
            "крутятся, говорят (рот двигается, реплика в пузыре), меняют эмоции; 3D-предметы вращаются; конфетти; "
            "камера плавно приближается. Рисует сервер по твоему сценарию — сама не рисуешь и код не пишешь. "
            "Ролик придёт отдельным сообщением; инструмент вернёт примерное время — ОБЯЗАТЕЛЬНО скажи в ответе, что "
            "делаешь мультик и сколько ждать. Пока бета: kind — cat, fox, bunny, bear, toy (3D-зверёк); shape — gem, "
            "star, donut, ball; фон — meadow (день), sunset, night. cast: {id: {kind, color?, eyes?}} до 4; "
            "things: {id: {shape, color?, size? 0.4–1.4}} до 3; scenes (1–4): {seconds, background, zoom? 1–1.3, "
            "place: {id: {x 0..1, y (только предметам), facing?}} — не указан: в кадре все; персонажей сервер сам "
            "раздвинет, events: [{t: секунда сцены, who, do?: walk (to: "
            "x)|wave|jump|dance|spin, say?: до 80 знаков, emotion?, dur?}, {t, fx: confetti, x, y}]}. Пиши живо: "
            "4–10 событий на сцену, короткие реплики, смена эмоций. Эмодзи не рисуются (можно ♥ ★ ♪ ☺).",
            cartoon_schema,
            make_cartoon,
        ),
    ]
