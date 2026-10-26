"""Image & Video generation (ElevenLabs Flows): text-to-video, photo animation, talking avatar, images."""
import io

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from config import Config
from eleven import b64_ref
from handlers.common import SIGN, Await, after_kb, api, esc
from handlers.settings import MODEL_NAMES, fmt
from storage import Storage
from ui.anim import EFFECT_FIRE, Loader
from ui.screens import btn, kb, show

router = Router(name="visual")

MAX_UPLOAD = 50 * 1024 * 1024
STATUS_RU = {"pending": "В очереди на рендер", "generating": "Нейросеть рисует кадры"}
PLAN_NOTE = "<i>ℹ️ Генерация изображений и видео в ElevenLabs доступна на тарифе Pro и выше.</i>"


def video_body(s: dict, prompt: str) -> dict:
    body = {
        "model_id": s["video_model"],
        "prompt": prompt,
        "duration_secs": s["video_duration"],
        "aspect_ratio": s["video_aspect"],
        "resolution": s["video_resolution"],
        "generate_audio": s["video_audio"],
    }
    if s["video_model"] == "bytedance-seedance-v2-fast" and s["video_resolution"] == "1080p":
        body["resolution"] = "720p"  # Seedance Fast tops out at 720p
    return body


async def render_flow(msg: Message, store: Storage, cfg: Config, bot: Bot, kind: str, body: dict, title: str):
    """Submits a flows generation, animates while it renders and returns (bytes, mime)."""
    client = api(store, cfg, msg.from_user.id)
    result = None
    eta = 25 if kind == "image" else 150
    async with Loader(bot, msg.chat.id, kind, title, eta=eta) as ld:
        create = client.image_create if kind == "image" else client.video_create
        gen_id = await create(body)

        async def on_status(status):
            if status in STATUS_RU:
                ld.stage(STATUS_RU[status])

        g = await client.wait_generation(kind, gen_id, on_status)
        ld.stage("Скачиваю результат")
        result = await client.download(g["content_url"]), g.get("content_mime_type", ""), g["content_url"]
    return result


async def deliver_video(msg: Message, data: bytes, url: str, caption: str, again: str):
    if len(data) > MAX_UPLOAD:
        await msg.answer(
            caption + "\n\n📦 Видео больше 50 МБ — скачайте его по ссылке (действует ~1 час).",
            reply_markup=kb([btn("⬇️ Скачать видео", url=url)], [btn("🔁 Ещё", again), btn("🏠 Меню", "m:home")]),
        )
        return
    await msg.answer_video(
        BufferedInputFile(data, "stells-video.mp4"),
        caption=caption,
        supports_streaming=True,
        reply_markup=after_kb(again),
        message_effect_id=EFFECT_FIRE,
    )


# ── video ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "f:video")
async def video_screen(cq: CallbackQuery, state: FSMContext, store: Storage):
    s = store.settings(cq.from_user.id)
    await state.set_state(None)
    await cq.answer()
    await show(
        cq,
        "video",
        "🎬 <b>Видео-студия</b>\n\n"
        f"🎥 Модель: <b>{MODEL_NAMES[s['video_model']]}</b>\n"
        f"⏱ {fmt('video_duration', s['video_duration'])} · 📐 {s['video_aspect']} · 🖥 {s['video_resolution']}"
        f" · 🔊 {'со звуком' if s['video_audio'] else 'без звука'}\n\n" + PLAN_NOTE,
        kb(
            [btn("✍️ Видео по описанию", "vi:prompt", style="primary")],
            [btn("🖼 Оживить фото", "vi:photo"), btn("🗣 Говорящий аватар", "vi:avatar")],
            [btn("🎞 Музыка к видео", "mu:v2m"), btn("🌍 Дубляж видео", "f:dub")],
            [btn("⚙️ Настройки видео", "set:tab:visual"), btn("🏠 Меню", "m:home")],
        ),
    )


@router.callback_query(F.data == "vi:prompt")
async def video_prompt_screen(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.video_prompt)
    await cq.answer()
    await show(
        cq,
        "video",
        "✍️ <b>Видео по описанию</b>\n\nОпишите сцену как режиссёр: кто в кадре, что происходит, свет, камера, "
        "атмосфера, звуки.\n\n<blockquote>«Корги на крошечной доске скользит по волне на закате, "
        "кинематографичная съёмка с дрона, брызги в замедлении»</blockquote>",
        kb([btn("⬅️ Назад", "f:video"), btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.video_prompt, F.text)
async def video_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    s = store.settings(msg.from_user.id)
    res = await render_flow(msg, store, cfg, bot, "video", video_body(s, msg.text[:2000]), "Генерация видео")
    if res is None:
        return
    await store.track(msg.from_user.id, "video", msg.text)
    await deliver_video(msg, res[0], res[2], f"🎬 <b>{esc(msg.text[:300])}</b>" + SIGN, "vi:prompt")


@router.callback_query(F.data == "vi:photo")
async def photo_screen(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.video_photo)
    await cq.answer()
    await show(
        cq,
        "video",
        "🖼 <b>Оживить фото</b>\n\nПришлите фотографию — она станет первым кадром видео.",
        kb([btn("⬅️ Назад", "f:video"), btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.video_photo)
async def photo_got(msg: Message, state: FSMContext):
    if not msg.photo and not (msg.document and (msg.document.mime_type or "").startswith("image")):
        await msg.answer("📎 Пришлите, пожалуйста, фото.")
        return
    file_id = msg.photo[-1].file_id if msg.photo else msg.document.file_id
    await state.update_data(photo=file_id)
    await state.set_state(Await.video_photo_prompt)
    await msg.answer("✨ Отлично! Теперь опишите, <b>что должно происходить</b> в видео:")


@router.message(Await.video_photo_prompt, F.text)
async def photo_run(msg: Message, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    data = await state.get_data()
    buf = io.BytesIO()
    await bot.download(data["photo"], destination=buf)
    s = store.settings(msg.from_user.id)
    body = video_body(s, msg.text[:2000])
    body["start_frame"] = b64_ref(buf.getvalue(), "image/jpeg")
    res = await render_flow(msg, store, cfg, bot, "video", body, "Оживление фото")
    if res is None:
        return
    await store.track(msg.from_user.id, "video_photo", msg.text)
    await deliver_video(msg, res[0], res[2], f"🖼➡️🎬 <b>{esc(msg.text[:300])}</b>" + SIGN, "vi:photo")


@router.callback_query(F.data == "vi:avatar")
async def avatar_screen(cq: CallbackQuery, state: FSMContext, store: Storage):
    s = store.settings(cq.from_user.id)
    await state.set_state(Await.avatar_photo)
    await cq.answer()
    await show(
        cq,
        "video",
        "🗣 <b>Говорящий аватар</b>\n\nПришлите портрет — человека, персонажа или питомца. Затем напишите текст, "
        f"и он произнесёт его голосом <b>{esc(s['voice_name'])}</b> с точной синхронизацией губ.",
        kb([btn("🎙 Сменить голос", "f:voices")], [btn("⬅️ Назад", "f:video"), btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.avatar_photo)
async def avatar_photo_got(msg: Message, state: FSMContext):
    if not msg.photo and not (msg.document and (msg.document.mime_type or "").startswith("image")):
        await msg.answer("📎 Пришлите, пожалуйста, портрет.")
        return
    file_id = msg.photo[-1].file_id if msg.photo else msg.document.file_id
    await state.update_data(photo=file_id)
    await state.set_state(Await.avatar_text)
    await msg.answer("🎙 Теперь напишите, <b>что скажет аватар</b>:")


@router.message(Await.avatar_text, F.text)
async def avatar_run(msg: Message, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    data = await state.get_data()
    buf = io.BytesIO()
    await bot.download(data["photo"], destination=buf)
    s = store.settings(msg.from_user.id)
    client = api(store, cfg, msg.from_user.id)
    speech = None
    async with Loader(bot, msg.chat.id, "tts", "Записываю голос", eta=6):
        speech = await client.tts(msg.text[:1500], s["voice_id"], s["tts_model"], s)
    if speech is None:
        return
    body = {
        "model_id": "creatify-aurora",
        "image": b64_ref(buf.getvalue(), "image/jpeg"),
        "audio": b64_ref(speech, "audio/mpeg"),
        "resolution": "720p",
    }
    res = await render_flow(msg, store, cfg, bot, "video", body, "Оживление аватара")
    if res is None:
        return
    await store.track(msg.from_user.id, "avatar", msg.text)
    await deliver_video(msg, res[0], res[2], f"🗣 <i>«{esc(msg.text[:300])}»</i>" + SIGN, "vi:avatar")


# ── images ───────────────────────────────────────────────────────────────
@router.callback_query(F.data == "f:image")
async def image_screen(cq: CallbackQuery, state: FSMContext, store: Storage):
    s = store.settings(cq.from_user.id)
    await state.set_state(Await.image_prompt)
    await cq.answer()
    await show(
        cq,
        "image",
        "🖼 <b>Генерация изображений</b>\n\nПросто напишите, что нарисовать, — или выберите редактирование своего фото.\n\n"
        f"🎨 Модель: <b>{MODEL_NAMES[s['image_model']]}</b> · 📐 {s['image_aspect']}\n\n" + PLAN_NOTE,
        kb(
            [btn("🪄 Редактировать фото", "im:edit", style="primary")],
            [btn("⚙️ Настройки", "set:tab:visual"), btn("🏠 Меню", "m:home")],
        ),
    )


async def image_run(msg: Message, store: Storage, cfg: Config, bot: Bot, prompt: str, ref: bytes | None, again: str):
    s = store.settings(msg.from_user.id)
    body = {"model_id": s["image_model"], "prompt": prompt[:4000], "aspect_ratio": s["image_aspect"]}
    if ref:
        body["images"] = [b64_ref(ref, "image/jpeg")]
    res = await render_flow(msg, store, cfg, bot, "image", body, "Генерация изображения")
    if res is None:
        return
    data, mime, _ = res
    await store.track(msg.from_user.id, "image", prompt)
    ext = "png" if "png" in mime else "jpg"
    await msg.answer_photo(
        BufferedInputFile(data, f"stells.{ext}"),
        caption=f"🎨 <b>{esc(prompt[:300])}</b>" + SIGN,
        reply_markup=after_kb(again, "🎨 Ещё картинку"),
        message_effect_id=EFFECT_FIRE,
    )
    await msg.answer_document(BufferedInputFile(data, f"stells-original.{ext}"), caption="📥 Оригинал без сжатия")


@router.message(Await.image_prompt, F.text)
async def image_prompt_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    await image_run(msg, store, cfg, bot, msg.text, None, "f:image")


@router.callback_query(F.data == "im:edit")
async def image_edit_screen(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.image_edit_photo)
    await cq.answer()
    await show(
        cq,
        "image",
        "🪄 <b>Редактирование фото</b>\n\nПришлите фото, а потом напишите, что изменить: "
        "«сделай в стиле аниме», «замени фон на космос», «добавь неоновую вывеску»…",
        kb([btn("⬅️ Назад", "f:image"), btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.image_edit_photo)
async def image_edit_photo(msg: Message, state: FSMContext):
    if not msg.photo and not (msg.document and (msg.document.mime_type or "").startswith("image")):
        await msg.answer("📎 Пришлите, пожалуйста, фото.")
        return
    await state.update_data(photo=(msg.photo[-1].file_id if msg.photo else msg.document.file_id))
    await state.set_state(Await.image_edit_prompt)
    await msg.answer("✏️ Что изменить на фото?")


@router.message(Await.image_edit_prompt, F.text)
async def image_edit_run(msg: Message, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    data = await state.get_data()
    buf = io.BytesIO()
    await bot.download(data["photo"], destination=buf)
    await image_run(msg, store, cfg, bot, msg.text, buf.getvalue(), "im:edit")
