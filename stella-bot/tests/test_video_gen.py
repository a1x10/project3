"""Видео нейросетью (HeyGen через OpenRouter): задание → опрос → скачивание; просьба «сделай видео» — наверняка."""

import json

import httpx
import pytest

from bot import video_gen
from bot.keys import STORE, KeyStore
from bot.media_tools import wants_video

KEY = "sk-or-v1-" + "v" * 40
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"0" * 100


async def test_job_poll_download():
    store = KeyStore()
    await store.add("openrouter", KEY)
    calls = []
    polls = iter(["pending", "in_progress", "completed"])

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "POST":
            body = json.loads(req.content)
            assert body == {"model": "heygen/heygen-video-1", "prompt": "a cat dancing", "duration": 5,
                            "resolution": "480p", "aspect_ratio": "9:16"}
            return httpx.Response(202, json={"id": "job1", "status": "pending"})
        if req.url.path.endswith("/content"):
            return httpx.Response(200, content=MP4)
        status = next(polls)
        return httpx.Response(200, json={"status": status, "usage": {"cost": 0.1}})

    data, cost = await video_gen.generate("a cat dancing", "tall", 5, "480p", store, "heygen/heygen-video-1",
                                          poll_every=0, transport=httpx.MockTransport(handler))
    assert data == MP4 and cost == 0.1
    assert calls[0] == ("POST", "/api/v1/videos") and calls[-1] == ("GET", "/api/v1/videos/job1/content")


async def test_failed_job_reports_error():
    store = KeyStore()
    await store.add("openrouter", KEY)

    def handler(req):
        if req.method == "POST":
            return httpx.Response(202, json={"id": "j"})
        return httpx.Response(200, json={"status": "failed", "error": {"message": "content policy"}})

    with pytest.raises(video_gen.VideoGenError, match="content policy"):
        await video_gen.generate("x", "wide", 5, "480p", store, "m", poll_every=0,
                                 transport=httpx.MockTransport(handler))
    assert video_gen.estimate_cost(5, "480p") == 0.1


def test_wants_video():
    assert wants_video("стелла сделай видео как кот танцует") and wants_video("сгенерируй короткий ролик про море")
    assert not wants_video("сделай мультик") and not wants_video("скинь видео https://youtu.be/x")
    assert not wants_video("как дела")


async def test_video_request_is_queued_even_if_model_forgets(brain, monkeypatch):
    from .conftest import VASYA, settle, upsert

    async def fake_generate(prompt, shape, seconds, resolution, store, model, **kw):
        fake_generate.calls.append((prompt, shape, seconds, resolution))
        return MP4, 0.1
    fake_generate.calls = []
    monkeypatch.setattr(video_gen, "generate", fake_generate)
    await STORE.add("openrouter", KEY)
    try:
        brain.llm.queue = ["щас"]
        await brain.handle_payload(upsert("стелла сделай видео как кот танцует", chat=VASYA, sender=VASYA))
        await settle(brain)
        assert "обязательно вызови make_ai_video" in brain.llm.calls[-1]["prompt"]
        assert fake_generate.calls and fake_generate.calls[0][1:] == ("tall", 5, "480p")
        assert [m for m in brain.evo.sent if m["type"] == "media" and m.get("mediatype") == "video"]
    finally:
        STORE.keys = []
