"""Клиент к локальному llama.cpp (llama-server, OpenAI-совместимый API).

RK3399 выдаёт единицы токенов в секунду, поэтому:
  * одновременно в модель идёт LLM_CONCURRENCY запросов, очередь ограничена;
  * если модель занята, недоступна или не уложилась в таймаут — возвращаем None,
    и отвечает детерминированный диспетчер из triage.fallback_reply.
"""
import asyncio
import logging

import httpx

from . import config
from .triage import TriageResult

log = logging.getLogger("stella.llm")

SYSTEM_PROMPT = """Ты — спокойный диспетчер спасательной службы. Интернета и сотовой связи нет,
ты работаешь на автономном устройстве в зоне бедствия. Спасатели видят данные из этого чата.
Правила:
- Отвечай по-русски, коротко: 1–3 предложения.
- Будь спокойным и поддерживающим, но не многословным. Не обещай точное время прибытия.
- Задавай ровно ОДИН уточняющий вопрос за раз, начиная с самого важного из списка "Не хватает".
- Не ставь диагнозов и не давай советов, кроме простейшей первой помощи.
- Никогда не советуй идти в опасное место или разбирать завал самостоятельно."""

_semaphore: asyncio.Semaphore | None = None
_waiting = 0

MISSING_LABELS = {
    "location": "где находится (адрес, этаж, ориентир)",
    "condition": "есть ли раненые и какие травмы",
    "people": "сколько людей рядом, есть ли дети или пожилые",
}


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(config.LLM_CONCURRENCY)
    return _semaphore


def build_messages(history: list[dict], triage: TriageResult) -> list[dict]:
    known = [
        f"Приоритет: {triage.priority}",
        f"Признаки: {', '.join(triage.tags) or 'нет данных'}",
        f"Место: {triage.location_text or ('координаты получены' if triage.coords else 'неизвестно')}",
        f"Людей: {triage.people if triage.people is not None else 'неизвестно'}",
    ]
    missing = ", ".join(MISSING_LABELS[m] for m in triage.missing) or "ничего, всё собрано"
    system = f"{SYSTEM_PROMPT}\n\nИзвестно: {'; '.join(known)}.\nНе хватает: {missing}."
    msgs = [{"role": "system", "content": system}]
    for m in history[-8:]:  # короткий контекст — быстрее на слабом CPU
        if m["role"] in ("user", "assistant"):
            msgs.append({"role": m["role"], "content": m["text"]})
    return msgs


async def generate(history: list[dict], triage: TriageResult) -> str | None:
    global _waiting
    if not config.LLM_ENABLED:
        return None
    sem = _sem()
    if sem.locked() and _waiting >= config.LLM_QUEUE_LIMIT:
        return None  # очередь переполнена — пусть ответит детерминированный диспетчер
    _waiting += 1
    try:
        await sem.acquire()
    finally:
        _waiting -= 1
    try:
        payload = {
            "messages": build_messages(history, triage),
            "max_tokens": config.LLM_MAX_TOKENS,
            "temperature": 0.3,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT) as client:
            resp = await client.post(config.LLM_URL, json=payload)
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            return text or None
    except Exception as exc:  # сеть, таймаут, неожиданный ответ — всё уходит в fallback
        log.warning("LLM недоступна: %s", exc)
        return None
    finally:
        sem.release()


async def healthy() -> bool:
    url = config.LLM_URL.split("/v1/")[0] + "/health"
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            return (await client.get(url)).status_code == 200
    except Exception:
        return False
