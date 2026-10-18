from datetime import date
from types import SimpleNamespace as NS

import pytest

from bot.llm import SwitchingLLM
from bot.llm.base import LLMRefusal, LLMReply, ToolSpec
from bot.llm.messages_api import MessagesApiLLM

from .conftest import make_settings


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def usage():
    return NS(input_tokens=1000, output_tokens=100, cache_read_input_tokens=0, cache_creation_input_tokens=0)


async def test_messages_api_tool_loop():
    calls = []

    async def remember(args):
        calls.append(args)
        return "запомнила"

    tool = ToolSpec("remember", "d", {"type": "object", "properties": {}}, remember)
    first = NS(stop_reason="tool_use", usage=usage(), stop_details=None, content=[
        NS(type="thinking", thinking=""),
        NS(type="tool_use", id="t1", name="remember", input={"person": "я", "fact": "любит чай"}),
    ])
    second = NS(stop_reason="end_turn", usage=usage(), stop_details=None, content=[NS(type="text", text="ок, запомнила")])
    fake = FakeMessages([first, second])
    client = NS(messages=fake, beta=NS(messages=fake))
    llm = MessagesApiLLM("claude-haiku-5-5", effort="low", client=client)
    reply = await llm.ask(system="sys", prompt="hi", tools=[tool])
    assert reply.text == "ок, запомнила" and calls == [{"person": "я", "fact": "любит чай"}]
    assert reply.cost_usd > 0
    req = fake.requests[1]
    assert req["model"] == "claude-haiku-5-5" and "fallbacks" not in req
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert req["output_config"] == {"effort": "low"}
    assert req["messages"][-1]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": "запомнила"}


async def test_messages_api_sonnet_uses_server_fallback_and_refusal_raises():
    refused = NS(stop_reason="refusal", usage=usage(), stop_details=NS(category="cyber"), content=[])
    fake = FakeMessages([refused])
    client = NS(messages=FakeMessages([]), beta=NS(messages=fake))
    llm = MessagesApiLLM("claude-sonnet-5-5", client=client)
    with pytest.raises(LLMRefusal):
        await llm.ask(system="s", prompt="p")
    assert fake.requests[0]["fallbacks"] == "default"
    assert fake.requests[0]["betas"] == ["server-side-fallback-2026-07-01"]


async def test_switching_llm_changes_backend_on_date(tmp_path):
    s = make_settings(tmp_path, llm_backend="agent_sdk", llm_model="claude-sonnet-5-5",
                      llm_switch_at=date(2026, 10, 23), llm_backend_after="messages_api",
                      llm_model_after="claude-haiku-5-5")
    made = []

    class Dummy:
        def __init__(self, kind, model):
            self.kind, self.model = kind, model

        async def ask(self, **kw):
            return LLMReply(text=f"{self.kind}:{kw['model']}")

    def factory(kind, model, settings):
        made.append(kind)
        return Dummy(kind, model)

    today = [date(2026, 10, 22)]
    llm = SwitchingLLM(s, today=lambda: today[0], factory=factory)
    assert (await llm.ask(system="", prompt="")).text == "agent_sdk:claude-sonnet-5-5"
    today[0] = date(2026, 10, 23)
    assert (await llm.ask(system="", prompt="")).text == "messages_api:claude-haiku-5-5"
    assert made == ["agent_sdk", "messages_api"]


def test_agent_sdk_only_web_search_from_builtins(tmp_path):
    from bot.llm.agent_sdk import AgentSdkLLM

    async def h(args):
        return "ok"

    tool = ToolSpec("remember", "d", {"type": "object", "properties": {}}, h)
    llm = AgentSdkLLM("claude-opus-5-5", sandbox_dir=str(tmp_path / "sb"), web_search=True)
    opts = llm._options("sys", [tool], "claude-opus-5-5", 5)
    assert opts.tools == ["WebSearch"] and "WebSearch" in opts.allowed_tools
    assert "WebSearch" not in opts.disallowed_tools and "Bash" in opts.disallowed_tools
    assert "WebFetch" in opts.disallowed_tools
    assert llm._options("sys", [], "m", 1).tools == []  # фоновой памяти поиск не нужен
    off = AgentSdkLLM("claude-opus-5-5", sandbox_dir=str(tmp_path / "sb"), web_search=False)
    assert off._options("sys", [tool], "m", 5).tools == []


async def test_switching_llm_rebuilds_when_settings_change(tmp_path):
    s = make_settings(tmp_path, llm_backend="agent_sdk", llm_model="claude-opus-5-5")
    made = []

    class Dummy:
        def __init__(self, kind, model):
            self.model = model

        async def ask(self, **kw):
            return LLMReply(text=kw["model"])

    def factory(kind, model, settings):
        made.append((model, settings.llm_effort))
        return Dummy(kind, model)

    llm = SwitchingLLM(s, today=lambda: date(2026, 10, 16), factory=factory)
    assert (await llm.ask(system="", prompt="")).text == "claude-opus-5-5"
    s.llm_model, s.llm_effort = "claude-sonnet-5-5", "medium"  # поменяли в панели
    assert (await llm.ask(system="", prompt="")).text == "claude-sonnet-5-5"
    assert made == [("claude-opus-5-5", "high"), ("claude-sonnet-5-5", "medium")]


async def test_memory_runs_on_its_own_model_and_effort(tmp_path):
    """Память о людях — Sonnet на effort medium, хотя чат — Opus на high."""
    s = make_settings(tmp_path, llm_backend="messages_api", llm_model="claude-opus-5-5")
    assert (s.llm_memory_model, s.llm_memory_effort, s.llm_effort) == ("claude-sonnet-5-5", "medium", "high")
    done = NS(stop_reason="end_turn", usage=usage(), stop_details=None, content=[NS(type="text", text="{}")])
    fake = FakeMessages([done, done])
    llm = MessagesApiLLM("claude-opus-5-5", effort="high", client=NS(messages=fake, beta=NS(messages=fake)))
    await llm.ask(system="s", prompt="p", model=s.llm_memory_model, max_turns=1, effort=s.llm_memory_effort)
    await llm.ask(system="s", prompt="p")
    assert fake.requests[0]["output_config"] == {"effort": "medium"}
    assert fake.requests[0]["model"] == "claude-sonnet-5-5"
    assert fake.requests[1]["output_config"] == {"effort": "high"}
