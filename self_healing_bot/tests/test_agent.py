from __future__ import annotations

import asyncio
import json
import os

import pytest
from aiohttp import web
from conftest import FakeProvider

from agent import (
    Agent,
    AIError,
    AnthropicProvider,
    OpenAICompatibleProvider,
    apply_edit,
    build_patches,
    extract_json,
    find_source_refs,
    load_context_file,
    make_diagnosis,
    redact,
    resolve_project_file,
)

GOOD_ANSWER = {
    "summary": "Опечатка в имени функции",
    "root_cause": "load_confg не определена",
    "confidence": "high",
    "edits": [{"file": "app.py", "search": "config = load_confg()", "replace": "config = load_config()"}],
    "commands": [],
    "notes": "",
}


@pytest.fixture
def project(tmp_path):
    app = tmp_path / "app"
    (app / "lib").mkdir(parents=True)
    (app / "app.py").write_text("from lib.util import helper\n\nconfig = load_confg()\n")
    (app / "lib" / "util.py").write_text("def helper():\n    return 1 / 0\n")
    (app / "server.js").write_text("const x = require('./x');\nconsole.log(x);\n")
    (app / ".env").write_text("TOKEN=secret\n")
    return app


def test_find_source_refs_python_traceback(project):
    logs = f"""Traceback (most recent call last):
  File "{project}/app.py", line 3, in <module>
  File "{project}/lib/util.py", line 2, in helper
  File "/usr/lib/python3/site-packages/requests/api.py", line 10, in get
ZeroDivisionError: division by zero"""
    refs = find_source_refs(logs, project)
    assert [r.path.name for r in refs] == ["util.py", "app.py"]  # последний упомянутый — первым
    assert refs[0].lines == [2]


def test_find_source_refs_node_stack_with_docker_paths(project):
    logs = """/usr/src/app/server.js:1
Error: Cannot find module './x'
    at Object.<anonymous> (/usr/src/app/server.js:1:11)
    at Module._compile (node:internal/modules/cjs/loader:1256:14)
    at /usr/src/app/node_modules/express/lib/router.js:5:1"""
    refs = find_source_refs(logs, project)
    assert [r.path for r in refs] == [project / "server.js"]


@pytest.mark.parametrize("raw", ["../outside.py", "/etc/passwd", ".env", ".git/config", "node_modules/a.js", "nope.py"])
def test_resolve_project_file_rejects_dangerous_paths(project, raw):
    (project.parent / "outside.py").write_text("x = 1\n")
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("[core]\n")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "a.js").write_text("1\n")
    path, error = resolve_project_file(raw, project)
    assert path is None and error


def test_resolve_project_file_rejects_symlink_escape(project, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("password\n")
    os.symlink(secret, project / "link.py")
    path, error = resolve_project_file("link.py", project)
    assert path is None and "за пределы" in error


def test_apply_edit_exact_ambiguous_and_loose():
    assert apply_edit("a = 1\nb = 2\n", "b = 2", "b = 3") == ("a = 1\nb = 3\n", None)
    updated, error = apply_edit("x\nx\n", "x", "y")
    assert updated is None and "2 раз" in error
    # Лишние пробелы в конце строк и \r\n не мешают; переводы строк файла сохраняются
    crlf = "def f():\r\n    return 1   \r\nprint(f())\r\n"
    updated, error = apply_edit(crlf, "def f():\n    return 1\n", "def f():\n    return 2\n")
    assert error is None
    assert updated == "def f():\r\n    return 2\r\nprint(f())\r\n"
    assert apply_edit("a\n", "zzz", "y")[0] is None


def test_build_patches_only_for_files_in_context(project):
    edits = [
        {"file": "app.py", "search": "load_confg()", "replace": "load_config()"},
        {"file": "lib/util.py", "search": "1 / 0", "replace": "1"},
    ]
    patches, rejected = build_patches(edits, project, allowed={"app.py"})
    assert [p.rel_path for p in patches] == ["app.py"]
    assert len(rejected) == 1 and "не было в контексте" in rejected[0]


def test_make_diagnosis_builds_diff(project):
    diag = make_diagnosis(GOOD_ANSWER, project, {"app.py"}, "fake-model")
    assert diag.can_apply
    assert "-config = load_confg()" in diag.diff and "+config = load_config()" in diag.diff
    assert diag.patches[0].stats() == (1, 1)
    # Битый ответ не роняет бота, а превращается в «нечего применять»
    broken = make_diagnosis({"edits": "oops", "confidence": "???"}, project, set(), "m")
    assert not broken.can_apply and broken.confidence == "low"


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Вот ответ:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('prefix {"a": 3} suffix') == {"a": 3}
    with pytest.raises(AIError):
        extract_json("не json")


def test_redact_masks_secrets():
    text = (
        "Authorization: Bearer abcdefghijklmnop\n"
        "connect postgres://user:hunter2@db:5432/app\n"
        "OPENAI_API_KEY=sk-proj-1234567890abcdefXYZ\n"
        'password: "qwerty"\n'
        "bot 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1 failed"
    )
    masked = redact(text)
    for secret in ("abcdefghijklmnop", "hunter2", "1234567890abcdef", "qwerty", "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1"):
        assert secret not in masked


def test_load_context_file_excerpt_for_big_files(tmp_path):
    big = tmp_path / "big.py"
    big.write_text("".join(f"line_{i} = {i}\n" for i in range(1, 2001)))
    ctx = load_context_file(big, tmp_path, [1000], max_chars=5000)
    assert ctx is not None and len(ctx.chunks) == 1
    attrs, text = ctx.chunks[0]
    assert attrs == 'lines="920-1080 of 2000"'
    assert "line_1000 = 1000" in text and "line_1 = 1\n" not in text


def test_agent_analyze_sends_code_and_validates_patch(project, make_settings):
    settings = make_settings(project, APP_START_CMD="python3 app.py")
    provider = FakeProvider(GOOD_ANSWER)
    agent = Agent(settings, provider=provider)
    logs = f'Traceback:\n  File "{project}/app.py", line 3, in <module>\nNameError: name \'load_confg\' is not defined'

    diag = asyncio.run(agent.analyze(logs=logs, reason="HTTP 502"))

    system, user = provider.calls[0]
    assert "search/replace" in system
    assert '<file path="app.py">' in user and "config = load_confg()" in user
    assert "TOKEN=secret" not in user  # .env никогда не уходит в ИИ
    assert diag.can_apply and diag.model == "fake-model"


# ---------- Провайдеры: проверяем реальные HTTP-запросы на локальном mock-сервере ----------


async def _serve(handler):
    app = web.Application()
    app.router.add_post("/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def _message(content, stop_reason="end_turn", model="claude-opus-5-5"):
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": content,
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


def test_anthropic_provider_request_shape(project, make_settings):
    seen = {}

    async def handler(request):
        seen["path"] = request.path
        seen["headers"] = {k.lower(): v for k, v in request.headers.items()}
        seen["body"] = await request.json()
        content = [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": json.dumps(GOOD_ANSWER, ensure_ascii=False)},
        ]
        return web.json_response(_message(content))

    async def scenario():
        runner, url = await _serve(handler)
        try:
            settings = make_settings(
                project, APP_START_CMD="x", AI_PROVIDER="anthropic", AI_API_KEY="test-key", AI_BASE_URL=url
            )
            return await AnthropicProvider(settings).complete_json("system", "user prompt")
        finally:
            await runner.cleanup()

    data, model = asyncio.run(scenario())
    assert data == GOOD_ANSWER and model == "claude-opus-5-5"
    assert seen["path"] == "/v1/messages"
    assert seen["headers"]["x-api-key"] == "test-key"
    assert "server-side-fallback-2026-07-01" in seen["headers"]["anthropic-beta"]
    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "thinking" not in body  # на Opus 5.5 мышление адаптивное по умолчанию
    assert body["system"] == "system" and body["messages"][0]["content"] == "user prompt"


def test_anthropic_provider_refusal_and_fallback_blocks(project, make_settings):
    replies = [
        _message([], stop_reason="refusal"),
        _message(
            [
                {"type": "text", "text": "частичный ответ отказавшей модели"},
                {"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-4-8"}},
                {"type": "text", "text": json.dumps(GOOD_ANSWER)},
            ],
            model="claude-opus-4-8",
        ),
    ]

    async def handler(request):
        return web.json_response(replies.pop(0))

    async def scenario():
        runner, url = await _serve(handler)
        try:
            settings = make_settings(
                project, APP_START_CMD="x", AI_PROVIDER="anthropic", AI_API_KEY="k", AI_BASE_URL=url
            )
            provider = AnthropicProvider(settings)
            with pytest.raises(AIError, match="отказалась"):
                await provider.complete_json("s", "u")
            return await provider.complete_json("s", "u")
        finally:
            await runner.cleanup()

    data, model = asyncio.run(scenario())
    assert data == GOOD_ANSWER and model == "claude-opus-4-8"


def test_anthropic_provider_without_fallback_for_other_models(project, make_settings):
    seen = {}

    async def handler(request):
        seen["headers"] = {k.lower(): v for k, v in request.headers.items()}
        seen["body"] = await request.json()
        return web.json_response(_message([{"type": "text", "text": "{}"}], model="claude-haiku-4-5"))

    async def scenario():
        runner, url = await _serve(handler)
        try:
            settings = make_settings(
                project, APP_START_CMD="x", AI_PROVIDER="anthropic", AI_API_KEY="k", AI_BASE_URL=url,
                AI_MODEL="claude-haiku-4-5", AI_EFFORT="none",
            )
            return await AnthropicProvider(settings).complete_json("s", "u")
        finally:
            await runner.cleanup()

    asyncio.run(scenario())
    assert "fallbacks" not in seen["body"] and "effort" not in seen["body"]["output_config"]
    assert "server-side-fallback" not in seen["headers"].get("anthropic-beta", "")


def test_openai_compatible_provider_retries_without_json_mode(project, make_settings):
    bodies = []

    async def handler(request):
        body = await request.json()
        bodies.append(body)
        if "response_format" in body:
            return web.json_response({"error": {"message": "response_format is not supported"}}, status=400)
        reply = "```json\n" + json.dumps(GOOD_ANSWER) + "\n```"
        return web.json_response({"model": "llama3", "choices": [{"message": {"content": reply}}]})

    async def scenario():
        runner, url = await _serve(handler)
        try:
            settings = make_settings(
                project, APP_START_CMD="x", AI_PROVIDER="openai", AI_BASE_URL=url + "/v1", AI_MODEL="llama3"
            )
            return await OpenAICompatibleProvider(settings).complete_json("s", "u")
        finally:
            await runner.cleanup()

    data, model = asyncio.run(scenario())
    assert data == GOOD_ANSWER and model == "llama3"
    assert len(bodies) == 2 and bodies[0]["messages"][0] == {"role": "system", "content": "s"}
