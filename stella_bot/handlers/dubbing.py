import asyncio

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from config import Config
from eleven import ElevenError
from handlers.common import SIGN, Await, after_kb, api, audio_file, download, screen
from handlers.settings import LANGS
from media import mux, to_mp3
from storage import Storage
from ui.anim import EFFECT_FIRE, Loader
from ui.screens import btn, kb, show

router = Router(name="dubbing")

STAGES = {
    "queued": "В очереди",
    "preparing": "Расшифровываю оригинал",
    "ready": "Перевожу и озвучиваю",
    "processing": "Озвучиваю на новом языке",
}


@router.callback_query(F.data == "f:dub")
@screen("f:dub")
async def dub_screen(cq: CallbackQuery, state: FSMContext, store: Storage):
    s = store.settings(cq.from_user.id)
    await state.set_state(Await.dub_media)
    await cq.answer()
    await show(
        cq,
        "dub",
        "🌍 <b>Дубляж</b>\n\nПришлите видео или аудио (до 20 МБ) — я переведу речь и озвучу её на другом языке, "
        "сохранив голоса и интонации говорящих.\n\n"
        f"🎯 Язык перевода: <b>{LANGS[s['dub_lang']]}</b>",
        kb([btn("🔁 Сменить язык", "set:c:dub_lang:f:dub", style="primary")], [btn("🏠 Меню", "m:home")]),
    )


@router.message(Await.dub_media)
async def dub_run(msg: Message, store: Storage, cfg: Config, bot: Bot):
    got = await download(bot, msg, ("audio", "video"))
    if not got:
        return
    media, name, kind = got
    lang = store.settings(msg.from_user.id)["dub_lang"]
    client = api(store, cfg, msg.from_user.id)
    result = None
    async with Loader(bot, msg.chat.id, "dub", f"Дубляж → {LANGS[lang]}", eta=120) as ld:
        project = await client.dub_create(media, name, lang)
        pid = project["project_id"]
        lid = (project.get("language_ids") or [None])[0]
        for _ in range(180):
            await asyncio.sleep(10)
            if lid is None:
                p = await client.dub_project(pid)
                if p["status"] == "failed":
                    raise ElevenError(500, (p.get("error") or {}).get("error", "Проект не удался"))
                ld.stage(STAGES.get(p["status"], "Обрабатываю"))
                lid = (p.get("language_ids") or [None])[0]
                continue
            target = await client.dub_language(pid, lid)
            if target["status"] == "failed":
                raise ElevenError(500, (target.get("error") or {}).get("error", "Дубляж не удался"))
            if target["status"] in ("completed", "stale") and target.get("outputs"):
                break
            ld.stage(STAGES.get(target["status"], "Озвучиваю"))
        else:
            raise ElevenError(504, "Дубляж занял слишком много времени")
        ld.stage("Свожу финальную дорожку")
        outputs = target["outputs"]
        flac = await client.download(outputs["lossless_audio"])
        subs = await client.download(outputs["subtitles"]) if outputs.get("subtitles") else None
        video = await mux(media, flac, audio_ext="flac") if kind == "video" else None
        result = flac, subs, video
    if result is None:
        return
    flac, subs, video = result
    await store.track(msg.from_user.id, "dub", lang)
    caption = f"🌍 <b>Дубляж готов</b> · {LANGS[lang]}" + SIGN
    if video:
        await msg.answer_video(BufferedInputFile(video, "stells-dub.mp4"), caption=caption, message_effect_id=EFFECT_FIRE)
    else:
        mp3 = await to_mp3(flac, "flac")
        await msg.answer_audio(
            audio_file(mp3, f"dub-{lang}") if mp3 else audio_file(flac, f"dub-{lang}", "flac"),
            title=f"Дубляж ({lang})",
            performer="STELLS Dubbing",
            caption=caption,
            message_effect_id=EFFECT_FIRE,
        )
    if subs:
        await msg.answer_document(BufferedInputFile(subs, f"subtitles-{lang}.vtt"), caption="💬 Субтитры")
    await msg.answer("Что дальше?", reply_markup=after_kb("f:dub", "🌍 Ещё дубляж"))
