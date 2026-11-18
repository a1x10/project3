"""Картинки нейросетью через OpenRouter (по тому же ключу, что и модель): по умолчанию Recraft V4.1 Flash V2 —
около $0.007 за картинку. Ключи берутся по очереди, как у модели (bot/keys.py)."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from .keys import base_url_of

log = logging.getLogger("stella.image_gen")

ASPECTS = {"square": "1:1", "wide": "16:9", "tall": "9:16"}
MAX_BYTES = 15 * 1024 * 1024


class ImageGenError(Exception):
    pass


async def generate(prompt: str, shape: str, store: Any, model: str, *, timeout: float = 120,
                   transport: httpx.AsyncBaseTransport | None = None) -> tuple[bytes, str, float | None]:
    """POST /images (OpenRouter) -> (байты картинки, mime, цена в $ или None).
    Лимит/перегрузка/неверный ключ — следующий ключ OpenRouter."""
    keys = store.candidates("openrouter")
    if not keys:
        raise ImageGenError("нет ключа OpenRouter — добавь в панели («Ключи»)")
    body = {"model": model, "prompt": prompt[:2000], "aspect_ratio": ASPECTS.get(shape, "1:1")}
    errors = []
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as http:
        for item in keys:
            try:
                resp = await http.post(f"{base_url_of('openrouter')}/images", json=body,
                                       headers={"Authorization": f"Bearer {item.key}"})
            except httpx.HTTPError as exc:
                errors.append(type(exc).__name__)
                continue
            if resp.status_code in (401, 402, 403, 408, 429, 500, 502, 503, 504):
                errors.append(f"{resp.status_code}: {resp.text[:120]}")
                if resp.status_code in (429, 503):
                    await store.failed(item, f"картинки: лимит/перегрузка ({resp.status_code})", 60)
                continue
            if resp.status_code != 200:
                raise ImageGenError(f"OpenRouter {resp.status_code}: {resp.text[:160]}")
            try:
                data = resp.json()
                first = (data.get("data") or [{}])[0]
                raw = base64.b64decode(first.get("b64_json") or "", validate=False)
                cost = (data.get("usage") or {}).get("cost")
            except (ValueError, AttributeError, IndexError, TypeError) as exc:
                raise ImageGenError("модель не вернула картинку") from exc
            if not raw:
                raise ImageGenError("модель не вернула картинку (возможно, запрос не прошёл её фильтр)")
            if len(raw) > MAX_BYTES:
                raise ImageGenError("картинка слишком большая")
            await store.used(item)
            return raw, str(first.get("media_type") or "image/png"), float(cost) if cost is not None else None
    raise ImageGenError("картинка не получилась: " + "; ".join(errors)[:300])
