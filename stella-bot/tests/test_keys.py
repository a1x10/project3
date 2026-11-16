"""Ключи Groq / OpenRouter / Gemini / OpenAI из панели: несколько ключей по очереди, лимит — следующий ключ."""

import json

import httpx
import pytest

from bot.keys import STORE, KeyStore, mask
from bot.llm import LLMError, SwitchingLLM
from bot.llm.base import ToolSpec
from bot.llm.openai_compat import OpenAICompatLLM, check_key

from .conftest import make_settings
from .test_admin import auth, login, panel, fast_login  # noqa: F401 — фикстуры панели

KEY_A = "gsk_" + "a" * 40
KEY_B = "gsk_" + "b" * 40


def chat_reply(text=None, tool=None):
    msg = {"role": "assistant", "content": text}
    if tool:
        msg["tool_calls"] = [{"id": "c1", "type": "function",
                              "function": {"name": tool[0], "arguments": json.dumps(tool[1])}}]
    return {"choices": [{"message": msg}]}


async def test_keys_rotate_on_rate_limit_and_tools_work():
    store = KeyStore()
    a = await store.add("openrouter", KEY_A, "первый")
    await store.add("openrouter", KEY_B)
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        key = req.headers["authorization"].split()[1]
        body = json.loads(req.content)
        seen.append((key, body))
        if key == KEY_A:
            return httpx.Response(429, json={"error": {"message": "rate limit"}}, headers={"retry-after": "30"})
        if body["messages"][-1]["role"] == "tool":
            return httpx.Response(200, json=chat_reply("на улице +5"))
        return httpx.Response(200, json=chat_reply(tool=("weather", {"city": "Алматы"})))

    called = []

    async def weather(args):
        called.append(args)
        return "+5"

    llm = OpenAICompatLLM("openrouter", "claude-opus-5-5", store, transport=httpx.MockTransport(handler))
    reply = await llm.ask(system="ты Стелла", prompt="какая погода?",
                          tools=[ToolSpec("weather", "погода", {"type": "object", "properties": {}}, weather)])
    assert reply.text == "на улице +5" and called == [{"city": "Алматы"}]
    assert seen[0][1]["model"] == "~deepseek/deepseek-flash-latest"  # модель Anthropic подменена моделью провайдера
    assert a.id in store.cooldown and "лимит" in a.last_error
    # следующий запрос: ключ A на паузе — сразу B
    seen.clear()
    await llm.ask(system="s", prompt="ещё")
    assert seen[0][0] == KEY_B


async def test_all_keys_fail_and_no_keys():
    store = KeyStore()
    llm = OpenAICompatLLM("openrouter", "", store, transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(LLMError, match="нет ключей"):
        await llm.ask(system="s", prompt="p")
    await store.add("openrouter", KEY_A)
    with pytest.raises(LLMError, match="все ключи"):
        await llm.ask(system="s", prompt="p")
    assert "не принят" in store.keys[0].last_error


async def test_key_validation_and_mask():
    store = KeyStore()
    with pytest.raises(ValueError):
        await store.add("openrouter", "short")
    with pytest.raises(ValueError):
        await store.add("nope", KEY_A)
    await store.add("openrouter", KEY_A)
    with pytest.raises(ValueError, match="уже"):
        await store.add("openrouter", KEY_A)
    assert mask(KEY_A) == "gsk_…aaaa" and KEY_A not in json.dumps(store.public())


async def test_test_key_lists_models():
    ok, detail, models = await check_key("openrouter", KEY_A, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "~deepseek/deepseek-flash-latest"}]})))
    assert ok and models == ["llama-3.3-70b-versatile", "~deepseek/deepseek-flash-latest"] and "2" in detail
    ok, detail, _ = await check_key("openrouter", KEY_A, transport=httpx.MockTransport(
        lambda r: httpx.Response(401, json={"error": {"message": "Invalid API Key"}})))
    assert not ok and "Invalid API Key" in detail


def test_backend_for_providers(tmp_path):
    s = make_settings(tmp_path, llm_backend="openrouter", alt_model="llama-3.3-70b-versatile")
    assert s.backend_for(s.local_today()) == ("openrouter", "llama-3.3-70b-versatile")
    assert s.anthropic_off() and not s.model_off()
    s.llm_backend = "agent_sdk"
    assert not s.anthropic_off()
    llm = SwitchingLLM(make_settings(tmp_path, llm_backend="openrouter"))
    backend, kind, _ = llm._backend()
    assert kind == "openrouter" and backend.default_model == "~deepseek/deepseek-flash-latest"


async def test_panel_keys_flow(panel, brain, monkeypatch):  # noqa: F811
    async def fake_test(provider, key, transport=None):
        return True, "ключ работает, моделей: 1", ["llama-3.3-70b-versatile"]

    monkeypatch.setattr("bot.llm.openai_compat.check_key", fake_test)
    h = auth((await login(panel)).json()["token"])
    r = await panel.put("/admin/api/keys/active", json={"backend": "openrouter"}, headers=h)
    assert r.status_code == 400  # сначала ключ
    r = await panel.post("/admin/api/keys", json={"provider": "openrouter", "key": KEY_A, "label": "мой"}, headers=h)
    data = r.json()
    assert r.status_code == 200 and data["test"]["ok"] and data["key"]["masked"] == "gsk_…aaaa"
    assert KEY_A not in r.text
    listing = (await panel.get("/admin/api/keys", headers=h)).json()
    assert KEY_A not in json.dumps(listing) and len(listing["keys"]) == 1
    groq = next(p for p in listing["providers"] if p["id"] == "openrouter")
    assert "llama-3.3-70b-versatile" in groq["models"]
    kid = data["key"]["id"]
    assert (await panel.patch(f"/admin/api/keys/{kid}", json={"disabled": True}, headers=h)).json()["key"]["disabled"]
    await panel.patch(f"/admin/api/keys/{kid}", json={"disabled": False}, headers=h)
    r = await panel.put("/admin/api/keys/active", json={"backend": "openrouter", "model": "deepseek/deepseek-v4-flash"},
                        headers=h)
    assert r.json()["active"]["backend"] == "openrouter" and brain.s.llm_backend == "openrouter"
    assert brain.s.llm_backend_after == "openrouter"  # и после окончания бонусных кредитов — тоже Groq
    assert brain.s.alt_model == "deepseek/deepseek-v4-flash"
    # ключи переживают перезапуск
    STORE.keys = []
    await STORE.load()
    assert STORE.keys and STORE.keys[0].key == KEY_A
    assert (await panel.delete(f"/admin/api/keys/{kid}", headers=h)).json()["ok"]
    assert (await panel.delete(f"/admin/api/keys/{kid}", headers=h)).status_code == 404
    assert (await panel.get("/admin/api/keys")).status_code == 401


async def test_env_key_alias_and_old_backends(tmp_path):
    from bot.keys import ENV_KEYS

    ENV_KEYS["openrouter"] = "sk-or-v1-" + "x" * 40
    try:
        store = KeyStore()
        seen = []

        def handler(req):
            seen.append((json.loads(req.content)["model"], req.headers["authorization"]))
            return httpx.Response(200, json=chat_reply("привет"))

        llm = OpenAICompatLLM("openrouter", "deepseek/deepseek-flash-latest", store,
                              transport=httpx.MockTransport(handler))
        assert (await llm.ask(system="s", prompt="p")).text == "привет"
        assert seen[0] == ("~deepseek/deepseek-flash-latest", "Bearer sk-or-v1-" + "x" * 40)
        assert store.has("openrouter") and "x" * 40 not in json.dumps(store.public())
        assert OpenAICompatLLM("openrouter", "auto", store).default_model == "~deepseek/deepseek-flash-latest"
    finally:
        ENV_KEYS["openrouter"] = ""
    s = make_settings(tmp_path, llm_backend="custom", alt_model="")  # убранные провайдеры — теперь OpenRouter
    assert s.backend_for(s.local_today()) == ("openrouter", "")
