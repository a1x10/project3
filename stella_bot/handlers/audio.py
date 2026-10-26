"""Text to speech, dialogue, sound effects, voice changer, transcription and voice isolation."""
import re

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from config import Config
from handlers.common import SIGN, Await, after_kb, api, audio_file, download, esc, screen
from handlers.settings import MODEL_NAMES
from storage import Storage
from ui.anim import Loader
from ui.screens import btn, kb, show

router = Router(name="audio")


def tools_kb(extra=None):
    rows = [[btn("🎙 Сменить голос", "f:voices"), btn("⚙️ Настройки", "f:settings")]]
    if extra:
        rows.insert(0, extra)
    rows.append([btn("🏠 Меню", "m:home")])
    return kb(*rows)


# ── text to speech ───────────────────────────────────────────────────────
@router.callback_query(F.data == "f:tts")
async def tts_screen(cq: CallbackQuery, state: FSMContext, store: Storage):
    s = store.settings(cq.from_user.id)
    await state.set_state(Await.tts_text)
    await cq.answer()
    await show(
        cq,
        "tts",
        "🗣 <b>Озвучка текста</b>\n\n"
        f"Пришлите текст — я озвучу его голосом <b>{esc(s['voice_name'])}</b>.\n\n"
        f"🧠 Модель: <b>{MODEL_NAMES.get(s['tts_model'], s['tts_model'])}</b>\n"
        f"🎚 Стабильность {s['stability']:.2f} · Схожесть {s['similarity']:.2f} · Скорость {s['speed']:.2f}\n\n"
        "<blockquote>💡 В моделях v3/v4 работают теги эмоций: "
        "<code>[whispers]</code> <code>[laughs]</code> <code>[excited]</code> <code>[sighs]</code></blockquote>",
        tools_kb(),
    )


@router.message(Await.tts_text, F.text)
async def tts_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    text = msg.text.strip()[:5000]
    s = store.settings(msg.from_user.id)
    audio = None
    async with Loader(bot, msg.chat.id, "tts", "Озвучка", eta=6 + len(text) / 80):
        audio = await api(store, cfg, msg.from_user.id).tts(text, s["voice_id"], s["tts_model"], s)
    if audio is None:
        return
    await store.track(msg.from_user.id, "tts", text)
    await msg.answer_audio(
        audio_file(audio, text[:30]),
        title=text[:40],
        performer=f"{s['voice_name']} · STELLS",
        caption=f"🗣 <b>Готово!</b>\n<blockquote expandable>{esc(text[:800])}</blockquote>"
        "<i>Пришлите следующий текст или вернитесь в меню.</i>" + SIGN,
        reply_markup=after_kb("f:tts", "🗣 Новый текст"),
    )


# ── dialogue ─────────────────────────────────────────────────────────────
LINE = re.compile(r"^\s*([^:\n]{1,30}):\s*(.+)$")


@router.callback_query(F.data == "f:dialogue")
async def dialogue_screen(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.dialogue_text)
    await cq.answer()
    await show(
        cq,
        "dialogue",
        "🎭 <b>Диалоги</b>\n\nНапишите сцену — каждая реплика с новой строки в формате <code>Имя: текст</code>. "
        "Каждому персонажу я подберу свой голос.\n\n"
        "<blockquote>Аня: [excited] Ты слышал? У нас получилось!\n"
        "Макс: [whispers] Тише… пусть это пока будет секретом.\n"
        "Аня: [laughs] Поздно, я уже всем рассказала!</blockquote>",
        tools_kb(),
    )


@router.message(Await.dialogue_text, F.text)
async def dialogue_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    lines = [LINE.match(l) for l in msg.text.splitlines() if l.strip()]
    lines = [m for m in lines if m]
    if len(lines) < 2:
        await msg.answer("✍️ Нужно минимум две реплики в формате <code>Имя: текст</code>.")
        return
    uid = msg.from_user.id
    s = store.settings(uid)
    client = api(store, cfg, uid)
    speakers = list(dict.fromkeys(m.group(1).strip() for m in lines))[:10]
    cast = {speakers[0]: (s["voice_id"], s["voice_name"])}
    audio = None
    async with Loader(bot, msg.chat.id, "tts", "Диалог", eta=10 + len(msg.text) / 60) as ld:
        if len(speakers) > 1:
            ld.stage("Подбираю актёров")
            pool = [v for v in await client.voices(voice_type="default") if v["voice_id"] != s["voice_id"]]
            for sp, v in zip(speakers[1:], pool):
                cast[sp] = (v["voice_id"], v.get("name", "?"))
        ld.stage("Записываю сцену")
        inputs = [{"text": m.group(2), "voice_id": cast.get(m.group(1).strip(), cast[speakers[0]])[0]} for m in lines]
        model = "eleven_v4" if s["tts_model"] == "eleven_v4" else "eleven_v3"
        audio = await client.dialogue(inputs, model)
    if audio is None:
        return
    await store.track(uid, "dialogue", lines[0].group(2))
    roles = "\n".join(f"🎭 {esc(sp)} — <b>{esc(cast.get(sp, cast[speakers[0]])[1])}</b>" for sp in speakers)
    await msg.answer_audio(
        audio_file(audio, "dialogue"),
        title="Сцена",
        performer="STELLS Dialogue",
        caption=f"🎭 <b>Сцена готова!</b>\n\n{roles}" + SIGN,
        reply_markup=after_kb("f:dialogue", "🎭 Новая сцена"),
    )


# ── sound effects ────────────────────────────────────────────────────────
@router.callback_query(F.data == "f:sfx")
async def sfx_screen(cq: CallbackQuery, state: FSMContext, store: Storage):
    s = store.settings(cq.from_user.id)
    await state.set_state(Await.sfx_prompt)
    await cq.answer()
    dur = f"{s['sfx_duration']} сек" if s["sfx_duration"] else "авто"
    await show(
        cq,
        "sfx",
        "💥 <b>Звуковые эффекты</b>\n\nОпишите звук — и он появится.\n"
        f"⏱ Длительность: <b>{dur}</b>\n\n"
        "<blockquote>Примеры: «гром вдалеке и дождь по крыше», «лазерный выстрел в стиле 80-х», "
        "«толпа на стадионе ревёт после гола»</blockquote>",
        tools_kb(),
    )


@router.message(Await.sfx_prompt, F.text)
async def sfx_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    s = store.settings(msg.from_user.id)
    audio = None
    async with Loader(bot, msg.chat.id, "sfx", "Звуковой эффект", eta=8):
        audio = await api(store, cfg, msg.from_user.id).sfx(msg.text[:450], s["sfx_duration"], s["sfx_model"])
    if audio is None:
        return
    await store.track(msg.from_user.id, "sfx", msg.text)
    await msg.answer_audio(
        audio_file(audio, msg.text[:30]),
        title=msg.text[:40],
        performer="STELLS SFX",
        caption=f"💥 <b>{esc(msg.text[:200])}</b>" + SIGN,
        reply_markup=after_kb("f:sfx", "💥 Ещё звук"),
    )


# ── voice changer ────────────────────────────────────────────────────────
@router.callback_query(F.data == "f:sts")
async def sts_screen(cq: CallbackQuery, state: FSMContext, store: Storage):
    s = store.settings(cq.from_user.id)
    await state.set_state(Await.sts_audio)
    await cq.answer()
    await show(
        cq,
        "sts",
        "🎙 <b>Смена голоса</b>\n\nЗапишите голосовое или пришлите аудио — я сохраню интонации и эмоции, "
        f"но заменю тембр на <b>{esc(s['voice_name'])}</b>.",
        tools_kb(),
    )


@router.message(Await.sts_audio)
async def sts_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    got = await download(bot, msg, ("audio", "video"))
    if not got:
        return
    data, name, _ = got
    s = store.settings(msg.from_user.id)
    audio = None
    async with Loader(bot, msg.chat.id, "sts", "Смена голоса", eta=12):
        audio = await api(store, cfg, msg.from_user.id).sts(data, name, s["voice_id"])
    if audio is None:
        return
    await store.track(msg.from_user.id, "sts")
    await msg.answer_audio(
        audio_file(audio, "voice-changed"),
        title=f"Голос: {s['voice_name']}",
        performer="STELLS Voice Changer",
        caption=f"🎙 Теперь это говорит <b>{esc(s['voice_name'])}</b>" + SIGN,
        reply_markup=after_kb("f:sts"),
    )


# ── speech to text ───────────────────────────────────────────────────────
@router.callback_query(F.data == "f:stt")
@screen("f:stt")
async def stt_screen(cq: CallbackQuery, state: FSMContext, store: Storage):
    s = store.settings(cq.from_user.id)
    await state.set_state(Await.stt_media)
    await cq.answer()
    await show(
        cq,
        "stt",
        "📝 <b>Расшифровка речи</b>\n\nПришлите голосовое, аудио, видео или кружок — я превращу речь в текст "
        "на любом из 90+ языков.\n\n"
        f"👥 Разделение по спикерам: <b>{'вкл' if s['stt_diarize'] else 'выкл'}</b>",
        kb([btn("👥 Спикеры: переключить", "set:t:stt_diarize:f:stt")], [btn("🏠 Меню", "m:home")]),
    )


def _diarized(words: list) -> str:
    out, cur, buf = [], None, []
    for w in words:
        if w.get("type") == "spacing":
            buf.append(w["text"])
            continue
        sp = w.get("speaker_id")
        if sp != cur and buf:
            out.append(f"<b>{esc(str(cur).replace('speaker_', 'Спикер '))}:</b> {esc(''.join(buf).strip())}")
            buf = []
        cur = sp
        buf.append(w["text"])
    if buf:
        out.append(f"<b>{esc(str(cur).replace('speaker_', 'Спикер '))}:</b> {esc(''.join(buf).strip())}")
    return "\n".join(out)


@router.message(Await.stt_media)
async def stt_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    got = await download(bot, msg, ("audio", "video"))
    if not got:
        return
    data, name, _ = got
    s = store.settings(msg.from_user.id)
    res = None
    async with Loader(bot, msg.chat.id, "stt", "Расшифровка", eta=10):
        res = await api(store, cfg, msg.from_user.id).stt(data, name, s["stt_model"], s["stt_diarize"])
    if res is None:
        return
    text = res.get("text", "").strip() or "(речь не найдена)"
    await store.track(msg.from_user.id, "stt", text)
    body = _diarized(res.get("words", [])) if s["stt_diarize"] else esc(text)
    head = f"📝 <b>Расшифровка</b> · язык: <code>{esc(res.get('language_code', '?'))}</code>\n\n"
    if len(body) < 3500:
        await msg.answer(head + f"<blockquote expandable>{body}</blockquote>" + SIGN, reply_markup=after_kb("f:stt"))
    else:
        await msg.answer_document(
            BufferedInputFile(text.encode(), filename="transcript.txt"),
            caption=head + "Текст длинный — отправляю файлом." + SIGN,
            reply_markup=after_kb("f:stt"),
        )


# ── voice isolation ──────────────────────────────────────────────────────
@router.callback_query(F.data == "f:isolate")
async def isolate_screen(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.isolate_audio)
    await cq.answer()
    await show(
        cq,
        "isolate",
        "🎧 <b>Очистка звука</b>\n\nПришлите запись с шумом, музыкой или эхом — я оставлю только чистый голос.",
        kb([btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.isolate_audio)
async def isolate_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    got = await download(bot, msg, ("audio", "video"))
    if not got:
        return
    data, name, _ = got
    audio = None
    async with Loader(bot, msg.chat.id, "isolate", "Очистка звука", eta=12):
        audio = await api(store, cfg, msg.from_user.id).isolate(data, name)
    if audio is None:
        return
    await store.track(msg.from_user.id, "isolate")
    await msg.answer_audio(
        audio_file(audio, "clean-voice"),
        title="Чистый голос",
        performer="STELLS Isolator",
        caption="🎧 <b>Шум удалён</b> — остался только голос." + SIGN,
        reply_markup=after_kb("f:isolate"),
    )
