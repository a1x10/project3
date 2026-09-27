import time

from .triage import TriageResult, fallback_reply

ENGINES = ("cloud", "local", "reserve")


async def reply(history: list[dict], triage: TriageResult) -> tuple[str, str]:
    return fallback_reply(triage), "reserve"


def snapshot() -> dict:
    now = time.time()
    return {
        "mode": "auto",
        "active": "reserve",
        "cloud": {"configured": False, "sdk": False, "model": None, "state": "disabled", "online": None,
                  "reason": "Ключ облачного ИИ не задан", "latency_ms": None, "last_ok": None,
                  "last_error": None, "cooldown_until": None, "calls": 0, "failures": 0},
        "local": {"enabled": False, "state": "disabled", "reason": "Локальный ИИ выключен", "latency_ms": None,
                  "last_ok": None, "last_error": None, "cooldown_until": None, "calls": 0, "failures": 0,
                  "power": "unknown", "model": None},
        "reserve": {"state": "ok"},
        "last_reply": None,
        "updated": now,
    }


async def start() -> None:
    return None


async def stop() -> None:
    return None


async def probe_now() -> dict:
    return snapshot()


async def self_test(text: str) -> dict:
    from .triage import assess
    result = assess([text])
    return {"input": text, "text": fallback_reply(result), "engine": "reserve", "ms": 0,
            "priority": result.priority, "attempts": [{"engine": "reserve", "ok": True, "error": None, "ms": 0}]}
