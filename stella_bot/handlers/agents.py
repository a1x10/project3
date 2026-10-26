"""ElevenLabs Agents: chat with Stella, create your own agents and talk to them."""
import asyncio
import hashlib
import io
import time

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import Config
from eleven import AgentChat
from handlers.common import SIGN, Await, api, audio_file, cancel_kb, esc, media_of
from storage import Storage
from ui.anim import EFFECT_PARTY, SPIN, Loader, safe_edit
from ui.screens import btn, kb, show

router = Router(name="agents")

STELLA_PROMPT = """Ты — Стелла, женский ИИ-ассистент, созданный в проекте STELLS.
Ты дружелюбная, остроумная и тёплая, говоришь живо и по делу, иногда с лёгким юмором и эмодзи.
Отвечай на языке собеседника (по умолчанию — по-русски). Обращайся к человеку по имени, если оно известно.
Ты можешь рассказать о возможностях бота STELLS: генерация песен, видео, изображений, озвучка текста,
диалоги, звуковые эффекты, смена и клонирование голоса, дизайн голосов, расшифровка речи, дубляж и ИИ-агенты.
Пиши компактно: обычно 1–4 предложения, без markdown-разметки."""

IDLE_TIMEOUT = 600
_sessions: dict[int, tuple[AgentChat, float]] = {}


async def close_session(uid: int):
    sess = _sessions.pop(uid, None)
    if sess:
        await sess[0].close()


async def reap_idle():
    """Background task: closes agent connections nobody used for a while."""
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        for uid, (_, last) in list(_sessions.items()):
            if now - last > IDLE_TIMEOUT:
                await close_session(uid)


async def stella_agent_id(store: Storage, cfg: Config, uid: int) -> str:
    client = api(store, cfg, uid)
    key = "stella_agent:" + hashlib.sha256(client.api_key.encode()).hexdigest()[:12]
    agent_id = store.get_global(key)
    if not agent_id:
        agent_id = await client.create_agent("Stella · STELLS", STELLA_PROMPT, "", "EXAVITQu4vr4xnSDxMaL")
        await store.set_global(key, agent_id)
    return agent_id


def chat_kb():
    return kb([btn("⏹ Завершить диалог", "ag:stop", style="danger"), btn("🏠 Меню", "m:home")])


@router.callback_query(F.data == "f:agents")
async def agents_screen(cq: CallbackQuery, state: FSMContext, store: Storage):
    await close_session(cq.from_user.id)
    await state.set_state(None)
    await cq.answer()
    n = len(store.user(cq.from_user.id)["agents"])
    await show(
        cq,
        "agents",
        "🤖 <b>ИИ-агенты</b>\n\nОбщайтесь со Стеллой или создайте собственного агента со своим характером, "
        "знаниями и голосом — и разговаривайте с ним текстом или голосовыми.\n\n"
        f"📂 Ваших агентов: <b>{n}</b>",
        kb(
            [btn("💬 Поговорить со Стеллой", "ag:stella", style="primary")],
            [btn("➕ Создать агента", "ag:new"), btn("📂 Мои агенты", "ag:list")],
            [btn("⚙️ Голосовые ответы", "set:tab:other"), btn("🏠 Меню", "m:home")],
        ),
    )


async def start_chat(cq: CallbackQuery, state: FSMContext, store: Storage, cfg: Config, bot: Bot,
                     agent_id: str | None, agent_name: str, greeting: str | None):
    uid = cq.from_user.id
    await close_session(uid)
    chat = None
    first = None
    async with Loader(bot, cq.message.chat.id, "agent", f"Соединяю: {agent_name}", eta=5) as ld:
        if agent_id is None:
            ld.stage("Пробуждаю Стеллу")
            agent_id = await stella_agent_id(store, cfg, uid)
        name = store.user(uid)["name"] or "друг"
        chat = AgentChat(api(store, cfg, uid), agent_id, f"Собеседника зовут {name}.")
        await chat.connect()
        if greeting is None:
            try:
                first = await chat.next_reply(timeout=12)
            except asyncio.TimeoutError:
                first = None  # the agent has no first message and waits for the user
    if chat is None or not chat.alive:
        return
    _sessions[uid] = (chat, time.monotonic())
    await state.set_state(Await.agent_chat)
    await state.update_data(agent_id=agent_id, agent_name=agent_name)
    text = greeting or first or "Привет! Я на связи."
    await cq.message.answer(
        f"🤖 <b>{esc(agent_name)}</b>\n\n{esc(text)}\n\n<i>Пишите сообщения или отправляйте голосовые 🎙</i>",
        reply_markup=chat_kb(),
    )


@router.callback_query(F.data == "ag:stella")
async def chat_stella(cq: CallbackQuery, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    await cq.answer()
    name = store.user(cq.from_user.id)["name"] or "друг"
    await start_chat(cq, state, store, cfg, bot, None, "Стелла",
                     f"Привет, {name}! ✨ Я Стелла. О чём поговорим? Могу помочь с идеей для песни, "
                     "видео или просто поболтать.")


@router.callback_query(F.data.startswith("ag:chat:"))
async def chat_custom(cq: CallbackQuery, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    agent_id = cq.data.split(":", 2)[2]
    agent = next((a for a in store.user(cq.from_user.id)["agents"] if a["id"] == agent_id), None)
    if agent is None:
        await cq.answer("Агент не найден", show_alert=True)
        return
    await cq.answer()
    await start_chat(cq, state, store, cfg, bot, agent_id, agent["name"], None)


@router.callback_query(F.data == "ag:stop")
async def chat_stop(cq: CallbackQuery, state: FSMContext, store: Storage):
    await agents_screen(cq, state, store)  # closes the session too


@router.message(Await.agent_chat)
async def chat_message(msg: Message, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    uid = msg.from_user.id
    data = await state.get_data()
    client = api(store, cfg, uid)
    text = msg.text
    if text is None:
        m = media_of(msg)
        if m is None or m[3] != "audio":
            await msg.answer("Я понимаю текст и голосовые 🙂")
            return
        buf = io.BytesIO()
        await bot.download(m[0], destination=buf)
        try:
            text = (await client.stt(buf.getvalue(), m[1], "scribe_v2", False)).get("text", "").strip()
        except Exception as e:
            await msg.answer(f"⚠️ Не расслышала: {esc(str(e))[:200]}")
            return
        if not text:
            await msg.answer("🤔 Не удалось разобрать речь, попробуйте ещё раз.")
            return
        await msg.reply(f"🎙 <i>{esc(text)}</i>")

    reply_msg = await msg.answer(f"<i>{esc(data.get('agent_name', 'Агент'))} печатает</i> {SPIN[0]}")
    sess = _sessions.get(uid)
    try:
        if sess is None or not sess[0].alive:
            agent_id = data.get("agent_id") or await stella_agent_id(store, cfg, uid)
            chat = AgentChat(client, agent_id, f"Собеседника зовут {store.user(uid)['name'] or 'друг'}.")
            await chat.connect()
        else:
            chat = sess[0]
        _sessions[uid] = (chat, time.monotonic())

        last_edit = 0.0

        async def on_delta(partial: str):
            nonlocal last_edit
            if time.monotonic() - last_edit > 0.9:
                last_edit = time.monotonic()
                await safe_edit(reply_msg, esc(partial) + " ▌")

        typing = asyncio.create_task(_typing(bot, msg.chat.id))
        try:
            await chat.send(text)
            answer = await chat.next_reply(on_delta)
        finally:
            typing.cancel()
    except Exception as e:
        await close_session(uid)
        await safe_edit(reply_msg, f"⚠️ Связь с агентом прервалась: <i>{esc(str(e))[:300]}</i>\nНапишите ещё раз — я переподключусь.",
                        reply_markup=chat_kb())
        return

    await safe_edit(reply_msg, f"{esc(answer)}", reply_markup=chat_kb())
    await store.track(uid, "agent_chat", text)
    if store.settings(uid)["agent_voice"]:
        s = store.settings(uid)
        try:
            audio = await client.tts(answer[:2500], s["voice_id"], "eleven_flash_v2_5", s)
            await msg.answer_audio(audio_file(audio, "reply"), title=data.get("agent_name", "Агент"), performer="STELLS Agents")
        except Exception:
            pass


async def _typing(bot: Bot, chat_id: int):
    while True:
        await bot.send_chat_action(chat_id, "typing")
        await asyncio.sleep(4.5)


# ── creating agents ──────────────────────────────────────────────────────
@router.callback_query(F.data == "ag:new")
async def new_agent(cq: CallbackQuery, state: FSMContext):
    await state.set_state(Await.agent_name)
    await cq.answer()
    await show(
        cq,
        "agents",
        "➕ <b>Новый агент · шаг 1/3</b>\n\nКак зовут вашего агента?",
        cancel_kb("f:agents"),
    )


@router.message(Await.agent_name, F.text)
async def new_agent_name(msg: Message, state: FSMContext):
    await state.update_data(new_name=msg.text.strip()[:40])
    await state.set_state(Await.agent_prompt)
    await msg.answer(
        "🧠 <b>Шаг 2/3 · Личность</b>\n\nОпишите характер, роль и знания агента. Например:\n"
        "<blockquote>«Ты — шеф-повар Марко из Неаполя. Темпераментный, обожаешь пасту, "
        "даёшь короткие рецепты и шутишь про ананасы на пицце.»</blockquote>",
        reply_markup=cancel_kb("f:agents"),
    )


@router.message(Await.agent_prompt, F.text)
async def new_agent_prompt(msg: Message, state: FSMContext):
    await state.update_data(new_prompt=msg.text.strip()[:6000])
    await state.set_state(Await.agent_first)
    await msg.answer(
        "👋 <b>Шаг 3/3 · Приветствие</b>\n\nС какой фразы агент начнёт разговор?",
        reply_markup=kb([btn("⏭ Пропустить", "ag:skipfirst")], [btn("✖️ Отмена", "f:agents", style="danger")]),
    )


async def create_agent(target: Message, uid: int, state: FSMContext, store: Storage, cfg: Config, bot: Bot, first: str):
    data = await state.get_data()
    s = store.settings(uid)
    name = data["new_name"]
    agent_id = None
    async with Loader(bot, target.chat.id, "agent", f"Создаю агента {name}", eta=6):
        agent_id = await api(store, cfg, uid).create_agent(
            name, data["new_prompt"] + "\nПиши компактно, без markdown-разметки.", first, s["voice_id"]
        )
    if agent_id is None:
        return
    await store.add_agent(uid, agent_id, name)
    await store.track(uid, "agent_create", name)
    await state.set_state(None)
    await target.answer(
        f"🎉 Агент <b>{esc(name)}</b> создан!\n🎙 Голос: {esc(s['voice_name'])}" + SIGN,
        reply_markup=kb([btn(f"💬 Начать чат с {name}", f"ag:chat:{agent_id}", style="primary")],
                        [btn("📂 Мои агенты", "ag:list"), btn("🏠 Меню", "m:home")]),
        message_effect_id=EFFECT_PARTY,
    )


@router.message(Await.agent_first, F.text)
async def new_agent_first(msg: Message, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    await create_agent(msg, msg.from_user.id, state, store, cfg, bot, msg.text.strip()[:500])


@router.callback_query(F.data == "ag:skipfirst")
async def new_agent_skip(cq: CallbackQuery, state: FSMContext, store: Storage, cfg: Config, bot: Bot):
    await cq.answer()
    await create_agent(cq.message, cq.from_user.id, state, store, cfg, bot, "")


@router.callback_query(F.data == "ag:list")
async def list_agents(cq: CallbackQuery, store: Storage):
    await cq.answer()
    await render_agents(cq, store)


async def render_agents(cq: CallbackQuery, store: Storage):
    agents = store.user(cq.from_user.id)["agents"]
    rows = [[btn(f"💬 {a['name']}", f"ag:chat:{a['id']}"), btn("🗑", f"ag:del:{a['id']}", style="danger")] for a in agents]
    rows.append([btn("➕ Создать агента", "ag:new", style="primary"), btn("⬅️ Назад", "f:agents")])
    await show(
        cq,
        "agents",
        "📂 <b>Мои агенты</b>\n\n" + ("Выберите агента для разговора." if agents else "Пока пусто — создайте первого агента!"),
        kb(*rows),
    )


@router.callback_query(F.data.startswith("ag:del:"))
async def delete_agent(cq: CallbackQuery, store: Storage, cfg: Config):
    agent_id = cq.data.split(":", 2)[2]
    try:
        await api(store, cfg, cq.from_user.id).delete_agent(agent_id)
    except Exception:
        pass  # already gone on the ElevenLabs side — still drop it locally
    await store.remove_agent(cq.from_user.id, agent_id)
    await cq.answer("🗑 Агент удалён")
    await render_agents(cq, store)
