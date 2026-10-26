from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from handlers.common import reopen

from storage import Storage
from ui.screens import btn, kb, show

router = Router(name="settings")

MODEL_NAMES = {
    "eleven_multilingual_v2": "Multilingual v2",
    "eleven_v3": "Eleven v3 ✦",
    "eleven_v4": "Eleven v4 ✦✦",
    "eleven_flash_v2_5": "Flash v2.5 ⚡",
    "music_v1": "Music v1",
    "music_v2": "Music v2",
    "music_v2_5": "Music v2.5 ✦",
    "eleven_text_to_sound_v2": "SFX v2",
    "eleven_text_to_sound_v3": "SFX v3 ✦",
    "gemini-3.1-flash-image": "Nano Banana 2",
    "gemini-3-pro-image": "Nano Banana Pro",
    "gpt-image-2": "GPT Image 2",
    "bytedance-seedream-5-pro": "Seedream 5 Pro",
    "veo-3.1-fast-generate-001": "Veo 3.1 Fast",
    "veo-3.1-generate-001": "Veo 3.1",
    "bytedance-seedance-v2-fast": "Seedance 2 Fast",
    "bytedance-seedance-v2": "Seedance 2",
    "scribe_v2": "Scribe v2",
    "scribe_v1": "Scribe v1",
}

LANGS = {
    "en": "🇬🇧 English", "ru": "🇷🇺 Русский", "es": "🇪🇸 Español", "de": "🇩🇪 Deutsch", "fr": "🇫🇷 Français",
    "it": "🇮🇹 Italiano", "pt": "🇵🇹 Português", "ja": "🇯🇵 日本語", "zh": "🇨🇳 中文", "ko": "🇰🇷 한국어",
    "ar": "🇸🇦 العربية", "hi": "🇮🇳 हिन्दी", "tr": "🇹🇷 Türkçe", "pl": "🇵🇱 Polski", "uk": "🇺🇦 Українська",
}

CHOICES = {
    "tts_model": ["eleven_multilingual_v2", "eleven_v3", "eleven_v4", "eleven_flash_v2_5"],
    "music_model": ["music_v1", "music_v2", "music_v2_5"],
    "music_length": [0, 15, 30, 60, 120, 180],
    "sfx_model": ["eleven_text_to_sound_v2", "eleven_text_to_sound_v3"],
    "sfx_duration": [0, 2, 5, 10, 20, 30],
    "image_model": ["gemini-3.1-flash-image", "gemini-3-pro-image", "gpt-image-2", "bytedance-seedream-5-pro"],
    "image_aspect": ["1:1", "16:9", "9:16", "3:4", "4:3"],
    "video_model": [
        "veo-3.1-fast-generate-001", "veo-3.1-generate-001", "bytedance-seedance-v2-fast", "bytedance-seedance-v2",
    ],
    "video_duration": [4, 6, 8],
    "video_aspect": ["16:9", "9:16"],
    "video_resolution": ["720p", "1080p"],
    "dub_lang": list(LANGS),
    "stt_model": ["scribe_v2", "scribe_v1"],
}

# key: (min, max, step)
SLIDERS = {
    "stability": (0.0, 1.0, 0.1),
    "similarity": (0.0, 1.0, 0.1),
    "style": (0.0, 1.0, 0.1),
    "speed": (0.7, 1.2, 0.05),
}

TABS = {
    "voice": "🗣 Голос",
    "music": "🎵 Звук",
    "visual": "🎬 Видео",
    "other": "🌍 Прочее",
}


def fmt(key, v):
    if key in ("music_length", "sfx_duration"):
        return f"{v} сек" if v else "авто"
    if key == "video_duration":
        return f"{v} сек"
    if key == "dub_lang":
        return LANGS.get(v, v)
    if isinstance(v, bool):
        return "✅ вкл" if v else "▫️ выкл"
    return MODEL_NAMES.get(v, str(v))


def cycle(label, key, s, tab):
    return btn(f"{label}: {fmt(key, s[key])}", f"set:c:{key}:set:{tab}")


def toggle(label, key, s, tab):
    return btn(f"{label}: {fmt(key, s[key])}", f"set:t:{key}:set:{tab}", style="success" if s[key] else None)


def slider(label, key, s, tab):
    return [
        btn("➖", f"set:-:{key}:set:{tab}"),
        btn(f"{label} {s[key]:.2f}", "noop"),
        btn("➕", f"set:+:{key}:set:{tab}"),
    ]


def tab_rows(tab, s):
    if tab == "voice":
        return [
            [cycle("🧠 Модель", "tts_model", s, tab)],
            [btn(f"🎙 Голос: {s['voice_name']}", "f:voices")],
            slider("Стабильность", "stability", s, tab),
            slider("Схожесть", "similarity", s, tab),
            slider("Экспрессия", "style", s, tab),
            slider("Скорость", "speed", s, tab),
        ]
    if tab == "music":
        return [
            [cycle("🎼 Модель музыки", "music_model", s, tab)],
            [cycle("⏱ Длина трека", "music_length", s, tab)],
            [toggle("🎹 Только инструментал", "instrumental", s, tab)],
            [cycle("💥 Модель звуков", "sfx_model", s, tab)],
            [cycle("⏱ Длина звука", "sfx_duration", s, tab)],
        ]
    if tab == "visual":
        return [
            [cycle("🎬 Видео-модель", "video_model", s, tab)],
            [cycle("⏱", "video_duration", s, tab), cycle("📐", "video_aspect", s, tab)],
            [cycle("🖥 Качество", "video_resolution", s, tab), toggle("🔊 Звук", "video_audio", s, tab)],
            [cycle("🖼 Модель картинок", "image_model", s, tab)],
            [cycle("📐 Формат картинок", "image_aspect", s, tab)],
        ]
    return [
        [cycle("🌍 Язык дубляжа", "dub_lang", s, tab)],
        [cycle("📝 Модель расшифровки", "stt_model", s, tab)],
        [toggle("👥 Спикеры в расшифровке", "stt_diarize", s, tab)],
        [toggle("🔊 Голосовые ответы агентов", "agent_voice", s, tab)],
    ]


async def render(cq: CallbackQuery, store: Storage, tab: str):
    s = store.settings(cq.from_user.id)
    tabs = [btn(("● " if k == tab else "") + v, f"set:tab:{k}", style="primary" if k == tab else None) for k, v in TABS.items()]
    rows = [tabs[:2], tabs[2:], *tab_rows(tab, s), [btn("♻️ Сбросить всё", "set:reset", style="danger"), btn("🏠 Меню", "m:home")]]
    await show(
        cq,
        "settings",
        "⚙️ <b>Настройки генерации</b>\n\nНажимайте на параметр, чтобы переключить значение. "
        "Всё сохраняется автоматически ✨",
        kb(*rows),
    )


@router.callback_query(F.data == "f:settings")
async def settings_screen(cq: CallbackQuery, store: Storage):
    await cq.answer()
    await render(cq, store, "voice")


@router.callback_query(F.data.startswith("set:tab:"))
async def settings_tab(cq: CallbackQuery, store: Storage):
    await cq.answer()
    await render(cq, store, cq.data.split(":")[2])


@router.callback_query(F.data == "set:reset")
async def settings_reset(cq: CallbackQuery, store: Storage):
    await store.update(cq.from_user.id, settings={})
    await cq.answer("♻️ Настройки сброшены")
    await render(cq, store, "voice")


@router.callback_query(F.data.startswith("set:"))
async def settings_change(cq: CallbackQuery, state: FSMContext, store: Storage):
    _, op, key, *back = cq.data.split(":")
    uid = cq.from_user.id
    s = store.settings(uid)
    if op == "c" and key in CHOICES:
        opts = CHOICES[key]
        value = opts[(opts.index(s[key]) + 1) % len(opts)] if s[key] in opts else opts[0]
    elif op in "+-" and key in SLIDERS:
        lo, hi, step = SLIDERS[key]
        value = round(min(hi, max(lo, s[key] + (step if op == "+" else -step))), 2)
    elif op == "t" and isinstance(s.get(key), bool):
        value = not s[key]
    else:
        await cq.answer()
        return
    await store.set_setting(uid, key, value)
    target = ":".join(back)
    if target.startswith("f:"):
        # toggles embedded in feature screens re-open that screen
        await reopen(target, cq, state=state, store=store)
    else:
        await cq.answer(f"✓ {fmt(key, value)}")
        await render(cq, store, back[1] if len(back) > 1 else "voice")
