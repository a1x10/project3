import json
import random

import httpx
import pytest

from bot.brain import Brain
from bot.db import DB
from bot.evolution import Evolution

from .conftest import FakeLLM, make_settings, nosleep


def mock_evolution(fetch_mode: str):
    """Evolution, где инстанса ещё нет: fetchInstances отдаёт 404 или пустой список."""
    state = {"created": False, "webhook": None, "calls": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"].append(f"{request.method} {request.url.path}")
        assert request.headers["apikey"] == "k"
        if request.url.path == "/instance/fetchInstances":
            if state["created"]:
                return httpx.Response(200, json=[{"name": "stella", "connectionStatus": "close", "ownerJid": None},
                                                 {"name": "other", "ownerJid": "70000000000@s.whatsapp.net"}])
            if fetch_mode == "404":
                return httpx.Response(404, json={"status": 404, "error": "Not Found",
                                                 "response": {"message": ['Instance "stella" not found']}})
            return httpx.Response(200, json=[])
        if request.url.path == "/instance/create":
            body = json.loads(request.content)
            assert body["instanceName"] == "stella" and body["integration"] == "WHATSAPP-BAILEYS"
            state["created"] = True
            return httpx.Response(201, json={"instance": {"instanceName": "stella"}})
        if request.url.path == "/webhook/set/stella":
            state["webhook"] = json.loads(request.content)["webhook"]
            return httpx.Response(201, json={})
        return httpx.Response(404, json={})

    client = httpx.AsyncClient(base_url="http://evo", transport=httpx.MockTransport(handler),
                               headers={"apikey": "k"})
    return Evolution("http://evo", "k", "stella", client=client), state


@pytest.mark.parametrize("fetch_mode", ["404", "empty"])
async def test_ensure_instance_creates_missing_instance(tmp_path, fetch_mode):
    evo, state = mock_evolution(fetch_mode)
    s = make_settings(tmp_path)
    brain = Brain(s, DB(s.database_url), evo, FakeLLM(), rng=random.Random(1), sleep=nosleep)
    await brain.db.init()
    await brain.ensure_instance()
    assert state["created"] is True
    assert state["webhook"]["url"] == s.webhook_url
    assert state["webhook"]["headers"] == {"x-webhook-secret": "s3cret"}
    assert brain.connection_state == "close"
    assert "70000000000@s.whatsapp.net" not in brain.bot.jids  # чужой инстанс не считается ботом
    await brain.db.close()
    await evo.close()


async def test_pair_by_number_recreates_instance_and_shows_codes():
    from bot.setup import pair_by_number

    st = {"created_with": None, "deleted": [], "connects": 0, "webhook": False}
    codes = [None, "ABCD1234", "ABCD1234", "WXYZ9876"]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "DELETE":
            st["deleted"].append(path)
            return httpx.Response(200, json={})
        if path == "/instance/create":
            st["created_with"] = json.loads(request.content).get("number")
            return httpx.Response(201, json={})
        if path == "/webhook/set/stella":
            st["webhook"] = True
            return httpx.Response(201, json={})
        if path == "/instance/connectionState/stella":
            state = "open" if st["connects"] >= len(codes) else "connecting"
            return httpx.Response(200, json={"instance": {"instanceName": "stella", "state": state}})
        if path == "/instance/connect/stella":
            code = codes[st["connects"]]
            st["connects"] += 1
            return httpx.Response(200, json={"pairingCode": code, "code": "qr", "count": st["connects"]})
        return httpx.Response(404, json={})

    client = httpx.AsyncClient(base_url="http://evo", transport=httpx.MockTransport(handler))
    evo = Evolution("http://evo", "k", "stella", client=client)
    printed = []
    ok = await pair_by_number(evo, "77077568480", "http://bot:8000/webhook", "s", out=printed.append, sleep=nosleep)
    await evo.close()
    text = "\n".join(printed)
    assert ok
    assert st["created_with"] == "77077568480" and st["webhook"]
    assert st["deleted"] == ["/instance/logout/stella", "/instance/delete/stella"]
    assert "ABCD-1234" in text and "WXYZ-9876" in text and text.count("ABCD-1234") == 1
    assert "подключён" in text
