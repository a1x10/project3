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
        self.uploaded, self.deleted = [], []

    async def upload(self, file):
        self.uploaded.append(file)
        return NS(id=f"up{len(self.uploaded)}")

    async def delete(self, fid):
        self.deleted.append(fid)

    async def retrieve_metadata(self, fid):
        name, mime, data = self.blobs[fid]
        return NS(filename=name, mime_type=mime, size_bytes=len(data))

    async def download(self, fid):
        data = self.blobs[fid][2]

        class R:
            async def read(self):
                return data
        return R()


class FakeStream:
    def __init__(self, client, kw):
        self.client, self.kw = client, kw

    async def __aenter__(self):
        self.client.requests.append(self.kw)
        if self.client.delay:
            await asyncio.sleep(self.client.delay)
        nxt = self.client.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        self.reply = nxt
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self.reply


class FakeClient:
    """Подмена клиента Anthropic: ответы по порядку (исключение — бросается), запросы запоминаются."""

    def __init__(self, responses, blobs=None, delay=0.0):
        self.responses = list(responses)
        self.requests = []
        self.delay = delay
        self.files = FakeFiles(blobs or {})
        self.messages = self

    def stream(self, **kw):
        return FakeStream(self, kw)


def api_error(code, message):
    import anthropic
    import httpx2

    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIStatusError(message, response=httpx2.Response(code, request=req), body=None)


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


# ---------- как Claude Code: интернет, файлы, контейнер-проект, фоновые проекты, режим друзей ----------
def done(text="готово", files=(), container="cnt_1"):
    return NS(stop_reason="end_turn", usage=usage(), container=NS(id=container),
              content=[result_block("ok\n", files=files), NS(type="text", text=text)])


async def test_max_power_request_web_tools_and_fallback():
    client = FakeClient([api_error(400, "web_fetch_20250910: unknown tool type"), done()])
    sandbox = CodeSandbox(client=client)
    res = await sandbox.run("найди документацию и напиши скрипт")
    first, second = client.requests
    assert first["model"] == "claude-opus-5-5" and first["output_config"] == {"effort": "max"}
    assert first["max_tokens"] == 64000 and [t["name"] for t in first["tools"]] == ["code_execution", "web_search",
                                                                                     "web_fetch"]
    assert [t["name"] for t in second["tools"]] == ["code_execution"] and res.container_id == "cnt_1"


async def test_input_files_go_into_the_container_and_are_cleaned_up():
    from bot.sandbox import InputFile

    client = FakeClient([done()])
    await CodeSandbox(client=client).run("разбери таблицу", [InputFile("sales.xlsx", b"XLSX", "application/x")])
    blocks = client.requests[0]["messages"][0]["content"]
    assert blocks[0]["type"] == "text" and "sales.xlsx" in blocks[0]["text"]
    assert blocks[1] == {"type": "container_upload", "file_id": "up1"}
    assert client.files.uploaded[0][0] == "sales.xlsx" and client.files.deleted == ["up1"]


async def test_expired_container_starts_fresh():
    client = FakeClient([api_error(404, "container cnt_old not found"), done(container="cnt_new")])
    res = await CodeSandbox(client=client).run("продолжи", container="cnt_old")
    assert client.requests[0]["container"] == "cnt_old" and "container" not in client.requests[1]
    assert res.container_id == "cnt_new"


async def test_project_lives_in_one_container_per_person(brain):
    brain.sandbox._client = client = FakeClient([done(container="cnt_A"), done(container="cnt_A"), done()])

    def ask(args):
        async def talk(tools, prompt):
            await tools["run_code"].handler(args)
            return "ок"
        return talk

    for args in ({"task": "сделай игру"}, {"task": "продолжи: добавь звук"}, {"task": "новое", "new_project": True}):
        brain.llm.queue = [ask(args)]
        await brain.handle_payload(upsert("стелла код", chat=OWNER_JID, sender=OWNER_JID))
        await settle(brain)
    assert "container" not in client.requests[0] and client.requests[1]["container"] == "cnt_A"
    assert "container" not in client.requests[2]


async def test_project_mode_runs_in_background_and_delivers(brain):
    brain.sandbox._client = FakeClient([done("сделала сайт, открой index.html", files=["f"])],
                                       {"f": ("index.html", "text/html", b"<html>")}, delay=0.2)
    outs = []

    async def talk(tools, prompt):
        outs.append(await tools["run_code"].handler({"task": "сделай сайт-портфолио", "mode": "project"}))
        return "взялась, пришлю как будет готово"

    brain.llm.queue = [talk]
    await brain.handle_payload(upsert("стелла сделай сайт", chat=OWNER_JID, sender=OWNER_JID, msg_id="P1"))
    await settle(brain, timeout=10)
    assert "в фоне" in outs[0]
    assert brain.evo.texts() == ["взялась, пришлю как будет готово", "сделала сайт, открой index.html"]
    assert brain.evo.sent[-1]["filename"] == "index.html" and brain.evo.sent[-1]["quoted"]["key"]["id"] == "P1"


async def test_friends_mode_trusts_only_people_in_a_group_with_the_owner(brain):
    from .conftest import GROUP, PETYA

    brain.s.friends_mode = True
    # Вася — в группе с владельцем; Петя — только в другой группе, где владельца нет
    await brain.handle_payload(upsert("всем привет", chat=GROUP, sender=f"{OWNER}@s.whatsapp.net", name="Хозяин"))
    await brain.handle_payload(upsert("привет", chat=GROUP, sender=VASYA))
    await brain.handle_payload(upsert("здарова", chat="120363000000000099@g.us", sender=PETYA, name="Петя"))
    await settle(brain)
    seen = {}

    def grab(who):
        async def g(tools, prompt):
            seen[who] = set(tools)
            return "ок"
        return g

    brain.llm.queue = [grab("vasya"), grab("petya")]
    await brain.handle_payload(upsert("стелла посчитай", chat=VASYA, sender=VASYA))
    await settle(brain)
    await brain.handle_payload(upsert("стелла посчитай", chat=PETYA, sender=PETYA, name="Петя"))
    await settle(brain)
    assert "run_code" in seen["vasya"] and "run_code" not in seen["petya"]
    brain.s.friends_mode = False
    brain._trust.clear()
    brain.llm.queue = [grab("vasya-off")]
    await brain.handle_payload(upsert("стелла посчитай", chat=VASYA, sender=VASYA))
    await settle(brain)
    assert "run_code" not in seen["vasya-off"]
