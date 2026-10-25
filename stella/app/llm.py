import base64

import httpx

from . import config


async def chat(messages: list[dict], tools: list[dict] | None = None, model: str | None = None,
               max_tokens: int = 400) -> dict:
    body = {"model": model or config.LLM_MODEL, "messages": messages, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{config.LLM_BASE_URL}/chat/completions", json=body,
                         headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"})
        if r.status_code >= 400:
            # в логах нужна причина от провайдера (неверная модель, лимит, ключ), а не только код
            raise RuntimeError(f"LLM {r.status_code} model={body['model']}: {r.text[:400]}")
        return r.json()["choices"][0]["message"]


def image_part(img: bytes, mime: str = "image/jpeg") -> dict:
    return {"type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{base64.b64encode(img).decode()}"}}


async def see(prompt: str, img: bytes, mime: str = "image/jpeg") -> str:
    msg = await chat([{"role": "user", "content": [{"type": "text", "text": prompt}, image_part(img, mime)]}],
                     model=config.VISION_MODEL, max_tokens=300)
    return (msg.get("content") or "").strip()
