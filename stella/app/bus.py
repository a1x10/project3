"""Шина пушей: сервер -> очки/телефон через SSE.
Типы событий: hud, speak, action, scan, photo, card, suggest."""
import asyncio
import json

_subs: set[asyncio.Queue] = set()


def publish(type_: str, **data) -> None:
    msg = json.dumps({"type": type_, **data}, ensure_ascii=False)
    for q in list(_subs):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            _subs.discard(q)


async def stream():
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subs.add(q)
    try:
        yield "retry: 3000\n\n"
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=20)
                yield f"data: {msg}\n\n"
            except asyncio.TimeoutError:
                yield ": ping\n\n"   # keep-alive, чтобы прокси не рвали канал
    finally:
        _subs.discard(q)
