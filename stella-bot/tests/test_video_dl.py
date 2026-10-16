"""Видео по ссылке: TikTok/YouTube скачивается и уходит ответом на сообщение со ссылкой."""

import asyncio
import json
import os
import shutil
import subprocess
import sys

import pytest

from bot import video_dl
from bot.video_dl import VideoError, find_links

from .conftest import OWNER, settle, upsert

TT = "https://www.tiktok.com/@cat.lover/video/7312345678901234567"


async def feed(brain, *payloads):
    for p in payloads:
        await brain.handle_payload(p)
    await settle(brain, timeout=20)


# ---------- ссылки ----------
@pytest.mark.parametrize("text, url", [
    ("гляньте https://www.tiktok.com/@cat.lover/video/7312345678901234567?is_from_webapp=1 ахах",
     "https://www.tiktok.com/@cat.lover/video/7312345678901234567?is_from_webapp=1"),
    ("https://vm.tiktok.com/ZMh3abcDe/", "https://vm.tiktok.com/ZMh3abcDe/"),
    ("https://vt.tiktok.com/ZSabc123/!", "https://vt.tiktok.com/ZSabc123/"),
    ("https://www.tiktok.com/t/ZTRabcdef/", "https://www.tiktok.com/t/ZTRabcdef/"),
    ("смотри https://youtu.be/jNQXAC9IVRw?si=abc.", "https://youtu.be/jNQXAC9IVRw?si=abc"),
    ("https://www.youtube.com/watch?v=jNQXAC9IVRw&t=10", "https://www.youtube.com/watch?v=jNQXAC9IVRw&t=10"),
    ("https://m.youtube.com/watch?feature=share&v=jNQXAC9IVRw", "https://m.youtube.com/watch?feature=share&v=jNQXAC9IVRw"),
    ("https://youtube.com/shorts/nNtHBdXNHUA?feature=share", "https://youtube.com/shorts/nNtHBdXNHUA?feature=share"),
])
def test_finds_video_links(text, url):
    assert find_links(text) == [url]


@pytest.mark.parametrize("text", [
    "https://www.youtube.com/@channel", "https://www.youtube.com/playlist?list=PL123", "https://example.com/v.mp4",
    "https://tiktok.com.evil.example/@a/video/1", "http://127.0.0.1/youtu.be/jNQXAC9IVRw", "просто текст",
    "https://www.tiktok.com/@user",
])
def test_ignores_other_links(text):
    assert find_links(text) == []


def test_error_classes():
    assert video_dl._classify("ERROR: Sign in to confirm you’re not a bot").kind == "blocked"
    assert video_dl._classify("Your IP address is blocked from accessing this post").kind == "blocked"
    assert video_dl._classify("[download] x does not pass filter (duration<=300 & !is_live)").kind == "too_long"
    assert video_dl._classify("File is larger than max-filesize (1 bytes > 2 bytes)").kind == "too_big"
    assert video_dl._classify("ERROR: Private video").kind == "unavailable"
    assert video_dl._classify("что-то странное").kind == "failed"


# ---------- скачивание (yt-dlp подменён, ffmpeg настоящий) ----------
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")


def _make_video(path: str, codec: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", codec, "-c:a", "aac", "-shortest",
                    path], check=True)


@pytest.fixture
def fake_ytdlp(monkeypatch):
    """Вместо yt-dlp кладём готовый файл и печатаем JSON, как yt-dlp; ffmpeg вызывается по-настоящему."""
    state = {"codec": "libx264", "fail": None, "calls": []}
    real_run = video_dl._run

    async def run(cmd, *, timeout, env, cwd):
        if cmd[0] != sys.executable:
            return await real_run(cmd, timeout=timeout, env=env, cwd=cwd)
        state["calls"].append(cmd)
        assert "--use-extractors" in cmd and cmd[cmd.index("--use-extractors") + 1] == video_dl.EXTRACTORS
        assert cmd[-2] == "--" and "KEY" not in "".join(env)  # ссылка — после «--», ключей в окружении нет
        if state["fail"]:
            return 1, b"", state["fail"].encode()
        path = os.path.join(cwd, "v.mp4")
        _make_video(path, state["codec"])
        vcodec = "avc1.64001e" if state["codec"] == "libx264" else "mp4v.20.9"
        line = json.dumps({"filepath": path, "title": "Кот танцует", "vcodec": vcodec, "acodec": "mp4a.40.2",
                           "height": 240, "duration": 1.0})
        return 0, line.encode() + b"\n", b""

    monkeypatch.setattr(video_dl, "_run", run)
    return state


@needs_ffmpeg
async def test_download_h264_as_is(fake_ytdlp):
    v = await video_dl.download(TT)
    assert v.site == "tiktok" and v.title == "Кот танцует" and v.data[4:8] == b"ftyp"


@needs_ffmpeg
async def test_download_other_codec_is_reencoded_to_h264(fake_ytdlp):
    fake_ytdlp["codec"] = "mpeg4"
    v = await video_dl.download("https://youtu.be/jNQXAC9IVRw")
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                            "-of", "csv=p=0", "-"], input=v.data, capture_output=True)
    assert probe.stdout.strip() == b"h264"


async def test_download_errors_and_cookies(fake_ytdlp, tmp_path):
    fake_ytdlp["fail"] = "ERROR: [youtube] x: Sign in to confirm you’re not a bot"
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    with pytest.raises(VideoError) as e:
        await video_dl.download("https://youtu.be/jNQXAC9IVRw", cookies=str(cookies))
    assert e.value.kind == "blocked"
    cmd = fake_ytdlp["calls"][-1]
    assert "--cookies" in cmd and cmd[cmd.index("--cookies") + 1] != str(cookies)  # копия, а не оригинал
    with pytest.raises(VideoError):
        await video_dl.download("https://example.com/a.mp4")


async def test_queue_is_one_at_a_time(monkeypatch):
    d = video_dl.Downloader()
    running = []
    peak = []

    async def slow(url, **kw):
        running.append(url)
        peak.append(len(running))
        await asyncio.sleep(0.05)
        running.remove(url)
        return video_dl.Video(b"x", "", "tiktok")

    monkeypatch.setattr(video_dl, "download", slow)
    await asyncio.gather(*(d.fetch(f"u{i}") for i in range(4)))
    assert max(peak) == 1 and d.waiting == 0
    assert not d.seen_recently(1, "a") and d.seen_recently(1, "a") and not d.seen_recently(2, "a")


# ---------- в чате ----------
@pytest.fixture
def fake_fetch(brain, monkeypatch):
    state = {"n": 0, "fail": None}

    async def fetch(url, **kw):
        state["n"] += 1
        if state["fail"]:
            raise VideoError(*state["fail"])
        return video_dl.Video(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64, "Смешной кот", video_dl.site_of(url))

    monkeypatch.setattr(brain.downloader, "fetch", fetch)
    return state


async def test_link_gets_video_reply_quoting_it(brain, fake_fetch):
    await feed(brain, upsert(f"ахаха гляньте {TT}", msg_id="LINK1"))
    media = [m for m in brain.evo.sent if m["type"] == "media"]
    assert len(media) == 1 and media[0]["mimetype"] == "video/mp4" and media[0]["caption"] == ""
    assert media[0]["quoted"]["key"]["id"] == "LINK1"  # ответом на сообщение со ссылкой
    assert brain.llm.calls == []  # просто ссылка в группе — она не встревает, только присылает видео


async def test_youtube_caption_and_duplicate_link(brain, fake_fetch):
    url = "https://youtu.be/jNQXAC9IVRw"
    await feed(brain, upsert(url), upsert(url))
    media = [m for m in brain.evo.sent if m["type"] == "media"]
    assert len(media) == 1 and media[0]["caption"] == "Смешной кот" and fake_fetch["n"] == 1


async def test_failure_is_silent_unless_asked_and_owner_told_about_block(brain, fake_fetch):
    fake_fetch["fail"] = ("blocked", "сайт не пускает сервер (нужен вход или блок по IP)")
    brain.connection_state = "open"
    await feed(brain, upsert(TT))
    owner_msgs = [m for m in brain.evo.sent if m["type"] == "text" and m["to"].startswith(OWNER)]
    group_msgs = [m for m in brain.evo.sent if m["to"].endswith("@g.us")]
    assert len(owner_msgs) == 1 and "cookies" in owner_msgs[0]["text"] and group_msgs == []
    brain.llm.queue = ["щас гляну"]
    await feed(brain, upsert("стелла скачай https://www.tiktok.com/@a/video/111"))
    assert any("не получилось скачать видео" in t for t in brain.evo.texts())
    assert len([m for m in brain.evo.sent if m["to"].startswith(OWNER)]) == 1  # владельцу — не чаще раза в 6 ч


async def test_daily_limit_and_switch(brain, fake_fetch):
    brain.s.video_dl_per_day = 1
    await feed(brain, upsert("https://youtu.be/aaaaaaaaaaa"), upsert("https://youtu.be/bbbbbbbbbbb"))
    assert fake_fetch["n"] == 1
    brain.s.video_dl_enabled = False
    brain.s.video_dl_per_day = 10
    await feed(brain, upsert("https://youtu.be/ccccccccccc"))
    assert fake_fetch["n"] == 1


async def test_paused_chat_gets_no_video(brain, fake_fetch):
    from datetime import timedelta

    from bot.util import utcnow

    await feed(brain, upsert("привет"))
    chat = await brain.db.get_chat_by_jid("stella", "120363000000000001@g.us")
    await brain.db.update_chat(chat["id"], paused_until=utcnow() + timedelta(minutes=5))
    await feed(brain, upsert(TT))
    assert not [m for m in brain.evo.sent if m["type"] == "media"]


def test_page_errors_are_not_called_unavailable():
    assert video_dl._classify("ERROR: Unable to download API page: SSL error").kind == "failed"
    assert video_dl._classify("Sign in to confirm your age").kind == "unavailable"
