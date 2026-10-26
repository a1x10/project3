import io
import zipfile

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InputMediaAudio, Message

from config import Config
from handlers.common import SIGN, Await, after_kb, api, audio_file, download, esc
from handlers.settings import MODEL_NAMES, fmt
from media import mux
from storage import Storage
from ui.anim import EFFECT_FIRE, Loader
from ui.screens import btn, kb, show

router = Router(name="music")


@router.callback_query(F.data == "f:music")
async def music_screen(cq: CallbackQuery, state: FSMContext, store: Storage):
    s = store.settings(cq.from_user.id)
    await state.set_state(None)
    await cq.answer()
    await show(
        cq,
        "music",
        "🎵 <b>Студия музыки</b>\n\n"
        "Создавайте полноценные песни с вокалом, саундтреки к видео и разбирайте треки на дорожки.\n\n"
        f"🎼 Модель: <b>{MODEL_NAMES[s['music_model']]}</b> · ⏱ {fmt('music_length', s['music_length'])}"
        f" · 🎹 {'инструментал' if s['instrumental'] else 'с вокалом'}",
        kb(
            [btn("🎼 Песня по описанию", "mu:prompt", style="primary")],
            [btn("🎞 Музыка к видео", "mu:v2m"), btn("🎚 Разделить на стемы", "mu:stems")],
            [btn("⚙️ Настройки звука", "set:tab:music"), btn("🏠 Меню", "m:home")],
        ),
    )


@router.callback_query(F.data == "mu:prompt")
async def prompt_screen(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.music_prompt)
    await cq.answer()
    await show(
        cq,
        "music",
        "🎼 <b>Песня по описанию</b>\n\nОпишите песню: жанр, настроение, инструменты, язык вокала — "
        "можно даже прислать свой текст куплета.\n\n"
        "<blockquote>«Летний синти-поп про ночной город, женский вокал на русском, припев про звёзды»\n\n"
        "«Эпичный оркестровый саундтрек для трейлера, хор, барабаны тайко»</blockquote>",
        kb([btn("⬅️ Назад", "f:music"), btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.music_prompt, F.text)
async def music_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    s = store.settings(msg.from_user.id)
    prompt = msg.text.strip()[:4000]
    track = None
    async with Loader(bot, msg.chat.id, "music", "Генерация песни", eta=35 + (s["music_length"] or 60) * 0.4):
        track = await api(store, cfg, msg.from_user.id).music(
            prompt, s["music_length"], s["music_model"], s["instrumental"]
        )
    if track is None:
        return
    await store.track(msg.from_user.id, "music", prompt)
    await msg.answer_audio(
        audio_file(track, prompt[:30]),
        title=prompt[:48],
        performer="Stella · STELLS Music",
        caption=f"🎵 <b>Ваш трек готов!</b>\n<blockquote expandable>{esc(prompt[:700])}</blockquote>" + SIGN,
        reply_markup=after_kb("mu:prompt", "🎼 Новая песня"),
        message_effect_id=EFFECT_FIRE,
    )


@router.callback_query(F.data == "mu:v2m")
async def v2m_screen(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.v2m_video)
    await cq.answer()
    await show(
        cq,
        "video",
        "🎞 <b>Музыка к видео</b>\n\nПришлите видео (до 20 МБ). В подписи можно описать желаемую музыку.\n"
        "ИИ посмотрит ролик, подберёт темп и настроение, добавит звуковые эффекты — и я наложу саундтрек на видео.",
        kb([btn("⬅️ Назад", "f:music"), btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.v2m_video)
async def v2m_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    got = await download(bot, msg, ("video",))
    if not got:
        return
    video, name, _ = got
    track = clip = None
    async with Loader(bot, msg.chat.id, "music", "Саундтрек к видео", eta=60) as ld:
        track = await api(store, cfg, msg.from_user.id).video_to_music(video, name, msg.caption or "")
        ld.stage("Накладываю музыку на видео")
        clip = await mux(video, track)
    if track is None:
        return
    await store.track(msg.from_user.id, "video_to_music", msg.caption or "")
    if clip:
        await msg.answer_video(
            BufferedInputFile(clip, "stells-soundtrack.mp4"), caption="🎞 <b>Видео с новым саундтреком</b>" + SIGN
        )
    await msg.answer_audio(
        audio_file(track, "soundtrack"),
        title="Саундтрек",
        performer="Stella · STELLS Music",
        caption="🎵 Отдельная дорожка саундтрека",
        reply_markup=after_kb("mu:v2m"),
    )


@router.callback_query(F.data == "mu:stems")
async def stems_screen(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.stems_audio)
    await cq.answer()
    await show(
        cq,
        "music",
        "🎚 <b>Разделение на стемы</b>\n\nПришлите песню — я разложу её на отдельные дорожки: "
        "вокал, барабаны, бас и остальные инструменты.",
        kb([btn("⬅️ Назад", "f:music"), btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.stems_audio)
async def stems_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    got = await download(bot, msg, ("audio",))
    if not got:
        return
    audio, name, _ = got
    archive = None
    async with Loader(bot, msg.chat.id, "music", "Разделение на стемы", eta=45):
        archive = await api(store, cfg, msg.from_user.id).separate_stems(audio, name)
    if archive is None:
        return
    await store.track(msg.from_user.id, "stems")
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
        stems = [(n, zf.read(n)) for n in zf.namelist() if not n.endswith("/")][:10]
    except zipfile.BadZipFile:
        stems = [("stems.mp3", archive)]
    caption = f"🎚 <b>Готово!</b> Дорожек: {len(stems)}" + SIGN
    group = [
        InputMediaAudio(
            media=BufferedInputFile(data, n.rsplit("/", 1)[-1]),
            title=n.rsplit("/", 1)[-1].rsplit(".", 1)[0].capitalize(),
            performer="STELLS Stems",
            caption=caption if i == len(stems) - 1 else None,
        )
        for i, (n, data) in enumerate(stems)
    ]
    await msg.answer_media_group(group)
    await msg.answer("Что дальше?", reply_markup=after_kb("mu:stems", "🎚 Другая песня"))
