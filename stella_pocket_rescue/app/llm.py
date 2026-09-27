import asyncio
import logging
import re
import time
from urllib.parse import urlsplit

import httpx

from . import config
from .triage import TriageResult

log = logging.getLogger("stella.llm")
if logging.getLogger("httpx").level == logging.NOTSET:
    logging.getLogger("httpx").setLevel(logging.WARNING)

SYSTEM_PROMPT = """Ты — спокойный диспетчер спасательной службы. Интернета и сотовой связи нет,
ты работаешь на автономном устройстве в зоне бедствия. Спасатели видят данные из этого чата.
Правила:
- Отвечай по-русски, коротко: 1–3 предложения.
- Будь спокойным и поддерживающим, но не многословным. Не обещай точное время прибытия.
- Задавай ровно ОДИН уточняющий вопрос за раз, начиная с самого важного из списка "Не хватает".
- Не ставь диагнозов и не давай советов, кроме простейшей первой помощи.
- Никогда не советуй идти в опасное место или разбирать завал самостоятельно."""

MISSING_LABELS = {
    "location": "где находится (адрес, этаж, ориентир)",
    "condition": "есть ли раненые и какие травмы",
    "people": "сколько людей рядом, есть ли дети или пожилые",
}

RESCUER_PREFIX = "Спасатель: "
REPLY_LIMIT = 600
TURN_LIMIT = 1500
MERGED_LIMIT = 3000
LOCAL_TURNS = 8

_THINK_RE = re.compile(r"<think>.*?(?:</think>|$)", re.S | re.I)
_SPEAKER_RE = re.compile(r"^\s*(спасатель|диспетчер|ассистент|assistant)\s*:\s*", re.I)
_SENTENCE_END_RE = re.compile(r"[.!?…](?=[\s\"»)]|$)")

_gate: dict = {"sem": None, "loop": None, "size": 0}
_waiting = 0


class Busy(Exception):
    pass


class LocalError(Exception):
    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind = kind
        self.reason = reason


def _sem() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    size = max(1, int(config.LLM_CONCURRENCY))
    if _gate["sem"] is None or _gate["loop"] is not loop or _gate["size"] != size:
        _gate.update(sem=asyncio.Semaphore(size), loop=loop, size=size)
    return _gate["sem"]


def busy() -> bool:
    sem = _gate["sem"]
    return _waiting > 0 or (sem is not None and sem.locked())


def context(triage: TriageResult) -> str:
    known = [
        f"Приоритет: {triage.priority}",
        f"Признаки: {', '.join(triage.tags) or 'нет данных'}",
        f"Место: {triage.location_text or ('координаты получены' if triage.coords else 'неизвестно')}",
        f"Людей: {triage.people if triage.people is not None else 'неизвестно'}",
    ]
    missing = ", ".join(MISSING_LABELS.get(m, m) for m in triage.missing) or "ничего, всё собрано"
    return f"Известно: {'; '.join(known)}.\nНе хватает: {missing}."


def _turn(item) -> tuple[str | None, str]:
    if not isinstance(item, dict):
        return None, ""
    text = str(item.get("text") or "").strip()[:TURN_LIMIT]
    if not text:
        return None, ""
    role = item.get("role")
    if role == "user":
        return "user", text
    if role == "assistant":
        return "assistant", text
    if role == "rescuer":
        return "assistant", RESCUER_PREFIX + text
    return None, ""


def history_turns(history: list[dict] | None, limit: int) -> list[dict]:
    turns: list[dict] = []
    for item in history or []:
        role, text = _turn(item)
        if role is None:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] = f"{turns[-1]['content']}\n{text}"[-MERGED_LIMIT:]
        else:
            turns.append({"role": role, "content": text})
    turns = turns[-limit:] if limit > 0 else []
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    while turns and turns[-1]["role"] != "user":
        turns.pop()
    return turns


def build_messages(history: list[dict], triage: TriageResult) -> list[dict]:
    system = f"{SYSTEM_PROMPT}\n\n{context(triage)}"
    return [{"role": "system", "content": system}, *history_turns(history, LOCAL_TURNS)]


def whole_sentences(text: str) -> str:
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(text or "")]
    return text[:ends[-1]].strip() if ends else ""


def _cut(text: str, limit: int) -> str:
    head = text[:limit]
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(head)]
    if ends and ends[-1] >= limit // 3:
        return head[:ends[-1]].strip()
    head = head[:limit - 1]
    space = head.rfind(" ")
    if space > limit // 3:
        head = head[:space]
    return head.rstrip(" ,;:—-") + "…"


def tidy(text: str | None, limit: int = REPLY_LIMIT) -> str:
    text = _THINK_RE.sub("", str(text or ""))
    text = text.replace("**", "").replace("__", "")
    text = _SPEAKER_RE.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) <= limit else _cut(text, limit)


def base_url() -> str:
    url = config.LLM_URL
    if "/v1/" in url:
        return url.split("/v1/")[0]
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else url.rstrip("/")


async def _acquire(sem: asyncio.Semaphore, wait: float) -> None:
    global _waiting
    if sem.locked() and _waiting >= config.LLM_QUEUE_LIMIT:
        raise Busy()
    _waiting += 1
    try:
        await asyncio.wait_for(sem.acquire(), timeout=max(0.01, wait))
    except asyncio.TimeoutError:
        raise Busy() from None
    finally:
        _waiting -= 1


def _answer(resp: httpx.Response) -> str:
    if resp.status_code == 503:
        raise LocalError("loading", "Локальная модель ещё загружается")
    if resp.status_code != 200:
        raise LocalError("http", f"Локальный ИИ вернул ошибку {resp.status_code}")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise LocalError("bad_response", "Локальный ИИ прислал непонятный ответ") from None
    text = tidy(content)
    if not text:
        raise LocalError("empty", "Локальный ИИ вернул пустой ответ")
    return text


async def _post(messages: list[dict], timeout: float) -> str:
    payload = {
        "messages": messages,
        "max_tokens": config.LLM_MAX_TOKENS,
        "temperature": 0.3,
        "stream": False,
    }
    limits = httpx.Timeout(timeout, connect=min(3.0, timeout))
    try:
        async with httpx.AsyncClient(timeout=limits, trust_env=False) as client:
            resp = await client.post(config.LLM_URL, json=payload)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        raise LocalError("down", "Локальный ИИ не запущен") from None
    except httpx.TimeoutException:
        raise LocalError("timeout", "Локальный ИИ не ответил вовремя") from None
    except httpx.HTTPError as exc:
        raise LocalError("http", f"Ошибка связи с локальным ИИ: {type(exc).__name__}") from None
    return _answer(resp)


async def complete(history: list[dict], triage: TriageResult, timeout: float | None = None) -> str:
    if not config.LLM_ENABLED:
        raise LocalError("disabled", "Локальный ИИ отключён в настройках")
    limit = float(config.LLM_TIMEOUT) if timeout is None else max(0.5, min(float(timeout), float(config.LLM_TIMEOUT)))
    started = time.monotonic()
    sem = _sem()
    await _acquire(sem, limit)
    try:
        remaining = max(0.5, limit - (time.monotonic() - started))
        return await _post(build_messages(history, triage), remaining)
    finally:
        sem.release()


async def generate(history: list[dict], triage: TriageResult) -> str | None:
    if not config.LLM_ENABLED:
        return None
    try:
        return await complete(history, triage)
    except Busy:
        log.info("LLM занята, ответ без неё")
    except LocalError as exc:
        log.warning("LLM недоступна: %s", exc.reason)
    except Exception as exc:
        log.warning("LLM недоступна: %r", exc)
    return None


async def health(timeout: float = 2.0) -> str:
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.get(base_url() + "/health")
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return "down"
    except httpx.TimeoutException:
        return "timeout"
    except Exception as exc:
        log.debug("LLM health failed: %r", exc)
        return "down"
    if resp.status_code == 200:
        return "ok"
    if resp.status_code == 503:
        return "loading"
    return "down"


async def healthy() -> bool:
    return await health() == "ok"


async def model_name(timeout: float = 2.0) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.get(base_url() + "/v1/models")
        name = resp.json()["data"][0]["id"] if resp.status_code == 200 else None
    except Exception:
        return None
    if not isinstance(name, str) or not name.strip():
        return None
    return name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1][:80]
