"""«Мой стиль»: из истории берутся только сообщения владельца, портрет попадает в запрос модели, удаляется кнопкой."""

import json
import random

from bot import my_style
from bot.my_style import MyStyle, _records, _text_of

from .conftest import VASYA, settle, upsert
from .test_admin import auth, login, panel, fast_login  # noqa: F401 — фикстуры панели


class FakeEvo:
    instance = "stella-mystyle"

    def __init__(self):
        self.calls, self.deleted = [], 0

    async def _call(self, method, path, json=None, params=None, timeout=None):
        self.calls.append((method, path, json))
        if path.startswith("/chat/findMessages"):
            recs = [{"key": {"fromMe": True}, "message": {"conversation": f"го катку {i} 😂 звони +7 701 555 44 33"}}
                    for i in range(40)]
            recs.append({"key": {"fromMe": False}, "message": {"conversation": "чужое сообщение"}})
            return {"messages": {"records": recs, "pages": 1}}
        return {}

    async def connection_state(self):
        return "open"

    async def connect(self, number=None):
        return {"base64": "iVBORw0KGgo="}

    async def delete_instance(self):
        self.deleted += 1


async def test_only_own_messages_profile_and_hint(brain, monkeypatch):
    monkeypatch.setattr(my_style, "STABLE_FOR", 0)
    monkeypatch.setattr(my_style.asyncio, "sleep", lambda *_: settle_sleep())
    ms = MyStyle(brain)
    ms._evo = FakeEvo()
    brain.llm.queue = ["пишет коротко, с маленькой буквы, много 😂, «го»"]
    out = await ms.start()
    assert out["qr"].startswith("data:image/png;base64,")
    await ms.task
    assert ms.state == "done", ms.detail
    data = await ms.load()
    assert data["count"] == 40 and all("чужое" not in s for s in data["samples"])
    assert all("555" not in s and "[номер]" in s for s in data["samples"])
    assert ms._evo.deleted >= 2  # хвосты до и сразу после — его WhatsApp отключён
    hint = await ms.hint(random.Random(1))
    assert "пишет коротко" in hint and "го катку" in hint
    brain.s.my_style_enabled = False
    assert await ms.hint(random.Random(1)) == ""
    await ms.forget()
    assert await ms.load() is None


async def settle_sleep():
    return None


def test_records_shapes():
    assert _records([{"a": 1}]) == ([{"a": 1}], 1)
    assert _records({"messages": {"records": [{"b": 2}], "pages": 3}}) == ([{"b": 2}], 3)
    assert _text_of({"message": {"extendedTextMessage": {"text": " привет "}}}) == "привет"


async def test_style_reaches_prompt_and_panel(panel, brain):  # noqa: F811
    await brain.db.kv_set(my_style.KV, json.dumps({"profile": "пишет капсом", "samples": ["ЖЕСТЬ"], "count": 50}))
    brain.llm.queue = ["ок"]
    await brain.handle_payload(upsert("стелла привет", chat=VASYA, sender=VASYA))
    await settle(brain)
    assert "пишет капсом" in brain.llm.calls[-1]["prompt"]
    h = auth((await login(panel)).json()["token"])
    r = (await panel.get("/admin/api/mystyle", headers=h)).json()
    assert r["profile"] == "пишет капсом" and r["count"] == 50
    assert (await panel.delete("/admin/api/mystyle", headers=h)).json()["ok"]
    assert (await panel.get("/admin/api/mystyle")).status_code == 401
