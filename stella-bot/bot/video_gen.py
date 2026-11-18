"""Видео нейросетью через OpenRouter (тот же ключ): по умолчанию HeyGen Video (heygen/heygen-video-1).

Задание ставится в очередь (POST /videos), дальше — опрос статуса (GET /videos/{id}) и скачивание
(GET /videos/{id}/content). Цена — за секунду ролика: у HeyGen 480p ≈ $0.02/с, 768p ≈ $0.036/с, 1080p ≈ $0.1/с.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from .keys import base_url_of

log = logging.getLogger("stella.video_gen")

ASPECTS = {"square": "1:1", "wide": "16:9", "tall": "9:16"}
PRICE_PER_SECOND = {"480p": 0.02, "768p": 0.036, "1080p": 0.1, "2K": 0.1}
MAX_BYTES = 45 * 1024 * 1024
POLL_EVERY = 10.0


class VideoGenError(Exception):
    pass


def estimate_cost(seconds: int, resolution: str) -> float:
    return round(seconds * PRICE_PER_SECOND.get(resolution, 0.1), 3)


async def generate(prompt: str, shape: str, seconds: int, resolution: str, store: Any, model: str, *,
                   timeout: float = 600, poll_every: float = POLL_EVERY,
                   transport: httpx.AsyncBaseTransport | None = None) -> tuple[bytes, float | None]:
    """-> (байты mp4, цена в $ или None). Ключи OpenRouter — по очереди (лимит/перегрузка — следующий)."""
    keys = store.candidates("openrouter")
    if not keys:
        raise VideoGenError("нет ключа OpenRouter — добавь в панели («Ключи»)")
    body = {"model": model, "prompt": prompt[:2000], "duration": int(seconds), "resolution": resolution,
            "aspect_ratio": ASPECTS.get(shape, "9:16")}
    base = base_url_of("openrouter")
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=60, transport=transport) as http:
        for item in keys:
            headers = {"Authorization": f"Bearer {item.key}"}
            try:
                resp = await http.post(f"{base}/videos", json=body, headers=headers)
            except httpx.HTTPError as exc:
                errors.append(type(exc).__name__)
                continue
            if resp.status_code in (401, 402, 403, 408, 429, 500, 502, 503, 504):
                errors.append(f"{resp.status_code}: {resp.text[:120]}")
                if resp.status_code in (429, 503):
                    await store.failed(item, f"видео: лимит/перегрузка ({resp.status_code})", 60)
                continue
            if resp.status_code not in (200, 201, 202):
                raise VideoGenError(f"OpenRouter {resp.status_code}: {resp.text[:200]}")
            job = resp.json()
            job_id = str(job.get("id") or "")
            if not job_id:
                raise VideoGenError("OpenRouter не принял задание на видео")
            await store.used(item)
            log.info("видео: задание %s поставлено (%s, %d с, %s)", job_id, model, seconds, resolution)
            return await _wait_and_download(http, base, job_id, headers, timeout, poll_every)
    raise VideoGenError("видео не получилось: " + "; ".join(errors)[:300])


async def _wait_and_download(http: httpx.AsyncClient, base: str, job_id: str, headers: dict[str, str],
                             timeout: float, poll_every: float) -> tuple[bytes, float | None]:
    deadline = time.monotonic() + timeout
    while True:
        await asyncio.sleep(poll_every)
        try:
            resp = await http.get(f"{base}/videos/{job_id}", headers=headers)
        except httpx.HTTPError:
            if time.monotonic() > deadline:
                raise VideoGenError("видео делалось слишком долго") from None
            continue
        state = resp.json() if resp.status_code == 200 else {}
        status = str(state.get("status") or "")
        if status == "completed":
            break
        if status in ("failed", "cancelled", "expired"):
            err = state.get("error")
            msg = err.get("message") if isinstance(err, dict) else err
            raise VideoGenError(f"видео не получилось: {str(msg or status)[:200]}")
        if time.monotonic() > deadline:
            raise VideoGenError("видео делалось слишком долго")
    cost = (state.get("usage") or {}).get("cost")
    resp = await http.get(f"{base}/videos/{job_id}/content", params={"index": 0}, headers=headers, timeout=180)
    if resp.status_code != 200 or not resp.content:
        raise VideoGenError(f"не получилось скачать видео ({resp.status_code})")
    if len(resp.content) > MAX_BYTES:
        raise VideoGenError("видео получилось слишком большим")
    return resp.content, float(cost) if cost is not None else None
