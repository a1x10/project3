from __future__ import annotations

import asyncio
import itertools
import os
import random
import shutil
from typing import Any

import pytest

os.environ.setdefault("EVOLUTION_API_KEY", "test")

from bot.brain import Brain  # noqa: E402
from bot.config import Settings  # noqa: E402
from bot.db import DB  # noqa: E402
from bot.llm.base import LLMReply  # noqa: E402
from bot.stickers import StickerLibrary  # noqa: E402

GROUP = "120363000000000001@g.us"
BOT = "77000000001@s.whatsapp.net"
VASYA = "77011111111@s.whatsapp.net"
PETYA = "77022222222@s.whatsapp.net"
OWNER = "77099999999"


class FakeEvolution:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.calls: list[tuple[str, Any]] = []
        self._ids = itertools.count(1)
        self.media: bytes | None = None

    def _id(self) -> str:
        return f"BOTMSG{next(self._ids)}"

    async def send_text(self, number, text, *, delay_ms=0, quoted=None, mentioned=None, mentions_everyone=False):
        wa_id = self._id()
        self.sent.append({"type": "text", "to": number, "text": text, "quoted": quoted, "mentioned": mentioned,
                          "everyone": mentions_everyone, "id": wa_id})
        return wa_id

    async def send_sticker(self, number, sticker_b64, *, delay_ms=0):
        wa_id = self._id()
        self.sent.append({"type": "sticker", "to": number, "id": wa_id})
        return wa_id

    async def send_poll(self, number, question, options, *, multiple=False, delay_ms=0):
        wa_id = self._id()
        self.sent.append({"type": "poll", "to": number, "question": question, "options": options,
                          "multiple": multiple, "id": wa_id})
        return wa_id

    async def delete_message(self, key):
        self.sent.append({"type": "delete", "key": key})

    async def send_reaction(self, key, emoji):
        self.sent.append({"type": "reaction", "key": key, "emoji": emoji})

    async def send_presence(self, number, presence="composing", delay_ms=3000):
        self.calls.append(("presence", number))
        await asyncio.sleep(0.01)

    async def mark_read(self, keys):
        self.calls.append(("read", len(keys)))

    async def media_base64(self, key, message=None):
        return self.media

    async def group_subject(self, jid):
        return "Друзья"

    async def fetch_instances(self):
        return [{"name": "stella", "ownerJid": BOT, "connectionStatus": "open"}]

    async def create_instance(self):
        return {}

    async def set_webhook(self, url, secret):
        return {}

    async def connect(self, number=None):
        return {}

    async def connection_state(self):
        return "open"

    async def close(self):
        pass

    def texts(self) -> list[str]:
        return [m["text"] for m in self.sent if m["type"] == "text"]


class FakeLLM:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.queue: list[Any] = []

    async def ask(self, *, system, prompt, tools=(), model=None, max_turns=5):
        self.calls.append({"system": system, "prompt": prompt, "tools": {t.name: t for t in tools}, "model": model})
        item = self.queue.pop(0) if self.queue else "ок"
        if callable(item):
            item = await item({t.name: t for t in tools}, prompt)
        if isinstance(item, Exception):
            raise item
        return LLMReply(text=item, cost_usd=0.001)


def make_settings(tmp_path, **overrides) -> Settings:
    s = Settings()
    values = dict(
        database_url=f"sqlite:///{tmp_path}/bot.db",
        data_dir=str(tmp_path),
        stickers_dir=str(tmp_path / "stickers"),
        evolution_auto_setup=False,
        reply_delay_min=0,
        reply_delay_max=0,
        batch_window_min=0,
        batch_window_max=0,
        batch_max_wait=0,
        typing_chars_per_sec=0,
        typo_rate=0,
        rate_limit_per_min=0,
        chime_default="off",
        memory_extract_every=0,
        owner_phone=OWNER,
        webhook_secret="s3cret",
        llm_switch_at=None,
        initiative_per_week=0,
    )
    values.update(overrides)
    for k, v in values.items():
        setattr(s, k, v)
    return s


async def nosleep(_seconds: float) -> None:
    await asyncio.sleep(0)


@pytest.fixture(scope="session")
def starter_pack(tmp_path_factory):
    """Стартовые стикеры рисуются один раз на все тесты (Pillow не быстрый)."""
    root = tmp_path_factory.mktemp("pack")
    lib = StickerLibrary(None, str(root))  # type: ignore[arg-type]
    lib._draw_starter_pack()
    return root


@pytest.fixture
def settings(tmp_path, starter_pack):
    shutil.copytree(starter_pack, tmp_path / "stickers")
    return make_settings(tmp_path)


@pytest.fixture
async def brain(settings):
    b = Brain(settings, DB(settings.database_url), FakeEvolution(), FakeLLM(), rng=random.Random(1), sleep=nosleep)
    b.ambient_quiet = (0.0, 0.0)
    await b.start()
    await b.add_bot_jid(BOT)
    yield b
    await settle(b)
    await b.db.close()


async def settle(b: Brain, timeout: float = 5.0) -> None:
    """Дождаться, пока все фоновые задачи бота закончатся."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        await asyncio.sleep(0.01)
        busy = [t for t in b.tasks if not t.done()]
        busy += [r.task for r in b.runners.values() if r.task and not r.task.done()]
        if not busy:
            await asyncio.sleep(0.01)
            if not [t for t in b.tasks if not t.done()]:
                return
    raise AssertionError("бот не успокоился")


_n = itertools.count(1)


def upsert(text: str | None = None, *, chat: str = GROUP, sender: str = VASYA, name: str = "Вася",
           msg_id: str | None = None, from_me: bool = False, mentioned: list[str] | None = None,
           quoted: dict[str, Any] | None = None, message: dict[str, Any] | None = None,
           message_type: str = "conversation") -> dict[str, Any]:
    key: dict[str, Any] = {"remoteJid": chat, "fromMe": from_me, "id": msg_id or f"IN{next(_n)}"}
    if chat.endswith("@g.us"):
        key["participant"] = sender
    data: dict[str, Any] = {
        "key": key,
        "pushName": name,
        "message": message if message is not None else {"conversation": text},
        "messageType": message_type,
        "messageTimestamp": 1760000000,
        "source": "android",
    }
    ctx: dict[str, Any] = {}
    if mentioned:
        ctx["mentionedJid"] = mentioned
    if quoted:
        ctx.update(quoted)
    if ctx:
        data["contextInfo"] = ctx
    return {"event": "messages.upsert", "instance": "stella", "data": data, "sender": BOT}
