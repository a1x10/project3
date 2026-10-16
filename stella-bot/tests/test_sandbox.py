"""Запуск кода — только по просьбе владельца, в песочнице Anthropic (здесь — подделка клиента)."""

import asyncio
from types import SimpleNamespace as NS

import pytest

from bot.sandbox import CodeSandbox, SandboxError

from .conftest import OWNER, VASYA, settle, upsert

OWNER_JID = f"{OWNER}@s.whatsapp.net"


def usage():
    return NS(input_tokens=100, output_tokens=50, cache_read_input_tokens=0, cache_creation_input_tokens=0)


def result_block(stdout="", stderr="", code=0, files=()):
    return NS(type="bash_code_execution_tool_result", content=NS(
        type="bash_code_execution_result", stdout=stdout, stderr=stderr, return_code=code,
        content=[NS(type="bash_code_execution_output", file_id=f) for f in files]))


class FakeFiles:
    def __init__(self, blobs):
        self.blobs = blobs

    async def retrieve_metadata(self, fid):
        name, mime, data = self.blobs[fid]
        return NS(filename=name, mime_type=mime, size_bytes=len(data))

    async def download(self, fid):
        data = self.blobs[fid][2]

        class R:
            async def read(self):
                return data
        return R()


class FakeClient:
    def __init__(self, responses, blobs=None, delay=0.0):
        self.responses = list(responses)
        self.requests = []
        self.delay = delay
        self.files = FakeFiles(blobs or {})
        self.messages = self

    async def create(self, **kw):
        self.requests.append(kw)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.responses.pop(0)


async def test_run_collects_output_files_and_continues_after_pause():
    paused = NS(stop_reason="pause_turn", usage=usage(), content=[result_block("шаг 1\n")])
    done = NS(stop_reason="end_turn", usage=usage(), content=[
        result_block("среднее = 5.5\n", files=["f1"]), NS(type="text", text="готово, график внутри")])
    client = FakeClient([paused, done], {"f1": ("../../chart.png", "image/png", b"PNG")})
    res = await CodeSandbox(client=client).run("посчитай среднее и нарисуй график")
    assert res.text == "готово, график внутри" and "среднее = 5.5" in res.stdout and "шаг 1" in res.stdout
    assert [(f.filename, f.kind) for f in res.files] == [("chart.png", "image")]  # без ../ в имени
    assert client.requests[0]["tools"][0]["type"].startswith("code_execution")
    assert client.requests[1]["messages"][-1]["role"] == "assistant"  # пауза — отправляем её ответ обратно
    assert res.cost_usd > 0


async def test_refusal_and_timeout():
    client = FakeClient([NS(stop_reason="refusal", usage=usage(), content=[])])
    with pytest.raises(SandboxError):
        await CodeSandbox(client=client).run("x")
    slow = FakeClient([NS(stop_reason="end_turn", usage=usage(), content=[])], delay=1)
    with pytest.raises(SandboxError):
        await CodeSandbox(client=slow, timeout=0.05).run("x")


async def test_only_owner_gets_run_code(brain):
    brain.sandbox._client = FakeClient([NS(stop_reason="end_turn", usage=usage(), content=[
        result_block("42\n", files=["f"]), NS(type="text", text="42")])], {"f": ("res.xlsx", "application/x", b"X")})

    async def owner_asks(tools, prompt):
        assert "run_code" in tools
        out = await tools["run_code"].handler({"task": "сколько будет 6*7"})
        assert "42" in out
        try:
            await tools["run_code"].handler({"task": "ещё"})
        except Exception as exc:
            assert "один запуск" in str(exc)
        return "42"

    brain.llm.queue = [owner_asks]
    await brain.handle_payload(upsert("стелла посчитай", chat=OWNER_JID, sender=OWNER_JID))
    await settle(brain)
    assert brain.evo.texts() == ["42"] and brain.evo.sent[-1]["type"] == "media"

    brain.llm.queue = ["нет"]
    await brain.handle_payload(upsert("стелла запусти код", chat=VASYA))
    await settle(brain)
    assert "run_code" not in brain.llm.calls[-1]["tools"]  # чужим — даже не показываем


async def test_sandbox_can_be_switched_off(brain):
    brain.s.sandbox_enabled = False
    brain.llm.queue = ["ок"]
    await brain.handle_payload(upsert("стелла привет", chat=OWNER_JID, sender=OWNER_JID))
    await settle(brain)
    assert "run_code" not in brain.llm.calls[-1]["tools"]
