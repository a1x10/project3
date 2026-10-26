"""Voice library, voice design from a description and instant voice cloning."""
import base64
import io

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from config import Config
from eleven import ElevenError
from handlers.common import SIGN, Await, api, audio_file, cancel_kb, esc, media_of
from storage import Storage
from ui.anim import EFFECT_PARTY, Loader
from ui.screens import btn, kb, show

router = Router(name="voices")

PAGE = 7
_cache: dict[int, list] = {}


def describe(v: dict) -> str:
    labels = v.get("labels") or {}
    parts = [labels.get(k) for k in ("gender", "age", "accent") if labels.get(k)]
    return ", ".join(parts)


async def render_list(cq: CallbackQuery | Message, store: Storage, page: int, title: str):
    uid = cq.from_user.id
    voices = _cache.get(uid, [])
    s = store.settings(uid)
    pages = max(1, (len(voices) + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    rows = []
    for v in voices[page * PAGE : (page + 1) * PAGE]:
        mark = "✅ " if v["voice_id"] == s["voice_id"] else ""
        rows.append([
            btn("▶️", f"vo:play:{v['voice_id']}"),
            btn(f"{mark}{v.get('name', '?')[:22]}", f"vo:sel:{v['voice_id']}", style="success" if mark else None),
        ])
    nav = [btn("◀️", f"vo:pg:{page - 1}"), btn(f"{page + 1}/{pages}", "noop"), btn("▶️", f"vo:pg:{page + 1}")]
    rows += [
        nav,
        [btn("🔍 Поиск", "vo:search"), btn("👤 Мои голоса", "vo:mine"), btn("🌐 Все", "f:voices")],
        [btn("🧬 Дизайн голоса", "f:design"), btn("🧪 Клон голоса", "f:clone")],
        [btn("🏠 Меню", "m:home")],
    ]
    caption = (
        f"📚 <b>{title}</b>\n\nТекущий голос: <b>{esc(s['voice_name'])}</b>\n"
        "▶️ — прослушать, название — выбрать для всех функций."
    )
    await show(cq, "voices", caption, kb(*rows))


async def load(cq, store: Storage, cfg: Config, bot: Bot, title: str, **query):
    uid = cq.from_user.id
    voices = None
    async with Loader(bot, cq.message.chat.id if isinstance(cq, CallbackQuery) else cq.chat.id, "voice", "Загружаю голоса", eta=3):
        voices = await api(store, cfg, uid).voices(page_size=100, **query)
    if voices is None:
        return
    _cache[uid] = voices
    if not voices:
        await bot.send_message(uid, "🔎 Ничего не нашлось.")
    await render_list(cq, store, 0, title)


@router.callback_query(F.data == "f:voices")
async def voices_screen(cq: CallbackQuery, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    await state.set_state(None)
    await cq.answer()
    await load(cq, store, cfg, bot, "Библиотека голосов")


@router.callback_query(F.data == "vo:mine")
async def voices_mine(cq: CallbackQuery, store: Storage, cfg: Config, bot: Bot):
    await cq.answer()
    await load(cq, store, cfg, bot, "Мои голоса", voice_type="personal")


@router.callback_query(F.data.startswith("vo:pg:"))
async def voices_page(cq: CallbackQuery, store: Storage):
    await cq.answer()
    await render_list(cq, store, int(cq.data.split(":")[2]), "Библиотека голосов")


@router.callback_query(F.data == "vo:search")
async def voices_search(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.voice_search)
    await cq.answer()
    await cq.message.answer("🔍 Напишите, какой голос ищете: имя, «female», «british», «deep»…", reply_markup=cancel_kb("f:voices"))


@router.message(Await.voice_search, F.text)
async def voices_search_run(msg: Message, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    await state.set_state(None)
    await load(msg, store, cfg, bot, f"Поиск: {msg.text[:30]}", search=msg.text[:60])


def _find(uid: int, voice_id: str) -> dict | None:
    return next((v for v in _cache.get(uid, []) if v["voice_id"] == voice_id), None)


@router.callback_query(F.data.startswith("vo:sel:"))
async def voice_select(cq: CallbackQuery, store: Storage):
    voice_id = cq.data.split(":", 2)[2]
    v = _find(cq.from_user.id, voice_id) or {"voice_id": voice_id, "name": voice_id[:8]}
    await store.set_setting(cq.from_user.id, "voice_id", voice_id)
    await store.set_setting(cq.from_user.id, "voice_name", v.get("name", "?"))
    await cq.answer(f"🎙 Голос «{v.get('name')}» выбран!")
    await render_list(cq, store, 0, "Библиотека голосов")


@router.callback_query(F.data.startswith("vo:play:"))
async def voice_play(cq: CallbackQuery, store: Storage, cfg: Config):
    v = _find(cq.from_user.id, cq.data.split(":", 2)[2])
    if not v or not v.get("preview_url"):
        await cq.answer("У этого голоса нет превью", show_alert=True)
        return
    await cq.answer("▶️ Загружаю превью…")
    try:
        data = await api(store, cfg, cq.from_user.id).download(v["preview_url"])
    except Exception:
        await cq.message.answer("⚠️ Не удалось загрузить превью, попробуйте ещё раз.")
        return
    await cq.message.answer_audio(
        audio_file(data, v.get("name", "voice")),
        title=v.get("name", "Голос"),
        performer="STELLS Voices",
        caption=f"🎙 <b>{esc(v.get('name'))}</b>\n<i>{esc(describe(v))}</i>",
        reply_markup=kb([btn("✅ Выбрать этот голос", f"vo:sel:{v['voice_id']}", style="success")]),
    )


# ── voice design ─────────────────────────────────────────────────────────
@router.callback_query(F.data == "f:design")
async def design_screen(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.design_desc)
    await cq.answer()
    await show(
        cq,
        "design",
        "🧬 <b>Дизайн голоса</b>\n\nОпишите голос, которого не существует, — я создам несколько вариантов.\n\n"
        "<blockquote>«Хриплый пожилой пират с ирландским акцентом, говорит медленно и загадочно»\n\n"
        "«Молодая девушка-диктор, тёплый бархатный тембр, лёгкая улыбка в голосе»</blockquote>",
        kb([btn("📚 Голоса", "f:voices"), btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.design_desc, F.text)
async def design_run(msg: Message, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    desc = msg.text.strip()[:1000]
    if len(desc) < 20:
        await msg.answer("✍️ Опишите голос чуть подробнее — хотя бы 20 символов.")
        return
    res = None
    async with Loader(bot, msg.chat.id, "voice", "Дизайн голоса", eta=20):
        res = await api(store, cfg, msg.from_user.id).design_voice(desc)
    if res is None:
        return
    previews = res.get("previews", [])[:3]
    await state.update_data(design_desc=desc, design_ids=[p["generated_voice_id"] for p in previews])
    await store.track(msg.from_user.id, "design", desc)
    for i, p in enumerate(previews):
        await msg.answer_audio(
            BufferedInputFile(base64.b64decode(p["audio_base_64"]), f"variant-{i + 1}.mp3"),
            title=f"Вариант {i + 1}",
            performer="STELLS Voice Design",
            caption=f"🧬 <b>Вариант {i + 1}</b>",
            reply_markup=kb([btn(f"💾 Сохранить вариант {i + 1}", f"ds:save:{i}", style="success")]),
        )
    await msg.answer(
        "🎧 Послушайте варианты и сохраните понравившийся. Или опишите голос иначе — я попробую снова.",
        reply_markup=kb([btn("🏠 Меню", "m:home")]),
    )


@router.callback_query(F.data.startswith("ds:save:"))
async def design_pick(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    idx = int(cq.data.split(":")[2])
    if idx >= len(data.get("design_ids", [])):
        await cq.answer("Этот вариант уже недоступен — создайте голос заново", show_alert=True)
        return
    await state.update_data(design_pick=data["design_ids"][idx])
    await state.set_state(Await.design_name)
    await cq.answer()
    await cq.message.answer("✏️ Как назовём новый голос?", reply_markup=cancel_kb())


@router.message(Await.design_name, F.text)
async def design_save(msg: Message, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    data = await state.get_data()
    name = msg.text.strip()[:40]
    v = None
    async with Loader(bot, msg.chat.id, "voice", "Сохраняю голос", eta=4):
        v = await api(store, cfg, msg.from_user.id).save_designed_voice(name, data["design_desc"], data["design_pick"])
    if v is None:
        return
    await store.set_setting(msg.from_user.id, "voice_id", v["voice_id"])
    await store.set_setting(msg.from_user.id, "voice_name", name)
    await state.set_state(None)
    await msg.answer(
        f"🎉 Голос <b>{esc(name)}</b> сохранён и выбран для всех функций!" + SIGN,
        reply_markup=kb([btn("🗣 Озвучить текст", "f:tts", style="primary"), btn("🏠 Меню", "m:home")]),
        message_effect_id=EFFECT_PARTY,
    )


# ── instant voice cloning ────────────────────────────────────────────────
@router.callback_query(F.data == "f:clone")
async def clone_screen(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.clone_samples)
    await state.update_data(samples=[])
    await cq.answer()
    await show(
        cq,
        "clone",
        "🧪 <b>Клонирование голоса</b>\n\nПришлите от 1 до 5 голосовых или аудио с чистой речью "
        "(лучше 1–2 минуты без музыки и шума). Затем нажмите «Создать клон».\n\n"
        "<blockquote>⚖️ Клонируйте только свой голос или голос человека, который дал на это согласие.</blockquote>",
        kb([btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.clone_samples)
async def clone_sample(msg: Message, state: FSMContext):
    m = media_of(msg)
    if m is None or m[3] not in ("audio", "video"):
        await msg.answer("🎙 Пришлите голосовое или аудиофайл.")
        return
    data = await state.get_data()
    samples = (data.get("samples") or []) + [[m[0], m[1]]]
    samples = samples[:5]
    await state.update_data(samples=samples)
    await msg.answer(
        f"📥 Образцов: <b>{len(samples)}</b>/5. Можно прислать ещё или создать клон.",
        reply_markup=kb([btn("✅ Создать клон", "cl:go", style="success")], [btn("✖️ Отмена", "m:home", style="danger")]),
    )


@router.callback_query(F.data == "cl:go")
async def clone_ask_name(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.clone_name)
    await cq.answer()
    await cq.message.answer("✏️ Как назовём клон голоса?", reply_markup=cancel_kb())


@router.message(Await.clone_name, F.text)
async def clone_run(msg: Message, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    data = await state.get_data()
    name = msg.text.strip()[:40]
    v = None
    async with Loader(bot, msg.chat.id, "voice", "Клонирование голоса", eta=15) as ld:
        files = []
        for file_id, fname in data.get("samples", []):
            buf = io.BytesIO()
            await bot.download(file_id, destination=buf)
            files.append((fname, buf.getvalue()))
        if not files:
            raise ElevenError(400, "Нет образцов голоса")
        ld.stage("Обучаю модель на образцах")
        v = await api(store, cfg, msg.from_user.id).clone_voice(name, files)
    if v is None:
        return
    await store.set_setting(msg.from_user.id, "voice_id", v["voice_id"])
    await store.set_setting(msg.from_user.id, "voice_name", name)
    await store.track(msg.from_user.id, "clone", name)
    await state.set_state(None)
    await msg.answer(
        f"🧪 Клон <b>{esc(name)}</b> готов и выбран как текущий голос!" + SIGN,
        reply_markup=kb([btn("🗣 Проверить в озвучке", "f:tts", style="primary"), btn("🏠 Меню", "m:home")]),
        message_effect_id=EFFECT_PARTY,
    )
