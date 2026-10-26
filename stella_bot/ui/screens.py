"""Banner screens: every section is a photo card that is edited in place while navigating."""
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

BANNERS = Path(__file__).resolve().parent.parent / "assets" / "banners"
_file_ids: dict[str, str] = {}


def btn(text: str, data: str | None = None, *, url: str | None = None, style: str | None = None) -> InlineKeyboardButton:
    if url:
        return InlineKeyboardButton(text=text, url=url, style=style)
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def kb(*rows) -> InlineKeyboardMarkup:
    """kb([btn, btn], [btn]) — each argument is a row; a bare button becomes its own row."""
    return InlineKeyboardMarkup(inline_keyboard=[list(r) if isinstance(r, (list, tuple)) else [r] for r in rows])


def _photo(key: str):
    return _file_ids.get(key) or FSInputFile(BANNERS / f"{key}.jpg")


def _remember(key: str, msg: Message | bool):
    if isinstance(msg, Message) and msg.photo:
        _file_ids[key] = msg.photo[-1].file_id


async def show(target: Message | CallbackQuery, key: str, caption: str, markup: InlineKeyboardMarkup | None = None):
    """Shows a banner card: edits the callback's message if possible, otherwise sends a new one."""
    if isinstance(target, CallbackQuery):
        msg = target.message
        if msg is not None and msg.photo:
            try:
                res = await msg.edit_media(InputMediaPhoto(media=_photo(key), caption=caption), reply_markup=markup)
                _remember(key, res)
                return res
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return msg
        chat_id = target.from_user.id if msg is None else msg.chat.id
        bot = target.bot
    else:
        chat_id = target.chat.id
        bot = target.bot
    res = await bot.send_photo(chat_id, _photo(key), caption=caption, reply_markup=markup)
    _remember(key, res)
    return res
