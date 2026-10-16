"""Мультики Стеллы: сценарий от модели → план по времени → кадры (cairo) → ролик (ffmpeg).

На уровне пакета — только лёгкие имена: бот импортирует bot.anim при старте, а cairo/numpy нужны лишь процессу
рендера. Всё тяжёлое импортируй из модулей напрямую (bot.anim.draw, bot.anim.compose и т. д.).
"""

from .model import AnimError, SpecError

__all__ = ["AnimError", "SpecError"]
