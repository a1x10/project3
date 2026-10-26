import html
import inspect
import io
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message, TelegramObject

from config import Config
from eleven import Eleven
from storage import Storage
from ui.screens import btn, kb

MAX_DOWNLOAD = 20 * 1024 * 1024  # Bot API getFile limit

_clients: dict[str, Eleven] = {}


def api(store: Storage, cfg: Config, uid: int) -> Eleven:
    key = store.user(uid).get("api_key") or cfg.eleven_api_key
    if key not in _clients:
        _clients[key] = Eleven(key)
    return _clients[key]


async def close_clients():
    for c in _clients.values():
        await c.close()


class Onboard(StatesGroup):
    key = State()
    name = State()


class Await(StatesGroup):
    tts_text = State()
    dialogue_text = State()
    music_prompt = State()
    v2m_video = State()
    stems_audio = State()
    video_prompt = State()
    video_photo = State()
    video_photo_prompt = State()
    avatar_photo = State()
    avatar_text = State()
    image_prompt = State()
    image_edit_photo = State()
    image_edit_prompt = State()
    sfx_prompt = State()
    sts_audio = State()
    stt_media = State()
    isolate_audio = State()
    design_desc = State()
    design_name = State()
    clone_name = State()
    clone_samples = State()
    dub_media = State()
    agent_name = State()
    agent_prompt = State()
    agent_first = State()
    agent_chat = State()
    voice_search = State()
    profile_key = State()
    profile_name = State()
    profile_apikey = State()


class AccessMiddleware(BaseMiddleware):
    """Lets only activated beta testers past onboarding."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        store: Storage = data["store"]
        user = data.get("event_from_user")
        if user is None or store.user(user.id)["activated"]:
            return await handler(event, data)
        state: FSMContext = data["state"]
        current = await state.get_state()
        if isinstance(event, Message) and (
            (event.text or "").startswith("/start") or current in (Onboard.key.state, Onboard.name.state)
        ):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and (event.data or "").startswith("ob:"):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer("🔒 Сначала активируйте ключ доступа — /start", show_alert=True)
        else:
            await event.answer("🔒 Доступ закрыт. Нажмите /start, чтобы ввести ключ бета-тестирования.")


def esc(s: str) -> str:
    return html.escape(s or "")


def after_kb(again: str, label: str = "🔁 Ещё раз"):
    return kb([btn(label, again, style="primary"), btn("🏠 Меню", "m:home")])


def cancel_kb(back: str = "m:home"):
    return kb([btn("✖️ Отмена", back, style="danger")])


def media_of(msg: Message):
    """Returns (file_id, filename, size, kind) for any media message, or None."""
    if msg.voice:
        return msg.voice.file_id, "voice.ogg", msg.voice.file_size, "audio"
    if msg.audio:
        return msg.audio.file_id, msg.audio.file_name or "audio.mp3", msg.audio.file_size, "audio"
    if msg.video:
        return msg.video.file_id, msg.video.file_name or "video.mp4", msg.video.file_size, "video"
    if msg.video_note:
        return msg.video_note.file_id, "circle.mp4", msg.video_note.file_size, "video"
    if msg.photo:
        p = msg.photo[-1]
        return p.file_id, "photo.jpg", p.file_size, "photo"
    if msg.document:
        mime = msg.document.mime_type or ""
        kind = "video" if mime.startswith("video") else "photo" if mime.startswith("image") else "audio"
        return msg.document.file_id, msg.document.file_name or "file", msg.document.file_size, kind
    return None


async def download(bot: Bot, msg: Message, kinds: tuple[str, ...]) -> tuple[bytes, str, str] | None:
    """Downloads the media of msg if it is one of kinds; replies with a hint otherwise."""
    m = media_of(msg)
    if m is None or m[3] not in kinds:
        names = {"audio": "аудио или голосовое", "video": "видео", "photo": "фото"}
        await msg.answer("📎 Пришлите, пожалуйста, " + " или ".join(names[k] for k in kinds) + ".")
        return None
    file_id, name, size, kind = m
    if size and size > MAX_DOWNLOAD:
        await msg.answer("📦 Файл больше 20 МБ — Telegram не даёт ботам скачивать такие. Сожмите его и пришлите снова.")
        return None
    buf = io.BytesIO()
    await bot.download(file_id, destination=buf)
    return buf.getvalue(), name, kind


def audio_file(data: bytes, title: str, ext: str = "mp3") -> BufferedInputFile:
    safe = "".join(c for c in title if c.isalnum() or c in " _-")[:40].strip() or "stells"
    return BufferedInputFile(data, filename=f"{safe}.{ext}")


SIGN = "\n\n<i>✦ создано в STELLS</i>"


_screens: dict[str, Callable] = {}


def screen(data: str):
    """Registers a feature screen so it can be re-opened after an inline toggle."""

    def deco(fn):
        _screens[data] = fn
        return fn

    return deco


async def reopen(data: str, cq: CallbackQuery, **deps):
    fn = _screens.get(data)
    if fn is None:
        return
    params = inspect.signature(fn).parameters
    await fn(cq, **{k: v for k, v in deps.items() if k in params})
