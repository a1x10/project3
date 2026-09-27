import asyncio
import importlib
import json
import socket
import time
from types import SimpleNamespace

import pytest

from app.triage import assess, fallback_reply

ISOLATED_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "STELLA_AI_MODE", "STELLA_CLOUD_MODEL",
    "STELLA_CLOUD_EFFORT", "STELLA_CLOUD_TIMEOUT", "STELLA_CLOUD_HOST", "STELLA_CLOUD_MAX_TOKENS",
    "STELLA_REPLY_DEADLINE", "STELLA_PROBE_INTERVAL", "STELLA_LLM_URL", "STELLA_LLM_TIMEOUT",
    "STELLA_LLM_QUEUE_LIMIT", "STELLA_LLM_CONCURRENCY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "NO_PROXY", "no_proxy",
)
CLOUD_KEYS = {"configured", "sdk", "model", "state", "online", "reason", "latency_ms", "last_ok", "last_error",
              "cooldown_until", "calls", "failures"}
LOCAL_KEYS = {"enabled", "state", "reason", "latency_ms", "last_ok", "last_error", "cooldown_until", "calls",
              "failures", "power", "model"}
TEXT = "Помогите, мы в доме 5 по улице Абая, 3 этаж"
HISTORY = [{"role": "user", "text": TEXT}]
TRIAGE = assess([TEXT])


@pytest.fixture()
def load(monkeypatch, tmp_path):
    for name in ISOLATED_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STELLA_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("STELLA_POWER_FILE", str(tmp_path / "power.json"))
    monkeypatch.setenv("STELLA_LLM_ENABLED", "0")
    from app import ai, config, llm

    def _load(**env):
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        importlib.reload(config)
        importlib.reload(llm)
        importlib.reload(ai)
        return ai

    yield _load
    monkeypatch.undo()
    importlib.reload(config)
    importlib.reload(llm)
    importlib.reload(ai)


def run(coro):
    return asyncio.run(coro)


def engine_stub(calls, name, outcome):
    async def engine(history, triage, budget):
        calls.append(name)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return engine


class FakeCalls:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def _next(self, kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def create(self, **kwargs):
        return await self._next(kwargs)

    async def retrieve(self, model_id, **kwargs):
        return await self._next({"model_id": model_id, **kwargs})


class FakeClient:
    def __init__(self, beta=(), plain=(), models=()):
        self.beta = SimpleNamespace(messages=FakeCalls(beta))
        self.messages = FakeCalls(plain)
        self.models = FakeCalls(models)
        self.closed = False

    async def close(self):
        self.closed = True


def install(ai, monkeypatch, client, keys=None):
    def factory(module, key):
        if keys is not None:
            keys.append(key)
        return client
    monkeypatch.setattr(ai, "_new_client", factory)
    return client


def message(text="Спасатели уже знают о вас. Где вы находитесь?", stop="end_turn", content=None):
    types = pytest.importorskip("anthropic.types.beta")
    blocks = content if content is not None else [
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": text},
    ]
    return types.BetaMessage.model_validate({
        "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5",
        "content": blocks, "stop_reason": stop, "stop_sequence": None,
        "stop_details": {"type": "refusal", "category": "cyber", "explanation": None} if stop == "refusal" else None,
        "usage": {"input_tokens": 12, "output_tokens": 7},
    })


def api_error(name, status, etype, text="ошибка", headers=None):
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": etype, "message": text}}
    response = httpx2.Response(status, request=request, json=body, headers=headers or {})
    return getattr(anthropic, name)(text, response=response, body=body)


def connection_error(timeout=False):
    anthropic = pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APITimeoutError(request) if timeout else anthropic.APIConnectionError(request=request)


def left(until):
    return round(until - time.time())


class Stub:
    def __init__(self, responder):
        self.responder = responder
        self.requests = []

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1").split("\r\n")
            method, path, _ = head[0].split(" ", 2)
            pairs = (line.split(":", 1) for line in head[1:] if ":" in line)
            headers = {k.strip().lower(): v.strip() for k, v in pairs}
            size = int(headers.get("content-length") or 0)
            body = await reader.readexactly(size) if size else b""
            request = {"method": method, "path": path, "headers": headers, "json": json.loads(body) if body else None}
            self.requests.append(request)
            status, payload = self.responder(request)
            data = json.dumps(payload, ensure_ascii=False).encode()
            writer.write(f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n"
                         f"Connection: close\r\n\r\n".encode() + data)
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


def closed_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_default_config_is_fast_reserve_without_network(load, monkeypatch):
    ai = load()

    def forbidden(*args, **kwargs):
        raise AssertionError("network must not be used")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(asyncio, "open_connection", forbidden)
    monkeypatch.setattr(ai, "_new_client", forbidden)
    monkeypatch.setattr(ai, "_ensure_sdk", forbidden)
    monkeypatch.setattr(ai.llm, "complete", forbidden)
    monkeypatch.setattr(ai.llm, "health", forbidden)
    started = time.monotonic()
    text, engine = run(ai.reply([{"role": "user", "text": "Помогите"}], assess(["Помогите"])))
    assert engine == "reserve" and "Где вы" in text
    assert time.monotonic() - started < 0.5
    snap = run(ai.probe_now())
    assert snap["active"] == "reserve"
    assert snap["cloud"]["state"] == "disabled" and snap["cloud"]["reason"] == "Ключ облачного ИИ не задан"
    assert snap["local"]["state"] == "disabled" and snap["local"]["reason"] == "Локальный ИИ отключён в настройках"


@pytest.mark.parametrize("mode, order", [
    ("auto", ["cloud", "local"]),
    ("cloud", ["cloud"]),
    ("local", ["local"]),
    ("offline", []),
])
def test_routing_order_per_mode(load, monkeypatch, mode, order):
    ai = load(STELLA_AI_MODE=mode, ANTHROPIC_API_KEY="sk-test", STELLA_LLM_ENABLED="1")
    calls = []
    monkeypatch.setattr(ai, "_cloud_reply", engine_stub(calls, "cloud", ai._Refusal("нет")))
    monkeypatch.setattr(ai, "_local_reply", engine_stub(calls, "local", ai.llm.Busy()))
    assert ai.snapshot()["active"] == (order[0] if order else "reserve")
    text, engine = run(ai.reply(HISTORY, TRIAGE))
    assert calls == order
    assert (text, engine) == (fallback_reply(TRIAGE), "reserve")
    assert ai.snapshot()["mode"] == mode


def test_auto_prefers_cloud_then_local(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test", STELLA_LLM_ENABLED="1")
    calls = []
    monkeypatch.setattr(ai, "_cloud_reply", engine_stub(calls, "cloud", "Облако на связи. Где вы?"))
    monkeypatch.setattr(ai, "_local_reply", engine_stub(calls, "local", "Локальный ИИ на связи. Где вы?"))
    assert run(ai.reply(HISTORY, TRIAGE)) == ("Облако на связи. Где вы?", "cloud")
    monkeypatch.setattr(ai, "_cloud_reply", engine_stub(calls, "cloud", ai._Empty("пусто")))
    assert run(ai.reply(HISTORY, TRIAGE)) == ("Локальный ИИ на связи. Где вы?", "local")
    assert calls == ["cloud", "cloud", "local"]
    snap = ai.snapshot()
    assert snap["last_reply"]["engine"] == "local" and snap["local"]["state"] == "ok"
    assert snap["cloud"]["calls"] == 2 and snap["cloud"]["failures"] == 1


def test_cloud_success_sends_opus_params_and_trims(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    long_text = "Оставайтесь на месте и берегите заряд телефона. " * 20 + "Где вы?"
    client = install(ai, monkeypatch, FakeClient(beta=[message(long_text)]))
    text, engine = run(ai.reply(HISTORY, TRIAGE))
    assert engine == "cloud"
    assert len(text) <= 600 and text.endswith("телефона.") and "  " not in text
    call = client.beta.messages.calls[0]
    assert call["model"] == "claude-opus-5" and call["max_tokens"] == ai.config.CLOUD_MAX_TOKENS
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["extra_body"] == {"fallbacks": "default"}
    assert call["output_config"] == {"effort": "low"}
    assert not {"temperature", "top_p", "top_k", "thinking"} & call.keys()
    assert call["messages"] == [{"role": "user", "content": TEXT}]
    assert call["system"].startswith(ai.CLOUD_PROMPT + "\n\n")
    assert "Известно:" in call["system"] and "Не хватает:" in call["system"]
    assert "Интернета" not in call["system"]
    assert 0 < call["timeout"] <= 25
    assert client.messages.calls == []
    cloud = ai.snapshot()["cloud"]
    assert cloud["state"] == "ok" and cloud["online"] is True and cloud["calls"] == 1
    assert cloud["latency_ms"] is not None and cloud["effort"] == "low" and cloud["fallbacks"] is True


def test_cloud_system_prompt_is_stable_except_context(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    client = install(ai, monkeypatch, FakeClient(beta=[message()]))
    run(ai.reply(HISTORY, TRIAGE))
    other = "человек без сознания"
    run(ai.reply([{"role": "user", "text": other}], assess([other])))
    first, second = (c["system"] for c in client.beta.messages.calls)
    prefix = ai.CLOUD_PROMPT + "\n\n"
    assert first.startswith(prefix) and second.startswith(prefix) and first != second


def test_cloud_reads_only_text_blocks_and_cuts_truncated_output(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    truncated = message(stop="max_tokens", content=[
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": "**Оставайтесь на месте.** Спасатели уже зна"},
    ])
    install(ai, monkeypatch, FakeClient(beta=[truncated]))
    assert run(ai.reply(HISTORY, TRIAGE)) == ("Оставайтесь на месте.", "cloud")


def test_cloud_thinking_only_reply_is_a_failure(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    empty = message(stop="max_tokens", content=[{"type": "thinking", "thinking": "", "signature": "sig"}])
    install(ai, monkeypatch, FakeClient(beta=[empty]))
    assert run(ai.reply(HISTORY, TRIAGE))[1] == "reserve"
    cloud = ai.snapshot()["cloud"]
    assert cloud["failures"] == 1 and cloud["cooldown_until"] is None


def test_refusal_falls_to_next_engine_without_cooldown(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test", STELLA_LLM_ENABLED="1")
    client = install(ai, monkeypatch, FakeClient(beta=[message(stop="refusal", content=[])]))
    monkeypatch.setattr(ai, "_local_reply", engine_stub([], "local", "Локальный ответ. Где вы?"))
    assert run(ai.reply(HISTORY, TRIAGE)) == ("Локальный ответ. Где вы?", "local")
    cloud = ai.snapshot()["cloud"]
    assert cloud["cooldown_until"] is None and cloud["state"] in ("unknown", "ok")
    assert cloud["failures"] == 1 and "refusal" in cloud["last_error"]
    run(ai.reply(HISTORY, TRIAGE))
    assert len(client.beta.messages.calls) == 2


@pytest.mark.parametrize("name, status, etype", [
    ("AuthenticationError", 401, "authentication_error"),
    ("PermissionDeniedError", 403, "permission_error"),
])
def test_auth_error_long_cooldown_until_key_changes(load, monkeypatch, name, status, etype):
    ai = load(ANTHROPIC_API_KEY="sk-bad-key-123")
    keys = []
    client = install(ai, monkeypatch, FakeClient(beta=[api_error(name, status, etype, "invalid x-api-key")]), keys)
    assert run(ai.reply(HISTORY, TRIAGE))[1] == "reserve"
    cloud = ai.snapshot()["cloud"]
    assert cloud["state"] == "error" and cloud["reason"].startswith("Неверный ключ API")
    assert 1795 <= left(cloud["cooldown_until"]) <= 1800
    run(ai.reply(HISTORY, TRIAGE))
    assert len(client.beta.messages.calls) == 1
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-good-key-456")
    importlib.reload(ai.config)
    client.beta.messages.outcomes = [message("Ключ принят. Где вы?")]
    assert ai.snapshot()["cloud"]["state"] == "unknown"
    assert run(ai.reply(HISTORY, TRIAGE)) == ("Ключ принят. Где вы?", "cloud")
    assert keys == ["sk-bad-key-123", "sk-good-key-456"]


@pytest.mark.parametrize("error, pause, reason", [
    (("APIStatusError", 402, "billing_error"), 1800, "Нет средств на счёте API"),
    (("BadRequestError", 400, "invalid_request_error", "Your credit balance is too low"), 1800,
     "Нет средств на счёте API"),
    (("NotFoundError", 404, "not_found_error"), 1800, "Модель claude-opus-5 недоступна"),
    (("BadRequestError", 400, "invalid_request_error", "messages: roles must alternate"), 300,
     "Облако отклонило запрос"),
])
def test_permanent_cloud_errors(load, monkeypatch, error, pause, reason):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    install(ai, monkeypatch, FakeClient(beta=[api_error(*error)]))
    assert run(ai.reply(HISTORY, TRIAGE))[1] == "reserve"
    cloud = ai.snapshot()["cloud"]
    assert cloud["state"] == "error" and cloud["reason"].startswith(reason)
    assert pause - 5 <= left(cloud["cooldown_until"]) <= pause


@pytest.mark.parametrize("make", [
    lambda: api_error("RateLimitError", 429, "rate_limit_error"),
    lambda: api_error("InternalServerError", 500, "api_error"),
    lambda: api_error("OverloadedError", 529, "overloaded_error"),
    lambda: connection_error(timeout=True),
])
def test_transient_errors_back_off_exponentially(load, monkeypatch, make):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    install(ai, monkeypatch, FakeClient(beta=[make()]))
    pauses = []
    for _ in range(7):
        assert run(ai.reply(HISTORY, TRIAGE))[1] == "reserve"
        cloud = ai.snapshot()["cloud"]
        assert cloud["state"] == "cooldown"
        pauses.append(left(cloud["cooldown_until"]))
        ai._cloud.cool_until = time.monotonic() - 1
    assert pauses == [15, 30, 60, 120, 240, 300, 300]
    ai._cloud.failed_at -= 601
    run(ai.reply(HISTORY, TRIAGE))
    assert left(ai.snapshot()["cloud"]["cooldown_until"]) == 15


def test_rate_limit_respects_retry_after(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    error = api_error("RateLimitError", 429, "rate_limit_error", headers={"retry-after": "120"})
    install(ai, monkeypatch, FakeClient(beta=[error]))
    run(ai.reply(HISTORY, TRIAGE))
    assert left(ai.snapshot()["cloud"]["cooldown_until"]) == 120


def test_connection_error_marks_cloud_offline(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    install(ai, monkeypatch, FakeClient(beta=[connection_error()]))
    assert run(ai.reply(HISTORY, TRIAGE))[1] == "reserve"
    snap = ai.snapshot()
    assert snap["cloud"]["state"] == "offline" and snap["cloud"]["online"] is False
    assert 15 <= left(snap["cloud"]["cooldown_until"]) <= 20
    assert snap["active"] == "reserve"


def test_rejected_fallback_beta_is_retried_without_and_remembered(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    rejected = api_error("BadRequestError", 400, "invalid_request_error", "fallbacks: Extra inputs are not permitted")
    client = install(ai, monkeypatch, FakeClient(
        beta=[rejected], plain=[message("Первый ответ. Где вы?"), message("Второй ответ. Где вы?")]))
    assert run(ai.reply(HISTORY, TRIAGE)) == ("Первый ответ. Где вы?", "cloud")
    retry = client.messages.calls[0]
    assert "betas" not in retry and "extra_body" not in retry
    assert retry["output_config"] == {"effort": "low"}
    assert run(ai.reply(HISTORY, TRIAGE)) == ("Второй ответ. Где вы?", "cloud")
    assert len(client.beta.messages.calls) == 1 and len(client.messages.calls) == 2
    cloud = ai.snapshot()["cloud"]
    assert cloud["fallbacks"] is False and cloud["failures"] == 0 and cloud["state"] == "ok"


def test_haiku_gets_neither_effort_nor_fallbacks(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test", STELLA_CLOUD_MODEL="claude-haiku-4-5")
    client = install(ai, monkeypatch, FakeClient(plain=[message("Хайку на связи. Где вы?")]))
    assert run(ai.reply(HISTORY, TRIAGE)) == ("Хайку на связи. Где вы?", "cloud")
    call = client.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert not {"output_config", "betas", "extra_body", "temperature", "top_p", "top_k"} & call.keys()
    assert client.beta.messages.calls == []
    cloud = ai.snapshot()["cloud"]
    assert cloud["effort"] is None and cloud["fallbacks"] is False and cloud["model"] == "claude-haiku-4-5"


def test_history_is_mapped_for_the_cloud(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    history = [
        {"id": 1, "role": "assistant", "text": "Здравствуйте, это аварийный чат"},
        {"id": 2, "role": "user", "text": "Помогите"},
        {"id": 3, "role": "user", "text": "Мы в подвале"},
        {"id": 4, "role": "advice", "text": "Прижмите рану"},
        {"id": 5, "role": "assistant", "text": "Где вы?"},
        {"id": 6, "role": "rescuer", "text": "Мы в пути"},
        {"id": 7, "role": "user", "text": "Ждём"},
        {"id": 8, "role": "user", "text": "   "},
    ]
    expected = [
        {"role": "user", "content": "Помогите\nМы в подвале"},
        {"role": "assistant", "content": "Где вы?\nСпасатель: Мы в пути"},
        {"role": "user", "content": "Ждём"},
    ]
    assert ai.llm.history_turns(history, 12) == expected
    client = install(ai, monkeypatch, FakeClient(beta=[message()]))
    run(ai.reply(history, assess(["Помогите", "Мы в подвале", "Ждём"])))
    assert client.beta.messages.calls[0]["messages"] == expected
    alternating = [{"role": "user" if i % 2 == 0 else "assistant", "text": f"m{i}"} for i in range(31)]
    turns = ai.llm.history_turns(alternating, 12)
    assert [t["content"] for t in turns] == [f"m{i}" for i in range(20, 31)]
    assert turns[0]["role"] == "user" and turns[-1]["role"] == "user"
    assert ai.llm.history_turns([{"role": "user", "text": "а"}, {"role": "rescuer", "text": "б"}], 12) == [
        {"role": "user", "content": "а"}]


def test_no_user_message_goes_straight_to_reserve(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test", STELLA_LLM_ENABLED="1")
    calls = []
    monkeypatch.setattr(ai, "_cloud_reply", engine_stub(calls, "cloud", "не должен"))
    monkeypatch.setattr(ai, "_local_reply", engine_stub(calls, "local", "не должен"))
    text, engine = run(ai.reply([{"role": "assistant", "text": "Где вы?"}, "мусор", None], None))
    assert engine == "reserve" and text and calls == []


def test_local_busy_goes_to_reserve_immediately(load):
    ai = load(STELLA_AI_MODE="local", STELLA_LLM_ENABLED="1", STELLA_LLM_QUEUE_LIMIT="0",
              STELLA_LLM_URL=f"http://127.0.0.1:{closed_port()}/v1/chat/completions")

    async def scenario():
        gate = ai.llm._sem()
        await gate.acquire()
        started = time.monotonic()
        try:
            result = await ai.self_test(TEXT)
        finally:
            gate.release()
        return result, time.monotonic() - started

    result, elapsed = run(scenario())
    assert result["engine"] == "reserve" and elapsed < 0.5
    assert result["attempts"][0] == {"engine": "local", "ok": False, "error": "Локальный ИИ занят другим запросом",
                                     "ms": result["attempts"][0]["ms"]}
    local = ai.snapshot()["local"]
    assert local["failures"] == 0 and local["calls"] == 0 and local["cooldown_until"] is None


def test_local_engine_talks_to_llama_server(load):
    def llama(request):
        if request["path"] == "/health":
            return 200, {"status": "ok"}
        if request["path"] == "/v1/models":
            return 200, {"data": [{"id": "/opt/stella/models/model-0.5b.gguf"}]}
        return 200, {"choices": [{"message": {"content": "<think>думаю</think>Оставайтесь на месте. Где вы?"}}]}

    async def scenario():
        async with Stub(llama) as stub:
            ai = load(STELLA_AI_MODE="local", STELLA_LLM_ENABLED="1",
                      STELLA_LLM_URL=f"http://127.0.0.1:{stub.port}/v1/chat/completions")
            snap = await ai.probe_now()
            result = await ai.reply(HISTORY, TRIAGE)
            return ai, snap, result, stub.requests

    ai, snap, result, requests = run(scenario())
    assert snap["local"]["state"] == "ok" and snap["local"]["model"] == "model-0.5b.gguf"
    assert snap["active"] == "local"
    assert result == ("Оставайтесь на месте. Где вы?", "local")
    body = requests[-1]["json"]
    assert body["messages"][0]["role"] == "system" and "Известно:" in body["messages"][0]["content"]
    assert body["messages"][-1] == {"role": "user", "content": TEXT}
    assert ai.snapshot()["local"]["latency_ms"] is not None


def test_local_loading_and_down_are_detected(load):
    async def scenario():
        async with Stub(lambda request: (503, {"error": "loading model"})) as stub:
            ai = load(STELLA_AI_MODE="local", STELLA_LLM_ENABLED="1",
                      STELLA_LLM_URL=f"http://127.0.0.1:{stub.port}/v1/chat/completions")
            loading = await ai.probe_now()
            reply = await ai.reply(HISTORY, TRIAGE)
            return ai, loading, reply, list(stub.requests)

    ai, loading, reply, requests = run(scenario())
    assert loading["local"]["state"] == "loading" and loading["active"] == "reserve"
    assert reply[1] == "reserve" and [r["path"] for r in requests] == ["/health"]
    ai = load(STELLA_AI_MODE="local", STELLA_LLM_ENABLED="1",
              STELLA_LLM_URL=f"http://127.0.0.1:{closed_port()}/v1/chat/completions")
    assert run(ai.reply(HISTORY, TRIAGE))[1] == "reserve"
    local = ai.snapshot()["local"]
    assert local["state"] == "cooldown" and local["failures"] == 1
    assert 5 <= left(local["cooldown_until"]) <= 10
    assert run(ai.probe_now())["local"]["state"] == "cooldown"
    ai._local.cool_until = time.monotonic() - 1
    assert ai.snapshot()["local"]["state"] == "down"


def test_local_failures_back_off_up_to_two_minutes(load, monkeypatch):
    ai = load(STELLA_AI_MODE="local", STELLA_LLM_ENABLED="1")
    monkeypatch.setattr(ai, "_local_reply", engine_stub([], "local", ai.llm.LocalError("timeout", "Не успел")))
    pauses = []
    for _ in range(6):
        run(ai.reply(HISTORY, TRIAGE))
        pauses.append(left(ai.snapshot()["local"]["cooldown_until"]))
        ai._local.cool_until = time.monotonic() - 1
    assert pauses == [10, 20, 40, 80, 120, 120]


def test_power_off_disables_local(load, monkeypatch, tmp_path):
    (tmp_path / "power.json").write_text(json.dumps({"profile": "off", "setting": "auto"}), encoding="utf-8")
    ai = load(STELLA_AI_MODE="local", STELLA_LLM_ENABLED="1")
    monkeypatch.setattr(ai.llm, "complete", engine_stub([], "local", AssertionError("must not run")))
    local = ai.snapshot()["local"]
    assert local["enabled"] is False and local["state"] == "disabled" and local["power"] == "off"
    assert local["reason"] == "Локальный ИИ выключен сторожем питания"
    assert run(ai.reply(HISTORY, TRIAGE))[1] == "reserve"
    assert ai.snapshot()["local"]["calls"] == 0


@pytest.mark.parametrize("content, power", [
    (None, "unknown"),
    ("{\"profile\": \"of", "unknown"),
    (b"\xff\xfe\x00", "unknown"),
    ("[]", "unknown"),
    ("{\"profile\": \"turbo\"}", "unknown"),
    ("{\"profile\": \"safe\"}", "safe"),
    ("{\"profile\": \"normal\"}", "normal"),
])
def test_power_file_is_tolerated(load, tmp_path, content, power):
    path = tmp_path / "power.json"
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif content is not None:
        path.write_text(content, encoding="utf-8")
    ai = load(STELLA_LLM_ENABLED="1")
    local = ai.snapshot()["local"]
    assert local["power"] == power and local["enabled"] is True


def test_power_file_directory_and_cache(load, tmp_path, monkeypatch):
    monkeypatch.setenv("STELLA_POWER_FILE", str(tmp_path))
    ai = load(STELLA_LLM_ENABLED="1")
    assert ai.snapshot()["local"]["power"] == "unknown"
    path = tmp_path / "p.json"
    path.write_text("{\"profile\": \"normal\"}", encoding="utf-8")
    ai = load(STELLA_LLM_ENABLED="1", STELLA_POWER_FILE=str(path))
    assert ai.snapshot()["local"]["power"] == "normal"
    path.write_text("{\"profile\": \"off\"}", encoding="utf-8")
    assert ai.snapshot()["local"]["power"] == "normal"
    ai._power_cache["at"] -= ai.POWER_TTL
    assert ai.snapshot()["local"]["power"] == "off"


def test_overall_deadline_is_respected(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test", STELLA_LLM_ENABLED="1")
    monkeypatch.setattr(ai.config, "REPLY_DEADLINE", 1.2)
    budgets = []

    async def slow(history, triage, budget):
        budgets.append(budget)
        await asyncio.sleep(30)
        return "Слишком поздно."

    monkeypatch.setattr(ai, "_cloud_reply", slow)
    monkeypatch.setattr(ai, "_local_reply", slow)
    started = time.monotonic()
    result = run(ai.self_test(TEXT))
    assert time.monotonic() - started < 2.0
    assert result["engine"] == "reserve" and len(budgets) == 1 and budgets[0] <= 1.2
    assert [a["engine"] for a in result["attempts"]] == ["cloud", "local", "reserve"]
    assert result["attempts"][1]["error"] == "Не хватило времени на ответ"
    cloud = ai.snapshot()["cloud"]
    assert cloud["state"] == "cooldown" and cloud["reason"].startswith("Облачный ИИ не ответил вовремя")


def test_engine_timeout_leaves_time_for_next_engine(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test", STELLA_LLM_ENABLED="1")
    monkeypatch.setattr(ai.config, "CLOUD_TIMEOUT", 0.3)

    async def slow(history, triage, budget):
        await asyncio.sleep(30)

    monkeypatch.setattr(ai, "_cloud_reply", slow)
    monkeypatch.setattr(ai, "_local_reply", engine_stub([], "local", "Локальный ответ. Где вы?"))
    started = time.monotonic()
    assert run(ai.reply(HISTORY, TRIAGE)) == ("Локальный ответ. Где вы?", "local")
    assert time.monotonic() - started < 1.5


def test_snapshot_shape_is_complete_and_json_safe(load, monkeypatch):
    ai = load()
    snap = ai.snapshot()
    assert {"mode", "active", "cloud", "local", "reserve", "last_reply", "updated"} <= snap.keys()
    assert CLOUD_KEYS <= snap["cloud"].keys() and LOCAL_KEYS <= snap["local"].keys()
    assert snap["reserve"] == {"state": "ok"} and snap["last_reply"] is None
    assert snap["mode"] == "auto" and snap["active"] == "reserve"
    assert json.loads(json.dumps(snap)) == snap
    run(ai.reply(HISTORY, TRIAGE))
    ai = load(ANTHROPIC_API_KEY="sk-secret-value-777", STELLA_LLM_ENABLED="1")
    error = api_error("BadRequestError", 400, "invalid_request_error", "bad key sk-secret-value-777 in body")
    install(ai, monkeypatch, FakeClient(beta=[error]))
    monkeypatch.setattr(ai, "_local_reply", engine_stub([], "local", ai.llm.LocalError("down", "Не запущен")))
    run(ai.reply(HISTORY, TRIAGE))
    snap = ai.snapshot()
    dumped = json.dumps(snap, ensure_ascii=False)
    assert "sk-secret-value-777" not in dumped
    assert snap["last_reply"]["engine"] == "reserve" and isinstance(snap["last_reply"]["ms"], int)
    assert snap["cloud"]["state"] in ("ok", "offline", "cooldown", "disabled", "error", "unknown")
    assert snap["local"]["state"] in ("ok", "loading", "down", "cooldown", "disabled", "unknown")
    assert snap["local"]["power"] in ("normal", "safe", "off", "unknown")
    assert isinstance(snap["cloud"]["cooldown_until"], float) and isinstance(snap["updated"], float)


def test_snapshot_never_raises(load, monkeypatch):
    ai = load()

    def broken(now):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai, "_cloud_view", broken)
    snap = ai.snapshot()
    assert snap["active"] == "reserve" and CLOUD_KEYS <= snap["cloud"].keys()


def test_self_test_returns_contract_shape(load, monkeypatch):
    ai = load()
    result = run(ai.self_test(""))
    assert set(result) == {"input", "text", "engine", "ms", "priority", "attempts"}
    assert result["input"] == ai.SAMPLE and result["engine"] == "reserve" and result["text"]
    assert result["priority"] in ("red", "yellow", "green", "unknown")
    assert result["attempts"][-1] == {"engine": "reserve", "ok": True, "error": None, "ms": 0}
    for attempt in result["attempts"]:
        assert {"engine", "ok", "error", "ms"} <= attempt.keys() and attempt["engine"] in ai.ENGINES
    json.dumps(result)
    ai = load(ANTHROPIC_API_KEY="sk-test")
    install(ai, monkeypatch, FakeClient(beta=[message("Помощь идёт. Кто ранен?")]))
    result = run(ai.self_test("  Нас трое, дом 4  "))
    assert result["input"] == "Нас трое, дом 4" and result["engine"] == "cloud"
    assert result["attempts"][0]["engine"] == "cloud" and result["attempts"][0]["ok"] is True


def test_missing_sdk_disables_cloud(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test")
    monkeypatch.setitem(ai._sdk, "module", None)
    monkeypatch.setitem(ai._sdk, "error", "Не установлена библиотека anthropic")
    monkeypatch.setattr(ai, "_new_client", engine_stub([], "client", AssertionError("no client")))
    cloud = ai.snapshot()["cloud"]
    assert cloud["configured"] is True and cloud["sdk"] is False and cloud["state"] == "disabled"
    assert cloud["reason"] == "Не установлена библиотека anthropic"
    assert run(ai.reply(HISTORY, TRIAGE))[1] == "reserve"


def test_sdk_import_failure_is_detected_at_runtime(load, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "anthropic", None)
    ai = load(ANTHROPIC_API_KEY="sk-test")
    assert run(ai.reply(HISTORY, TRIAGE))[1] == "reserve"
    cloud = ai.snapshot()["cloud"]
    assert cloud["sdk"] is False and cloud["reason"] == "Не установлена библиотека anthropic"


def test_real_sdk_request_on_the_wire(load, monkeypatch):
    pytest.importorskip("anthropic")
    ok_body = {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
               "content": [{"type": "text", "text": "Помощь в пути. Сколько вас?"}], "stop_reason": "end_turn",
               "stop_sequence": None, "usage": {"input_tokens": 5, "output_tokens": 5}}

    def api(request):
        if "fallbacks" in (request["json"] or {}):
            return 400, {"type": "error", "error": {"type": "invalid_request_error",
                                                    "message": "fallbacks: Extra inputs are not permitted"}}
        return 200, ok_body

    async def scenario():
        async with Stub(api) as stub:
            monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{stub.port}")
            ai = load(ANTHROPIC_API_KEY="sk-wire")
            result = await ai.reply(HISTORY, TRIAGE)
            client = ai._client_slot["client"]
            await ai.stop()
            return ai, result, stub.requests, client

    ai, result, requests, client = run(scenario())
    assert result == ("Помощь в пути. Сколько вас?", "cloud")
    first, second = requests
    assert first["path"] == "/v1/messages?beta=true"
    assert first["headers"]["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert first["headers"]["x-api-key"] == "sk-wire"
    assert first["json"]["fallbacks"] == "default" and first["json"]["output_config"] == {"effort": "low"}
    assert first["json"]["model"] == "claude-opus-5" and first["json"]["max_tokens"] == 2048
    assert not {"temperature", "top_p", "top_k", "thinking"} & first["json"].keys()
    assert second["path"] == "/v1/messages" and "anthropic-beta" not in second["headers"]
    assert "fallbacks" not in second["json"] and second["json"]["output_config"] == {"effort": "low"}
    assert client.is_closed() and ai._client_slot["client"] is None


def test_probe_detects_offline_cloud_and_loading_local(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test", STELLA_LLM_ENABLED="1")

    async def unreachable(host, port):
        return False, None, "Нет DNS — похоже, у коробки нет интернета"

    async def loading(timeout=2.0):
        return "loading"

    monkeypatch.setattr(ai, "_reach", unreachable)
    monkeypatch.setattr(ai.llm, "health", loading)
    install(ai, monkeypatch, FakeClient(models=[AssertionError("no key check while offline")]))
    snap = run(ai.probe_now())
    assert snap["cloud"]["online"] is False and snap["cloud"]["state"] == "offline"
    assert "DNS" in snap["cloud"]["reason"]
    assert snap["local"]["state"] == "loading" and snap["active"] == "reserve"


def test_probe_checks_key_for_free_and_recovers(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-test", STELLA_LLM_ENABLED="1")
    online = {"ok": False}

    async def reach(host, port):
        return (True, 12, None) if online["ok"] else (False, None, "Нет связи с облаком")

    async def healthy(timeout=2.0):
        return "ok"

    async def model_name(timeout=2.0):
        return "model-0.5b.gguf"

    monkeypatch.setattr(ai, "_reach", reach)
    monkeypatch.setattr(ai.llm, "health", healthy)
    monkeypatch.setattr(ai.llm, "model_name", model_name)
    client = install(ai, monkeypatch, FakeClient(
        beta=[connection_error()],
        models=[api_error("AuthenticationError", 401, "authentication_error"), SimpleNamespace(id="claude-opus-5")]))
    run(ai.reply(HISTORY, TRIAGE))
    assert ai.snapshot()["cloud"]["state"] == "offline"
    online["ok"] = True
    snap = run(ai.probe_now())
    assert snap["cloud"]["state"] == "error" and snap["cloud"]["reason"].startswith("Неверный ключ API")
    assert snap["active"] == "local" and snap["local"]["model"] == "model-0.5b.gguf"
    assert snap["cloud"]["calls"] == 1 and snap["cloud"]["probe_ms"] == 12
    snap = run(ai.probe_now())
    assert snap["cloud"]["state"] == "ok" and snap["cloud"]["online"] is True and snap["active"] == "cloud"
    assert [c["model_id"] for c in client.models.calls] == ["claude-opus-5", "claude-opus-5"]
    assert len(client.beta.messages.calls) == 1 and client.messages.calls == []


def test_reach_uses_real_tcp(load):
    ai = load()

    async def no_dns(*args, **kwargs):
        raise socket.gaierror(-2, "Name or service not known")

    async def portal_dns(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.42.0.1", port))]

    async def scenario():
        server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        opened = await ai._reach("127.0.0.1", port)
        server.close()
        await server.wait_closed()
        refused = await ai._reach("127.0.0.1", closed_port())
        loop = asyncio.get_running_loop()
        loop.getaddrinfo = no_dns
        unknown = await ai._reach("api.anthropic.com", 443)
        loop.getaddrinfo = portal_dns
        portal = await ai._reach("api.anthropic.com", 443)
        return opened, refused, unknown, portal

    opened, refused, unknown, portal = run(scenario())
    assert opened[0] is True and isinstance(opened[1], int)
    assert refused == (False, None, "Нет связи с облаком")
    assert unknown[0] is False and "DNS" in unknown[2]
    assert portal[0] is False and "портал" in portal[2]


def test_probe_target_follows_proxy_settings(load, monkeypatch):
    ai = load()
    assert ai._probe_target() == ("api.anthropic.com", 443)
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.5:3128")
    assert ai._probe_target() == ("10.0.0.5", 3128)
    monkeypatch.setenv("NO_PROXY", "localhost,api.anthropic.com")
    assert ai._probe_target() == ("api.anthropic.com", 443)


def test_probe_loop_survives_errors_and_start_stop_are_idempotent(load, monkeypatch):
    ai = load()
    monkeypatch.setattr(ai.config, "PROBE_INTERVAL", 0.01)
    runs = []

    async def flaky(force=False):
        runs.append(force)
        if len(runs) == 1:
            raise RuntimeError("probe exploded")

    monkeypatch.setattr(ai, "_probe_once", flaky)

    async def scenario():
        await ai.stop()
        await ai.start()
        first = ai._runtime["task"]
        await ai.start()
        assert ai._runtime["task"] is first
        for _ in range(200):
            if len(runs) >= 3:
                break
            await asyncio.sleep(0.01)
        await ai.stop()
        await ai.stop()
        return first

    task = run(scenario())
    assert len(runs) >= 3 and task.done() and ai._runtime["task"] is None


def test_stop_closes_cloud_client_and_key_change_recreates_it(load, monkeypatch):
    ai = load(ANTHROPIC_API_KEY="sk-one")
    clients = [FakeClient(beta=[message()]), FakeClient(beta=[message()])]
    keys = []

    def factory(module, key):
        keys.append(key)
        return clients[len(keys) - 1]

    monkeypatch.setattr(ai, "_new_client", factory)

    async def scenario():
        await ai.reply(HISTORY, TRIAGE)
        await ai.reply(HISTORY, TRIAGE)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-two")
        importlib.reload(ai.config)
        await ai.reply(HISTORY, TRIAGE)
        await ai.stop()

    run(scenario())
    assert keys == ["sk-one", "sk-two"]
    assert clients[0].closed and clients[1].closed


def test_llm_legacy_generate_never_raises(load, monkeypatch):
    ai = load()
    assert run(ai.llm.generate(HISTORY, TRIAGE)) is None
    ai = load(STELLA_LLM_ENABLED="1", STELLA_LLM_URL=f"http://127.0.0.1:{closed_port()}/v1/chat/completions")
    assert run(ai.llm.generate(HISTORY, TRIAGE)) is None
    assert run(ai.llm.health()) == "down" and run(ai.llm.healthy()) is False
    assert "Известно:" in ai.llm.build_messages(HISTORY, TRIAGE)[0]["content"]


def test_tidy_limits_and_cleans(load):
    ai = load()
    tidy = ai.llm.tidy
    assert tidy("Спасатель: **Держитесь.**  Где вы?") == "Держитесь. Где вы?"
    assert tidy("<think>скрыто</think>\n\n\n\nОк.") == "Ок."
    words = tidy("слово " * 200)
    assert len(words) <= 600 and words.endswith("…")
    assert tidy(None) == ""
