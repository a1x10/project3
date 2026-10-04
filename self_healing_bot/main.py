"""Точка входа: `python main.py`. Поднимает Telegram-бота и фоновый мониторинг приложения."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat

from agent import Agent
from config import ConfigError, load_settings
from git_patch import Patcher
from handlers import build_guest_router, build_router
from monitor import Monitor
from system import AppController
from telegram_ui import TelegramNotifier

COMMANDS = [
    BotCommand(command="status", description="Состояние приложения и сервера"),
    BotCommand(command="logs", description="Последние строки логов"),
    BotCommand(command="restart", description="Перезапустить приложение"),
    BotCommand(command="debug", description="ИИ-анализ логов"),
    BotCommand(command="pause", description="Приостановить мониторинг"),
    BotCommand(command="resume", description="Возобновить мониторинг"),
    BotCommand(command="cmd", description="Выполнить команду на сервере"),
    BotCommand(command="help", description="Справка"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings()
    except ConfigError as e:
        logging.error("Ошибка в настройках: %s", e)
        sys.exit(2)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    app = AppController(settings)
    agent = Agent(settings) if settings.ai_enabled else None
    monitor = Monitor(settings, app, agent, Patcher(settings, app), TelegramNotifier(bot, settings.alert_chat_id))

    dp = Dispatcher()
    dp.include_router(build_router(settings))
    dp.include_router(build_guest_router())

    async def on_startup(bot: Bot) -> None:
        for admin_id in settings.admin_ids:  # меню команд видят только админы
            try:
                await bot.set_my_commands(COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception as e:  # например, админ ещё ни разу не писал боту
                logging.warning("Не удалось установить меню команд для %s: %s", admin_id, e)
        await monitor.start()
        logging.info("Self-Healing Bot запущен, слежу за: %s", app.describe())

    async def on_shutdown() -> None:
        await monitor.stop()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    await dp.start_polling(bot, monitor=monitor, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
