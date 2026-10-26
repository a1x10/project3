import asyncio
import time
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Config
from eleven import Eleven, ElevenError
from handlers.common import Await, api, cancel_kb, esc
from storage import Storage
from ui.anim import SPIN, bar, safe_edit
from ui.screens import btn, kb, show

router = Router(name="profile")

FEATURE_RU = {
    "tts": "🗣 Озвучка", "dialogue": "🎭 Диалоги", "sfx": "💥 Звуки", "sts": "🎙 Смена голоса",
    "stt": "📝 Расшифровка", "isolate": "🎧 Очистка", "music": "🎵 Песни", "video_to_music": "🎞 Музыка к видео",
    "stems": "🎚 Стемы", "video": "🎬 Видео", "video_photo": "🖼 Оживление фото", "avatar": "🗣 Аватар",
    "image": "🖼 Изображения", "design": "🧬 Дизайн голоса", "clone": "🧪 Клон голоса", "dub": "🌍 Дубляж",
    "agent_chat": "🤖 Чат с агентом", "agent_create": "➕ Новый агент",
}


@router.callback_query(F.data == "f:profile")
async def profile_lock(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.profile_key)
    await cq.answer()
    await show(
        cq,
        "gate",
        "🔐 <b>Вход в профиль</b>\n\nДля защиты аккаунта введите ключ бета-тестирования — "
        "тот же, что при первом запуске.",
        cancel_kb(),
    )


@router.message(Await.profile_key, F.text)
async def profile_unlock(msg: Message, state: FSMContext, store: Storage, cfg: Config):
    key = msg.text.strip()
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass
    check = await msg.answer(f"🛡 Проверяю ключ {SPIN[0]}")
    for i in range(1, 5):
        await asyncio.sleep(0.25)
        await safe_edit(check, f"🛡 Проверяю ключ {SPIN[i]}\n<code>{bar(i / 4)}</code>")
    if key != cfg.beta_key:
        await safe_edit(
            check,
            "⛔️ <b>Неверный ключ</b> — доступ к профилю закрыт.\nПопробуйте ещё раз: просто отправьте ключ.",
            reply_markup=cancel_kb(),
        )
        return
    await state.set_state(None)
    try:
        await check.delete()
    except TelegramBadRequest:
        pass
    await render_profile(msg, store, cfg)


async def render_profile(target: Message | CallbackQuery, store: Storage, cfg: Config):
    uid = target.from_user.id
    u = store.user(uid)
    s = store.settings(uid)
    days = max(1, (int(time.time()) - u["joined"]) // 86400 + 1)
    total = sum(u["stats"].values())
    top = sorted(u["stats"].items(), key=lambda kv: -kv[1])[:3]
    top_txt = "\n".join(f"   {FEATURE_RU.get(k, k)} — <b>{v}</b>" for k, v in top) or "   пока ничего — самое время начать ✨"

    sub_txt = ""
    try:
        sub = await api(store, cfg, uid).subscription()
        used, limit = sub.get("character_count", 0), sub.get("character_limit", 0) or 1
        sub_txt = (
            f"\n💳 <b>ElevenLabs</b> · тариф <code>{esc(sub.get('tier', '?'))}</code>\n"
            f"<code>{bar(min(1, used / limit))}</code> {used:,} / {limit:,} кредитов\n".replace(",", " ")
        )
    except Exception:
        sub_txt = "\n💳 <i>Данные ElevenLabs недоступны</i>\n"

    own_key = "свой ключ ✅" if u.get("api_key") else "ключ проекта STELLS"
    caption = (
        f"👤 <b>{esc(u['name'] or 'Без имени')}</b>\n"
        f"🎫 Статус: <b>β-тестер STELLS</b> ✦\n"
        f"🆔 <code>{uid}</code>\n"
        f"📅 С нами: {datetime.fromtimestamp(u['joined']).strftime('%d.%m.%Y')} · {days} дн.\n"
        f"🎙 Голос: <b>{esc(s['voice_name'])}</b>\n"
        f"🔌 API: {own_key}\n"
        f"{sub_txt}\n"
        f"📊 <b>Генераций: {total}</b>\n{top_txt}"
    )
    await show(
        target,
        "profile",
        caption,
        kb(
            [btn("✏️ Изменить имя", "pr:name"), btn("🗂 История", "pr:history")],
            [btn("🔑 Свой API-ключ ElevenLabs", "pr:apikey")],
            [btn("🚪 Выйти из бета-доступа", "pr:logout", style="danger")],
            [btn("🏠 Меню", "m:home", style="primary")],
        ),
    )


@router.callback_query(F.data == "pr:back")
async def profile_back(cq: CallbackQuery, store: Storage, cfg: Config):
    await cq.answer()
    await render_profile(cq, store, cfg)


@router.callback_query(F.data == "pr:history")
async def history(cq: CallbackQuery, store: Storage):
    await cq.answer()
    items = store.user(cq.from_user.id)["history"][:12]
    lines = [
        f"<code>{datetime.fromtimestamp(h['t']).strftime('%d.%m %H:%M')}</code> {FEATURE_RU.get(h['f'], h['f'])}"
        + (f" — <i>{esc(h['n'])}</i>" if h.get("n") else "")
        for h in items
    ]
    await show(
        cq,
        "profile",
        "🗂 <b>История генераций</b>\n\n" + ("\n".join(lines) if lines else "<i>Пока пусто</i>"),
        kb([btn("⬅️ В профиль", "pr:back"), btn("🏠 Меню", "m:home")]),
    )


@router.callback_query(F.data == "pr:name")
async def ask_name(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.profile_name)
    await cq.answer()
    await cq.message.answer("✏️ Как мне вас называть?", reply_markup=cancel_kb("pr:back"))


@router.message(Await.profile_name, F.text)
async def set_name(msg: Message, state: FSMContext, store: Storage, cfg: Config):
    name = " ".join(msg.text.split())[:32]
    await store.update(msg.from_user.id, name=name)
    await state.set_state(None)
    await msg.answer(f"💫 Буду звать вас <b>{esc(name)}</b>!")
    await render_profile(msg, store, cfg)


@router.callback_query(F.data == "pr:apikey")
async def ask_apikey(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.profile_apikey)
    await cq.answer()
    await cq.message.answer(
        "🔑 Пришлите свой API-ключ ElevenLabs (elevenlabs.io → Developers → API Keys).\n"
        "Сообщение с ключом я сразу удалю. Отправьте <code>-</code>, чтобы вернуться к ключу проекта.",
        reply_markup=cancel_kb("pr:back"),
    )


@router.message(Await.profile_apikey, F.text)
async def set_apikey(msg: Message, state: FSMContext, store: Storage, cfg: Config):
    key = msg.text.strip()
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass
    if key == "-":
        await store.update(msg.from_user.id, api_key=None)
        await state.set_state(None)
        await msg.answer("↩️ Снова используется ключ проекта STELLS.")
        await render_profile(msg, store, cfg)
        return
    probe = Eleven(key)
    try:
        sub = await probe.subscription()
    except ElevenError as e:
        await msg.answer(f"⛔️ Ключ не подошёл: <i>{esc(e.message)[:200]}</i>", reply_markup=cancel_kb("pr:back"))
        return
    finally:
        await probe.close()
    await store.update(msg.from_user.id, api_key=key)
    await state.set_state(None)
    await msg.answer(f"✅ Ключ подключён! Тариф: <b>{esc(sub.get('tier', '?'))}</b>")
    await render_profile(msg, store, cfg)


@router.callback_query(F.data == "pr:logout")
async def logout_confirm(cq: CallbackQuery):
    await cq.answer()
    await cq.message.answer(
        "🚪 Выйти из бета-доступа? Чтобы вернуться, понадобится снова ввести ключ.",
        reply_markup=kb([btn("Да, выйти", "pr:logout!", style="danger"), btn("Остаться", "pr:back", style="success")]),
    )


@router.callback_query(F.data == "pr:logout!")
async def logout(cq: CallbackQuery, state: FSMContext, store: Storage):
    await store.update(cq.from_user.id, activated=False)
    await state.clear()
    await cq.answer()
    await safe_edit(cq.message, "👋 Вы вышли из STELLS β. Нажмите /start, чтобы войти снова.")


@router.message(Command("profile"))
async def profile_cmd(msg: Message, state: FSMContext):
    await state.set_state(Await.profile_key)
    await msg.answer("🔐 Введите ключ бета-тестирования для входа в профиль:", reply_markup=cancel_kb())

