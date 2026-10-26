"""Stella — the STELLS Telegram bot built on the ElevenLabs API."""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import load_config
from handlers import routers
from handlers.agents import reap_idle
from handlers.common import AccessMiddleware, close_clients
from storage import Storage


async def setup_profile(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="✦ Запуск / вход"),
        BotCommand(command="menu", description="🏠 Главное меню"),
        BotCommand(command="profile", description="👤 Профиль"),
    ])
    try:
        await bot.set_my_short_description("✦ Стелла — ИИ проекта STELLS: песни, видео, голоса и ИИ-агенты")
        await bot.set_my_description(
            "Привет! Я Стелла — ИИ, созданная в проекте STELLS ✨\n\n"
            "🎵 Пишу песни · 🎬 снимаю видео · 🖼 рисую · 🗣 озвучиваю · 🤖 создаю ИИ-агентов\n\n"
            "Для входа нужен ключ бета-тестирования. Нажмите «Старт»!"
        )
    except Exception:
        logging.warning("Не удалось обновить описание бота")


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    if not cfg.eleven_api_key:
        logging.warning("ELEVENLABS_API_KEY не задан — пользователи смогут добавить свой ключ в профиле")

    bot = Bot(cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage(), store=Storage(cfg.data_dir / "users.json"), cfg=cfg)
    dp.message.outer_middleware(AccessMiddleware())
    dp.callback_query.outer_middleware(AccessMiddleware())
    dp.include_routers(*routers)

    await setup_profile(bot)
    reaper = asyncio.create_task(reap_idle())
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        reaper.cancel()
        await close_clients()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
