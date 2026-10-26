from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from handlers.agents import close_session
from handlers.common import esc
from storage import Storage
from ui.screens import btn, kb, show

router = Router(name="menu")

FEATURES = [
    ("🤖 ИИ-агенты", "f:agents"),
    ("🎵 Песни", "f:music"),
    ("🎬 Видео", "f:video"),
    ("🖼 Изображения", "f:image"),
    ("🗣 Озвучка", "f:tts"),
    ("🎭 Диалоги", "f:dialogue"),
    ("💥 Звуки", "f:sfx"),
    ("🎙 Смена голоса", "f:sts"),
    ("📝 Расшифровка", "f:stt"),
    ("🎧 Очистка звука", "f:isolate"),
    ("🧬 Дизайн голоса", "f:design"),
    ("🧪 Клон голоса", "f:clone"),
    ("🌍 Дубляж", "f:dub"),
    ("📚 Голоса", "f:voices"),
]


def menu_kb():
    rows = [[btn(*FEATURES[i]), btn(*FEATURES[i + 1])] for i in range(0, len(FEATURES), 2)]
    rows.append([btn("⚙️ Настройки", "f:settings"), btn("👤 Профиль", "f:profile", style="primary")])
    return kb(*rows)


def menu_caption(store: Storage, uid: int) -> str:
    name = store.user(uid)["name"] or "друг"
    s = store.settings(uid)
    return (
        f"✦ <b>{esc(name)}</b>, выберите, какую из функций вы хотите попробовать:\n\n"
        "<blockquote expandable>"
        "🤖 <b>ИИ-агенты</b> — чат со Стеллой, создание своих агентов\n"
        "🎵 <b>Песни</b> — трек по описанию, музыка к видео, стемы\n"
        "🎬 <b>Видео</b> — видео по тексту, оживление фото, говорящий аватар\n"
        "🖼 <b>Изображения</b> — генерация и редактирование\n"
        "🗣 <b>Озвучка</b> · 🎭 <b>Диалоги</b> · 💥 <b>Звуки</b>\n"
        "🎙 <b>Смена голоса</b> · 📝 <b>Расшифровка</b> · 🎧 <b>Очистка</b>\n"
        "🧬 <b>Дизайн</b> и 🧪 <b>клон голоса</b> · 🌍 <b>Дубляж</b>"
        "</blockquote>\n"
        f"🎙 Голос: <b>{esc(s['voice_name'])}</b>"
    )


async def send_menu(target: Message | CallbackQuery, store: Storage):
    uid = target.from_user.id
    await show(target, "menu", menu_caption(store, uid), menu_kb())


@router.callback_query(F.data == "m:home")
async def home(cq: CallbackQuery, state: FSMContext, store: Storage):
    await close_session(cq.from_user.id)
    await state.set_state(None)
    await cq.answer()
    await send_menu(cq, store)


@router.message(Command("menu"))
async def menu_cmd(msg: Message, state: FSMContext, store: Storage):
    await close_session(msg.from_user.id)
    await state.set_state(None)
    await send_menu(msg, store)


@router.callback_query(F.data == "noop")
async def noop(cq: CallbackQuery):
    await cq.answer()
