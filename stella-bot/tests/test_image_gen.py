"""Картинки нейросетью через OpenRouter: запрос /images, ключи по очереди, инструмент есть только с ключом."""

import base64
import json

import httpx
import pytest

from bot import image_gen
from bot.keys import STORE, KeyStore
from bot.media_tools import build_media_tools
from bot.tools import ToolContext

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
KEY_A, KEY_B = "sk-or-v1-" + "a" * 40, "sk-or-v1-" + "b" * 40


async def test_generate_rotates_keys_and_returns_png():
    store = KeyStore()
    await store.add("openrouter", KEY_A)
    await store.add("openrouter", KEY_B)
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append((req.url.path, req.headers["authorization"].split()[1], body))
        if req.headers["authorization"].endswith("a" * 40):
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode(),
                                                   "media_type": "image/png"}], "usage": {"cost": 0.007}})

    data, mime, cost = await image_gen.generate("a cat in space", "wide", store, "recraft/recraft-v4.1-flash-v2",
                                                transport=httpx.MockTransport(handler))
    assert data == PNG and mime == "image/png" and cost == 0.007
    assert seen[-1][0] == "/api/v1/images" and seen[-1][2] == {"model": "recraft/recraft-v4.1-flash-v2",
                                                                "prompt": "a cat in space", "aspect_ratio": "16:9"}
    with pytest.raises(image_gen.ImageGenError, match="нет ключа"):
        await image_gen.generate("x", "square", KeyStore(), "m")


async def test_tool_only_with_openrouter_key(settings, brain):
    ctx = ToolContext(chat_id=1, sender=None, people_refs={}, is_admin=False)
    STORE.keys = []
    assert "draw_image" not in {t.name for t in build_media_tools(brain.db, settings, ctx)}
    await STORE.add("openrouter", KEY_A)
    try:
        assert "draw_image" in {t.name for t in build_media_tools(brain.db, settings, ctx)}
        settings.image_gen_enabled = False
        assert "draw_image" not in {t.name for t in build_media_tools(brain.db, settings, ctx)}
    finally:
        STORE.keys = []
