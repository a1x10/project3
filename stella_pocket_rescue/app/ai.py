import asyncio
import hashlib
import importlib
import importlib.util
import inspect
import json
import logging
import socket
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import config, llm
from .triage import TriageResult, assess, fallback_reply

log = logging.getLogger("stella.ai")
if logging.getLogger("httpx2").level == logging.NOTSET:
    logging.getLogger("httpx2").setLevel(logging.WARNING)

ENGINES = ("cloud", "local", "reserve")
ROUTES = {"auto": ("cloud", "local"), "cloud": ("cloud",), "local": ("local",), "offline": ()}
MODE_OFF = {
    "auto": "Выключен режимом ИИ",
    "cloud": "Режим ИИ «только облако»",
    "local": "Режим ИИ «только локальный»",
    "offline": "Режим ИИ «офлайн» — только резервные ответы",
}

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-opus-5", "claude-fable")
EFFORT_MODELS = (
    "claude-opus-5", "claude-fable", "claude-mythos", "claude-sonnet-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-opus-4-5", "claude-sonnet-4-6",
)
HISTORY_TURNS = 12
MIN_BUDGET = 1.0
PROBE_TIMEOUT = 3.0
VERIFY_TIMEOUT = 5.0
VERIFY_EVERY = 1800.0
POWER_TTL = 5.0
CLOUD_PAUSE = (15.0, 300.0)
LOCAL_PAUSE = (10.0, 120.0)

SAMPLE = "Нас двое, у мамы кровь из ноги, мы на 3 этаже, дом 12 по улице Абая"
RESERVE_TEXT = ("Ваше сообщение получено, спасатели его видят. Где вы находитесь? "
                "Назовите адрес, этаж или ориентир рядом.")

CLOUD_PROMPT = """Ты — спокойный диспетчер спасательной службы. Тебе пишут люди из зоны бедствия
через аварийную точку Wi‑Fi «Stella», часто с почти разряженного телефона.
Спасатели видят всё, что написано в этом чате.
Правила:
- Отвечай по-русски, коротко: 1–3 предложения простым текстом, без списков и разметки.
- Будь спокойным и поддерживающим, но не многословным. Не обещай точное время прибытия.
- Задавай ровно ОДИН уточняющий вопрос за раз, начиная с самого важного из списка «Не хватает».
  Если всё собрано — спроси, не изменилось ли состояние людей.
- Не ставь диагнозов и не давай советов, кроме простейшей первой помощи.
- Никогда не советуй идти в опасное место или разбирать завал самостоятельно.
- Сообщения с пометкой «Спасатель:» написали настоящие спасатели. Не противоречь им и не пиши от их имени.
- Не придумывай подробностей о спасательной операции, которых нет в чате."""

CLOUD_POLICY = {
    "auth": ("error", 1800.0, "Неверный ключ API или нет доступа — облако отклоняет ключ"),
    "billing": ("error", 1800.0, "Нет средств на счёте API"),
    "model": ("error", 1800.0, "Модель {model} недоступна"),
    "bad_request": ("error", 300.0, "Облако отклонило запрос"),
    "failure": ("error", 60.0, "Сбой облачного ИИ"),
    "offline": ("offline", 20.0, "Нет связи с облаком"),
    "limit": ("cooldown", None, "Превышен лимит запросов к облаку"),
    "overload": ("cooldown", None, "Облачный ИИ перегружен"),
    "timeout": ("cooldown", None, "Облачный ИИ не ответил вовремя"),
    "refusal": (None, 0.0, "Облачный ИИ отказался отвечать"),
    "empty": (None, 0.0, "Облачный ИИ вернул пустой ответ"),
    "sdk": (None, 0.0, "Не установлена библиотека anthropic"),
}
SCOPED = ("auth", "billing", "model")
LOCAL_SEEN = {
    "ok": None,
    "loading": "Локальная модель загружается",
    "down": "Локальный ИИ не запущен",
    "timeout": "Локальный ИИ не отвечает на проверку",
}


class _Refusal(Exception):
    pass


class _Empty(Exception):
    pass


class _NoSdk(Exception):
    pass


class _PortalDns(OSError):
    pass


@dataclass
class Engine:
    state: str = "unknown"
    reason: str | None = None
    latency_ms: int | None = None
    last_ok: float | None = None
    last_error: str | None = None
    cool_until: float | None = None
    calls: int = 0
    failures: int = 0
    streak: int = 0
    failed_at: float = 0.0
    kind: str | None = None
    scope: tuple = ()
    seen: str = "unknown"
    seen_at: float = 0.0
    seen_reason: str | None = None
    probe_ms: int | None = None
    model: str | None = None
    checked: tuple = ()
    checked_at: float = 0.0
    verified: tuple = ()


_cloud = Engine()
_local = Engine()
_sdk: dict = {"module": None, "error": None, "found": None}
_client_slot: dict = {"client": None, "key": None, "loop": None}
_loop_slot: dict = {"loop": None, "items": {}}
_power_cache: dict = {"path": None, "at": 0.0, "value": "unknown"}
_runtime: dict = {"task": None, "updated": time.time(), "last_reply": None, "dropped": {}}
_closing: set = set()


def _ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _touch() -> None:
    _runtime["updated"] = time.time()


def _mode() -> str:
    return config.AI_MODE if config.AI_MODE in ROUTES else "auto"


def _fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:16] if key else ""


def _scope() -> tuple:
    return _fingerprint(config.ANTHROPIC_API_KEY), config.CLOUD_MODEL


def _redact(text: str) -> str:
    key = config.ANTHROPIC_API_KEY
    return text.replace(key, "***") if key and len(key) > 6 else text


def _loop_item(name, factory):
    loop = asyncio.get_running_loop()
    if _loop_slot["loop"] is not loop:
        _loop_slot.update(loop=loop, items={})
    items = _loop_slot["items"]
    if name not in items:
        items[name] = factory()
    return items[name]


def _sdk_found() -> bool:
    if _sdk["module"] is not None:
        return True
    if _sdk["error"] is not None:
        return False
    if _sdk["found"] is None:
        try:
            _sdk["found"] = importlib.util.find_spec("anthropic") is not None
        except (ImportError, ValueError):
            _sdk["found"] = False
    return bool(_sdk["found"])


def _load_sdk():
    if _sdk["module"] is None and _sdk["error"] is None:
        try:
            _sdk["module"] = importlib.import_module("anthropic")
        except ImportError:
            _sdk["error"] = "Не установлена библиотека anthropic"
        except Exception as exc:
            _sdk["error"] = "Библиотека anthropic не загружается"
            log.warning("anthropic import failed: %r", exc)
    return _sdk["module"]


async def _ensure_sdk():
    if _sdk["module"] is None and _sdk["error"] is None:
        await asyncio.to_thread(_load_sdk)
    return _sdk["module"]


def _sdk_classes(*names: str) -> tuple:
    module = _sdk["module"]
    found = (getattr(module, name, None) for name in names) if module is not None else ()
    return tuple(c for c in found if isinstance(c, type))


def _new_client(module, key: str):
    return module.AsyncAnthropic(api_key=key, max_retries=1, timeout=config.CLOUD_TIMEOUT)


def _client(module):
    loop = asyncio.get_running_loop()
    key = config.ANTHROPIC_API_KEY
    slot = _client_slot
    if slot["client"] is not None and slot["key"] == key and slot["loop"] is loop:
        return slot["client"]
    old, old_loop = slot["client"], slot["loop"]
    client = _new_client(module, key)
    slot.update(client=client, key=key, loop=loop)
    if old is not None and old_loop is loop:
        _close_later(old)
    return client


async def _close(client) -> None:
    try:
        result = client.close()
        if inspect.isawaitable(result):
            await asyncio.wait_for(result, timeout=3)
    except Exception as exc:
        log.debug("AI client close failed: %r", exc)


def _close_later(client) -> None:
    task = asyncio.get_running_loop().create_task(_close(client))
    _closing.add(task)
    task.add_done_callback(_closing.discard)


def _read_power(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            raw = fh.read(65536)
    except OSError:
        return "unknown"
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return "unknown"
    profile = data.get("profile") if isinstance(data, dict) else None
    return profile if profile in ("normal", "safe", "off") else "unknown"


def _power() -> str:
    path = str(config.POWER_FILE)
    now = time.monotonic()
    cache = _power_cache
    if cache["path"] == path and now - cache["at"] < POWER_TTL:
        return cache["value"]
    value = _read_power(path)
    cache.update(path=path, at=now, value=value)
    return value


def _fresh(engine: Engine, now: float) -> bool:
    try:
        window = max(60.0, 3 * float(config.PROBE_INTERVAL))
    except (TypeError, ValueError):
        window = 60.0
    return bool(engine.seen_at) and now - engine.seen_at <= window


def _cooling(engine: Engine, now: float) -> bool:
    if engine.cool_until is None or now >= engine.cool_until:
        return False
    return not (engine is _cloud and engine.kind in SCOPED and engine.scope != _scope())


def _lift(engine: Engine, *kinds: str) -> None:
    if engine.kind in kinds and engine.cool_until is not None:
        engine.cool_until = None
        engine.kind = None
        engine.streak = 0
        engine.state = "ok"
        engine.reason = None


def _cloud_view(now: float) -> tuple[str, str | None, bool]:
    mode = _mode()
    if "cloud" not in ROUTES[mode]:
        return "disabled", MODE_OFF[mode], False
    if not config.ANTHROPIC_API_KEY:
        return "disabled", "Ключ облачного ИИ не задан", False
    if not _sdk_found():
        return "disabled", _sdk["error"] or "Не установлена библиотека anthropic", False
    if _cooling(_cloud, now):
        return _cloud.state, _cloud.reason, False
    if _cloud.seen == "offline" and _fresh(_cloud, now):
        return "offline", _cloud.seen_reason or "Нет связи с облаком", False
    if _cloud.last_ok is not None or _cloud.verified == _scope():
        return "ok", None, True
    return "unknown", None, True


def _local_view(now: float) -> tuple[str, str | None, bool]:
    mode = _mode()
    if "local" not in ROUTES[mode]:
        return "disabled", MODE_OFF[mode], False
    if not config.LLM_ENABLED:
        return "disabled", "Локальный ИИ отключён в настройках", False
    if _power() == "off":
        return "disabled", "Локальный ИИ выключен сторожем питания", False
    if _cooling(_local, now):
        return "cooldown", _local.reason, False
    seen = _local.seen if _fresh(_local, now) else "unknown"
    if seen in ("loading", "down"):
        return seen, _local.seen_reason or LOCAL_SEEN[seen], False
    return seen if seen == "ok" else "unknown", None, True


def _view(engine: str, now: float) -> tuple[str, str | None, bool]:
    return _cloud_view(now) if engine == "cloud" else _local_view(now)


def _active(now: float) -> str:
    for engine in ROUTES[_mode()]:
        if _view(engine, now)[2]:
            return engine
    return "reserve"


def _until(engine: Engine, now: float) -> float | None:
    if not _cooling(engine, now):
        return None
    return round(time.time() + (engine.cool_until - now), 3)


def _uses_effort(model: str) -> bool:
    return model.startswith(EFFORT_MODELS)


def _features(model: str) -> set:
    features = set()
    if model.startswith(FALLBACK_MODELS):
        features.add("fallbacks")
    if _uses_effort(model):
        features.add("effort")
    return features - _runtime["dropped"].get(model, set())


def _snapshot() -> dict:
    now = time.monotonic()
    key = bool(config.ANTHROPIC_API_KEY)
    model = config.CLOUD_MODEL
    power = _power()
    cloud_state, cloud_reason, _ = _cloud_view(now)
    local_state, local_reason, _ = _local_view(now)
    features = _features(model) if key else set()
    last = _runtime["last_reply"]
    return {
        "mode": _mode(),
        "active": _active(now),
        "cloud": {
            "configured": key,
            "sdk": _sdk_found(),
            "model": model if key else None,
            "state": cloud_state,
            "online": {"online": True, "offline": False}.get(_cloud.seen),
            "reason": cloud_reason,
            "latency_ms": _cloud.latency_ms,
            "last_ok": _cloud.last_ok,
            "last_error": _cloud.last_error,
            "cooldown_until": _until(_cloud, now),
            "calls": _cloud.calls,
            "failures": _cloud.failures,
            "effort": config.CLOUD_EFFORT if "effort" in features else None,
            "fallbacks": "fallbacks" in features,
            "probe_ms": _cloud.probe_ms,
        },
        "local": {
            "enabled": bool(config.LLM_ENABLED) and power != "off",
            "state": local_state,
            "reason": local_reason,
            "latency_ms": _local.latency_ms,
            "last_ok": _local.last_ok,
            "last_error": _local.last_error,
            "cooldown_until": _until(_local, now),
            "calls": _local.calls,
            "failures": _local.failures,
            "power": power,
            "model": _local.model,
            "probe_ms": _local.probe_ms,
        },
        "reserve": {"state": "ok"},
        "last_reply": dict(last) if last else None,
        "updated": _runtime["updated"],
    }


def _plain_snapshot() -> dict:
    return {
        "mode": "auto",
        "active": "reserve",
        "cloud": {"configured": False, "sdk": False, "model": None, "state": "unknown", "online": None,
                  "reason": "Состояние облачного ИИ неизвестно", "latency_ms": None, "last_ok": None,
                  "last_error": None, "cooldown_until": None, "calls": 0, "failures": 0},
        "local": {"enabled": False, "state": "unknown", "reason": "Состояние локального ИИ неизвестно",
                  "latency_ms": None, "last_ok": None, "last_error": None, "cooldown_until": None,
                  "calls": 0, "failures": 0, "power": "unknown", "model": None},
        "reserve": {"state": "ok"},
        "last_reply": None,
        "updated": time.time(),
    }


def snapshot() -> dict:
    try:
        return _snapshot()
    except Exception:
        log.exception("AI snapshot failed")
        return _plain_snapshot()


def _error_text(exc: BaseException) -> str:
    text = str(getattr(exc, "message", "") or "") or str(exc)
    body = getattr(exc, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        detail = body["error"].get("message")
        if isinstance(detail, str) and detail not in text:
            text = f"{text} {detail}".strip()
    return _redact(text)


def _short(exc: BaseException) -> str:
    name, text = type(exc).__name__, _error_text(exc)
    return (f"{name}: {text}" if text else name)[:300]


def _status_kind(exc) -> str:
    status = getattr(exc, "status_code", 0) or 0
    etype = getattr(exc, "type", None)
    text = _error_text(exc).lower()
    if status in (401, 403) or etype in ("authentication_error", "permission_error"):
        return "auth"
    if status == 402 or etype == "billing_error" or "credit balance" in text:
        return "billing"
    if status == 404 or etype == "not_found_error":
        return "model"
    if status == 429 or etype == "rate_limit_error":
        return "limit"
    if status in (408, 504) or etype == "timeout_error":
        return "timeout"
    if status == 409 or status >= 500 or etype in ("overloaded_error", "api_error"):
        return "overload"
    if status in (400, 413, 422) or etype == "invalid_request_error":
        return "bad_request"
    return "failure"


def _classify_cloud(exc: BaseException) -> str:
    if isinstance(exc, _Refusal):
        return "refusal"
    if isinstance(exc, _Empty):
        return "empty"
    if isinstance(exc, _NoSdk):
        return "sdk"
    if isinstance(exc, _sdk_classes("APITimeoutError")) or isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"
    if isinstance(exc, _sdk_classes("APIConnectionError")):
        return "offline"
    if isinstance(exc, _sdk_classes("APIStatusError")):
        return _status_kind(exc)
    if isinstance(exc, _sdk_classes("CredentialsError")):
        return "auth"
    return "failure"


def _retry_after(exc: BaseException) -> float:
    try:
        value = float(exc.response.headers.get("retry-after") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0.0
    return value if 0 < value < 3600 else 0.0


def _backoff(engine: Engine, now: float, base: float, cap: float) -> float:
    if now - engine.failed_at > 2 * cap:
        engine.streak = 0
    engine.failed_at = now
    engine.streak += 1
    return min(base * 2 ** (min(engine.streak, 20) - 1), cap)


def _cloud_penalty(kind: str, exc: BaseException, counted: bool) -> str:
    state, fixed, reason = CLOUD_POLICY[kind]
    reason = reason.format(model=config.CLOUD_MODEL)
    if kind == "sdk":
        reason = _sdk["error"] or reason
    s = _cloud
    now = time.monotonic()
    if counted:
        s.calls += 1
        s.failures += 1
    s.last_error = _short(exc)
    pause = fixed
    if fixed is None:
        pause = max(_backoff(s, now, *CLOUD_PAUSE), min(_retry_after(exc), CLOUD_PAUSE[1]))
    if kind == "offline":
        s.seen, s.seen_at, s.seen_reason = "offline", now, reason
    if pause:
        s.cool_until = now + pause
        s.kind = kind
        s.scope = _scope()
        s.state = state
        s.reason = f"{reason} — пауза {int(pause)} с" if kind not in SCOPED else reason
    log.warning("cloud AI %s: %s", kind, s.last_error)
    _touch()
    return reason


def _local_penalty(exc: BaseException) -> str:
    if isinstance(exc, llm.Busy):
        return "Локальный ИИ занят другим запросом"
    if isinstance(exc, llm.LocalError):
        kind, reason = exc.kind, exc.reason
    elif isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        kind, reason = "timeout", "Локальный ИИ не ответил вовремя"
    else:
        kind, reason = "failure", "Сбой локального ИИ"
    s = _local
    now = time.monotonic()
    s.calls += 1
    s.failures += 1
    s.last_error = _short(exc)
    pause = _backoff(s, now, *LOCAL_PAUSE)
    s.cool_until = now + pause
    s.kind = kind
    s.state = "cooldown"
    s.reason = f"{reason} — пауза {int(pause)} с"
    if kind in ("down", "loading"):
        s.seen, s.seen_at, s.seen_reason = kind, now, reason
    log.warning("local AI %s: %s", kind, s.last_error)
    _touch()
    return reason


def _succeeded(engine: str, ms: int) -> None:
    s = _cloud if engine == "cloud" else _local
    s.calls += 1
    s.streak = 0
    s.cool_until = None
    s.kind = None
    s.state = "ok"
    s.reason = None
    s.latency_ms = ms
    s.last_ok = time.time()
    s.seen = "online" if engine == "cloud" else "ok"
    s.seen_at = time.monotonic()
    s.seen_reason = None
    _touch()


def _rejected_features(exc: BaseException, features: set) -> set:
    if not isinstance(exc, _sdk_classes("BadRequestError")):
        return set()
    text = _error_text(exc).lower()
    dropped = set()
    if "fallbacks" in features and ("fallback" in text or "beta" in text):
        dropped.add("fallbacks")
    if "effort" in features and ("effort" in text or "output_config" in text):
        dropped.add("effort")
    return dropped


async def _cloud_create(client, system: str, messages: list[dict], deadline: float):
    model = config.CLOUD_MODEL
    features = _features(model)
    while True:
        params = {
            "model": model,
            "max_tokens": config.CLOUD_MAX_TOKENS,
            "system": system,
            "messages": messages,
            "timeout": max(1.0, deadline - time.monotonic()),
        }
        if "effort" in features:
            params["output_config"] = {"effort": config.CLOUD_EFFORT}
        try:
            if "fallbacks" in features:
                return await client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"})
            return await client.messages.create(**params)
        except Exception as exc:
            dropped = _rejected_features(exc, features)
            if not dropped:
                raise
            features -= dropped
            _runtime["dropped"].setdefault(model, set()).update(dropped)
            log.warning("cloud rejected %s for %s, retrying without: %s", sorted(dropped), model, _short(exc))


def _cloud_text(message) -> str:
    stop = getattr(message, "stop_reason", None)
    if stop == "refusal":
        category = getattr(getattr(message, "stop_details", None), "category", None)
        raise _Refusal(f"refusal ({category or 'без категории'})")
    parts = []
    for block in getattr(message, "content", None) or []:
        text = getattr(block, "text", None)
        if getattr(block, "type", None) == "text" and isinstance(text, str) and text.strip():
            parts.append(text.strip())
    text = llm.tidy("\n".join(parts))
    if stop in ("max_tokens", "model_context_window_exceeded"):
        text = llm.whole_sentences(text)
    if not text:
        raise _Empty(f"empty reply (stop_reason={stop})")
    return text


async def _cloud_reply(history: list[dict], triage: TriageResult, budget: float) -> str:
    deadline = time.monotonic() + budget
    module = await _ensure_sdk()
    if module is None:
        raise _NoSdk(_sdk["error"] or "anthropic is missing")
    messages = llm.history_turns(history, HISTORY_TURNS)
    system = f"{CLOUD_PROMPT}\n\n{llm.context(triage)}"
    size = max(1, int(config.CLOUD_CONCURRENCY))
    gate = _loop_item(("cloud", size), lambda: asyncio.Semaphore(size))
    async with gate:
        message = await _cloud_create(_client(module), system, messages, deadline)
    return _cloud_text(message)


async def _local_reply(history: list[dict], triage: TriageResult, budget: float) -> str:
    return await llm.complete(history, triage, timeout=budget)


def _engine_timeout(engine: str) -> float:
    return float(config.CLOUD_TIMEOUT if engine == "cloud" else config.LLM_TIMEOUT)


async def _attempt(engine: str, history: list[dict], triage: TriageResult, budget: float):
    started = time.monotonic()
    call = _cloud_reply if engine == "cloud" else _local_reply
    try:
        text = await asyncio.wait_for(call(history, triage, budget), timeout=budget)
        if not isinstance(text, str) or not text.strip():
            raise _Empty("empty reply")
    except Exception as exc:
        ms = _ms(started)
        if engine == "cloud":
            return None, _cloud_penalty(_classify_cloud(exc), exc, counted=True), ms
        if isinstance(exc, _Empty):
            exc = llm.LocalError("empty", "Локальный ИИ вернул пустой ответ")
        return None, _local_penalty(exc), ms
    ms = _ms(started)
    _succeeded(engine, ms)
    return text.strip(), None, ms


def _skip(engine: str, reason: str | None) -> dict:
    return {"engine": engine, "ok": False, "error": reason or "Недоступен", "ms": 0, "skipped": True}


def _reserve(triage) -> str:
    try:
        text = fallback_reply(triage)
    except Exception:
        log.exception("reserve reply failed")
        return RESERVE_TEXT
    return text if isinstance(text, str) and text.strip() else RESERVE_TEXT


def _safe_triage(history: list[dict], triage) -> TriageResult:
    if isinstance(triage, TriageResult):
        return triage
    try:
        return assess([str(m.get("text") or "") for m in history if m.get("role") == "user"])
    except Exception:
        return TriageResult()


def _deadline() -> float:
    try:
        value = float(config.REPLY_DEADLINE)
    except (TypeError, ValueError):
        return 75.0
    return value if value > 0 else 75.0


async def _route(history, triage, started: float, attempts: list[dict]) -> tuple[str, str]:
    rows = [m for m in list(history or []) if isinstance(m, dict)]
    triage = _safe_triage(rows, triage)
    deadline = started + _deadline()
    if not llm.history_turns(rows, HISTORY_TURNS):
        attempts.append(_skip("cloud", "Нет сообщения пострадавшего"))
        attempts.append({"engine": "reserve", "ok": True, "error": None, "ms": 0})
        return _reserve(triage), "reserve"
    for engine in ROUTES[_mode()]:
        state, reason, usable = _view(engine, time.monotonic())
        if not usable:
            attempts.append(_skip(engine, reason or state))
            continue
        remaining = deadline - time.monotonic()
        if remaining < MIN_BUDGET:
            attempts.append(_skip(engine, "Не хватило времени на ответ"))
            continue
        budget = max(0.05, min(_engine_timeout(engine), remaining))
        text, error, ms = await _attempt(engine, rows, triage, budget)
        attempts.append({"engine": engine, "ok": text is not None, "error": error, "ms": ms})
        if text is not None:
            return text, engine
    attempts.append({"engine": "reserve", "ok": True, "error": None, "ms": 0})
    return _reserve(triage), "reserve"


async def reply(history: list[dict], triage: TriageResult) -> tuple[str, str]:
    started = time.monotonic()
    try:
        text, engine = await _route(history, triage, started, [])
    except Exception:
        log.exception("AI routing failed")
        text, engine = _reserve(triage), "reserve"
    _runtime["last_reply"] = {"engine": engine, "ts": time.time(), "ms": _ms(started)}
    _touch()
    return text, engine


async def self_test(text: str) -> dict:
    sample = str(text or "").strip()[:300] or SAMPLE
    started = time.monotonic()
    attempts: list[dict] = []
    try:
        triage = assess([sample])
    except Exception:
        triage = TriageResult()
    try:
        answer, engine = await _route([{"role": "user", "text": sample}], triage, started, attempts)
    except Exception:
        log.exception("AI self-test failed")
        answer, engine = _reserve(triage), "reserve"
        attempts.append({"engine": "reserve", "ok": True, "error": None, "ms": 0})
    return {"input": sample, "text": answer, "engine": engine, "ms": _ms(started),
            "priority": triage.priority, "attempts": attempts}


def _probe_target() -> tuple[str, int]:
    host = config.CLOUD_HOST
    try:
        proxies = urllib.request.getproxies_environment()
        proxy = proxies.get("https") or proxies.get("all")
        if proxy and not urllib.request.proxy_bypass_environment(host, proxies):
            parts = urlsplit(proxy if "://" in proxy else f"http://{proxy}")
            if parts.hostname:
                return parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
    except Exception as exc:
        log.debug("proxy settings ignored: %r", exc)
    return host, 443


async def _connect(host: str, port: int) -> None:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(info[4][0] for info in infos))[:4]
    if not addresses:
        raise socket.gaierror("no address")
    if addresses == [config.PORTAL_HOST] and host != config.PORTAL_HOST:
        raise _PortalDns("dns points to portal")
    error: OSError = OSError("unreachable")
    for address in addresses:
        try:
            _, writer = await asyncio.open_connection(address, port)
        except OSError as exc:
            error = exc
            continue
        writer.close()
        return
    raise error


async def _reach(host: str, port: int) -> tuple[bool, int | None, str | None]:
    started = time.monotonic()
    try:
        await asyncio.wait_for(_connect(host, port), timeout=PROBE_TIMEOUT)
    except socket.gaierror:
        return False, None, "Нет DNS — похоже, у коробки нет интернета"
    except _PortalDns:
        return False, None, "DNS коробки указывает на портал — облако недоступно"
    except (asyncio.TimeoutError, TimeoutError):
        return False, None, "Облако не отвечает — похоже, нет интернета"
    except OSError:
        return False, None, "Нет связи с облаком"
    return True, _ms(started), None


def _mark_online(ok: bool, ms: int | None, reason: str | None) -> None:
    s = _cloud
    before = s.seen
    s.seen = "online" if ok else "offline"
    s.seen_at = time.monotonic()
    s.seen_reason = reason
    s.probe_ms = ms
    if before != s.seen:
        log.info("cloud AI %s%s", s.seen, f" ({reason})" if reason else "")


async def _verify(module, force: bool) -> None:
    scope = _scope()
    now = time.monotonic()
    if not force and _cloud.checked == scope and now - _cloud.checked_at < VERIFY_EVERY:
        return
    _cloud.checked, _cloud.checked_at = scope, now
    try:
        call = _client(module).models.retrieve(config.CLOUD_MODEL, timeout=VERIFY_TIMEOUT)
        await asyncio.wait_for(call, timeout=VERIFY_TIMEOUT + 1)
    except Exception as exc:
        kind = _classify_cloud(exc)
        if kind == "auth":
            _cloud_penalty(kind, exc, counted=False)
        else:
            log.info("cloud key check inconclusive: %s", _short(exc))
        return
    _cloud.verified = scope
    _lift(_cloud, "auth", "model")
    _touch()


async def _probe_cloud(force: bool) -> None:
    module = await _ensure_sdk()
    host, port = _probe_target()
    ok, ms, reason = await _reach(host, port)
    _mark_online(ok, ms, reason)
    if ok and module is not None:
        await _verify(module, force)


async def _probe_local() -> None:
    if llm.busy():
        return
    started = time.monotonic()
    seen = await llm.health(timeout=2.0)
    s = _local
    before = s.seen
    s.seen = "down" if seen == "timeout" else seen
    s.seen_at = time.monotonic()
    s.seen_reason = LOCAL_SEEN.get(seen, LOCAL_SEEN["down"])
    s.probe_ms = _ms(started) if seen == "ok" else None
    if s.seen == "ok":
        _lift(s, "down", "loading")
        if s.model is None:
            s.model = await llm.model_name(timeout=2.0)
    elif s.seen == "down":
        s.model = None
    if before != s.seen:
        log.info("local AI %s", s.seen)


async def _probe_once(force: bool = False) -> None:
    jobs = []
    if config.ANTHROPIC_API_KEY:
        jobs.append(asyncio.wait_for(_probe_cloud(force), timeout=PROBE_TIMEOUT + VERIFY_TIMEOUT + 4))
    if config.LLM_ENABLED and _power() != "off":
        jobs.append(asyncio.wait_for(_probe_local(), timeout=6))
    for result in await asyncio.gather(*jobs, return_exceptions=True):
        if isinstance(result, Exception):
            log.warning("AI probe error: %r", result)
    _touch()


def _interval() -> float:
    try:
        return max(0.05, float(config.PROBE_INTERVAL))
    except (TypeError, ValueError):
        return 20.0


async def _probe_loop() -> None:
    log.info("AI probe loop started")
    while True:
        try:
            await _probe_once()
        except Exception:
            log.exception("AI probe failed")
        await asyncio.sleep(_interval())


async def start() -> None:
    loop = asyncio.get_running_loop()
    task = _runtime["task"]
    if task is not None and not task.done() and task.get_loop() is loop:
        return
    _runtime["task"] = loop.create_task(_probe_loop(), name="stella-ai-probe")


async def stop() -> None:
    loop = asyncio.get_running_loop()
    task, _runtime["task"] = _runtime["task"], None
    if task is not None and not task.done():
        try:
            task.cancel()
        except RuntimeError:
            pass
        if task.get_loop() is loop:
            await asyncio.wait({task}, timeout=5)
    client, client_loop = _client_slot["client"], _client_slot["loop"]
    _client_slot.update(client=None, key=None, loop=None)
    if client is not None and client_loop is loop:
        await _close(client)
    pending = [t for t in list(_closing) if not t.done() and t.get_loop() is loop]
    if pending:
        await asyncio.wait(pending, timeout=3)


async def probe_now() -> dict:
    try:
        await asyncio.wait_for(_probe_once(force=True), timeout=15)
    except Exception as exc:
        log.warning("AI probe failed: %r", exc)
    return snapshot()
