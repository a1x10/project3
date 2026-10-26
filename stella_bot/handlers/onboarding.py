import asyncio
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Config
from handlers.common import Onboard, esc
from handlers.menu import send_menu
from storage import Storage
from ui.anim import EFFECT_HEART, EFFECT_PARTY, SPIN, bar, boot, safe_edit, typewrite
from ui.screens import btn, kb, show

router = Router(name="onboarding")

MAX_ATTEMPTS = 5
LOCK_SECONDS = 60

GATE_TEXT = (
    "🔐 <b>STELLS · ранний доступ</b>\n\n"
    "Введите ключ бета-тестирования проектов, который можно купить на сайте "
    "или у создателя, для получения раннего доступа к новейшим функциям ИИ.\n\n"
    "<blockquote>🎵 песни · 🎬 видео · 🗣 озвучка · 🤖 ИИ-агенты · 🧬 голоса и многое другое</blockquote>"
)


def gate_kb(cfg: Config):
    rows = [btn("🔑 Ввести ключ", "ob:key", style="primary")]
    links = []
    if cfg.shop_url:
        links.append(btn("🌐 Купить на сайте", url=cfg.shop_url))
    if cfg.creator:
        links.append(btn("👤 Создатель", url=f"https://t.me/{cfg.creator}"))
    return kb(rows, links) if links else kb(rows)


@router.message(CommandStart())
async def start(msg: Message, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    await state.clear()
    u = store.user(msg.from_user.id)
    if u["activated"] and u["name"]:
        await msg.answer(f"✦ С возвращением, <b>{esc(u['name'])}</b>!", message_effect_id=EFFECT_HEART)
        await asyncio.sleep(0.6)
        await send_menu(msg, store)
        return
    loader = await boot(bot, msg.chat.id)
    await show(msg, "gate", GATE_TEXT, gate_kb(cfg))
    try:
        await loader.delete()
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "ob:key")
async def ask_key(cq: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("locked_until", 0) > time.time():
        left = int(data["locked_until"] - time.time())
        await cq.answer(f"⏳ Слишком много попыток. Подождите {left} сек.", show_alert=True)
        return
    await state.set_state(Onboard.key)
    await cq.answer()
    await cq.message.answer("⌨️ <b>Введите ключ</b>\n<i>Просто отправьте его сообщением ниже 👇</i>")


@router.message(Onboard.key, F.text)
async def got_key(msg: Message, state: FSMContext):
    key = msg.text.strip()
    try:
        await msg.delete()  # keep the key out of the chat history
    except TelegramBadRequest:
        pass
    await state.update_data(pending_key=key)
    masked = "•" * len(key)
    await msg.answer(
        f"🔑 Ключ: <code>{masked}</code>  <tg-spoiler>{esc(key)}</tg-spoiler>\n\n<b>Подтвердить?</b>",
        reply_markup=kb([btn("✅ Подтвердить", "ob:confirm", style="success"), btn("✏️ Изменить", "ob:key")]),
    )


@router.callback_query(F.data == "ob:confirm")
async def confirm_key(cq: CallbackQuery, state: FSMContext, store: Storage, cfg: Config):
    data = await state.get_data()
    key = data.get("pending_key")
    if key is None:
        await cq.answer("Сначала введите ключ", show_alert=True)
        return
    await cq.answer()
    msg = cq.message
    steps = ["Шифрую запрос", "Сверяю подпись", "Проверяю доступ"]
    for i in range(9):
        p = (i + 1) / 10
        await safe_edit(
            msg,
            f"🛡 <b>Проверка ключа</b>  {SPIN[i % len(SPIN)]}\n\n"
            f"<i>{steps[min(i // 3, 2)]}…</i>\n<code>{bar(p)}</code> {int(p * 100)}%",
        )
        await asyncio.sleep(0.32)

    if key != cfg.beta_key:
        attempts = data.get("attempts", 0) + 1
        update = {"attempts": attempts, "pending_key": None}
        if attempts >= MAX_ATTEMPTS:
            update.update(attempts=0, locked_until=time.time() + LOCK_SECONDS)
        await state.update_data(**update)
        for frame in ("❌ 🔒 ❌", "🔒 ❌ 🔒", "❌ 🔒 ❌"):
            await safe_edit(msg, f"<b>{frame}</b>")
            await asyncio.sleep(0.25)
        left = MAX_ATTEMPTS - attempts
        tail = (
            f"Осталось попыток: <b>{left}</b>" if attempts < MAX_ATTEMPTS
            else f"Слишком много попыток — ввод заблокирован на {LOCK_SECONDS} сек."
        )
        rows = [btn("🔑 Ввести снова", "ob:key", style="primary")]
        links = [btn("🌐 Купить ключ", url=cfg.shop_url)] if cfg.shop_url else []
        await safe_edit(
            msg,
            f"⛔️ <b>Неверный ключ</b>\n\nКлюч можно купить на сайте или у создателя.\n{tail}",
            reply_markup=kb(rows, links) if links else kb(rows),
        )
        return

    await store.update(cq.from_user.id, activated=True)
    await state.set_data({})
    await safe_edit(msg, f"✅ <b>Ключ принят</b>\n<code>{bar(1)}</code> 100%\n\n<i>Добро пожаловать в STELLS β</i>")
    await cq.bot.send_message(msg.chat.id, "🎉", message_effect_id=EFFECT_PARTY)
    await asyncio.sleep(0.8)
    await show(cq, "stella", "✦ <b>Stella</b> · ИИ проекта STELLS")
    intro = await cq.bot.send_message(msg.chat.id, "▌")
    plain = (
        "Здравствуйте! Меня зовут Стелла — я ИИ, созданная в проекте STELLS. "
        "Как зовут вас? Напишите ваше имя внизу 👇"
    )
    final = (
        "👋 <b>Здравствуйте!</b>\n\n"
        "Меня зовут <b>Стелла</b> — я ИИ, созданная в проекте <b>STELLS</b> ✨\n\n"
        "Как зовут вас? <i>Напишите ваше имя внизу</i> 👇"
    )
    await typewrite(intro, plain, final)
    await state.set_state(Onboard.name)


@router.message(Onboard.name, F.text)
async def got_name(msg: Message, state: FSMContext, store: Storage):
    name = " ".join(msg.text.split())[:32]
    if not name or name.startswith("/"):
        await msg.answer("Напишите, пожалуйста, просто ваше имя 🙂")
        return
    await store.update(msg.from_user.id, name=name)
    await state.clear()
    m = await msg.answer("▌", message_effect_id=EFFECT_HEART)
    await typewrite(
        m,
        f"Приятно познакомиться, {name}!",
        f"💫 <b>Приятно познакомиться, {esc(name)}!</b>\n\n<i>Я подготовила для вас лабораторию STELLS…</i>",
        steps=4,
    )
    await asyncio.sleep(1.2)
    await send_menu(msg, store)
