"""Видео по ссылке: TikTok/YouTube скачивается и уходит ответом на сообщение со ссылкой."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from bot import video_dl
from bot.video_dl import VideoError, find_links

from .conftest import OWNER, PETYA, settle, upsert

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
    ("https://m.tiktok.com/@a/video/7312345678901234567", "https://m.tiktok.com/@a/video/7312345678901234567"),
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
    "https://www.tiktok.com/@user", "https://www.tiktok.com/@a/photo/7312345678901234567",
])
def test_ignores_other_links(text):
    assert find_links(text) == []


def test_same_video_same_key_and_canonical_tiktok():
    assert video_dl.video_key("https://youtu.be/jNQXAC9IVRw?si=1") == \
        video_dl.video_key("https://www.youtube.com/watch?feature=x&v=jNQXAC9IVRw&si=2") == "youtube:jNQXAC9IVRw"
    assert video_dl.video_key(TT + "?x=1") == video_dl.video_key(TT) == "tiktok:7312345678901234567"
    assert video_dl.canonical("https://tiktok.com/@a/video/1") == "https://www.tiktok.com/@a/video/1"
    assert video_dl.canonical("https://m.tiktok.com/@a/video/1") == "https://www.tiktok.com/@a/video/1"


def test_regex_is_fast_on_hostile_text():
    hostile = ("https://youtube.com/watch?&" * 20000)[:300_000]
    started = time.monotonic()
    find_links(hostile)
    find_links("https://youtube.com/watch?" + "a&" * 100_000)
    assert time.monotonic() - started < 0.5


def test_error_classes():
    assert video_dl._classify("ERROR: Sign in to confirm you’re not a bot").kind == "blocked"
    assert video_dl._classify("Your IP address is blocked from accessing this post").kind == "blocked"
    assert video_dl._classify("ERROR: unable to download video data: HTTP Error 403: Forbidden").kind == "blocked"
    assert video_dl._classify("ERROR: Private video").kind == "unavailable"
    assert video_dl._classify("Sign in to confirm your age").kind == "unavailable"
    assert video_dl._classify("ERROR: [TikTok] 7403123456789012345: Video not available").kind == "unavailable"
    assert video_dl._classify("ERROR: [TikTok] 7403123456789012345: something odd").kind == "failed"  # «403» в ID
    assert video_dl._classify("ERROR: Unable to download API page: SSL error").kind == "failed"
    assert video_dl._classify("ERROR: 'cookies.txt' does not look like a Netscape format cookies file").kind == "cookies"


# ---------- скачивание (yt-dlp подменён, ffmpeg настоящий) ----------
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")


def _make_video(path: str, codec: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", codec, "-c:a", "aac", "-shortest",
                    path], check=True)


@pytest.fixture
def fake_ytdlp(monkeypatch):
    """Вместо yt-dlp кладём готовый файл и печатаем строки, как yt-dlp; ffmpeg вызывается по-настоящему."""
    state = {"codec": "libx264", "fail": None, "calls": [], "filtered": None}
    real_run = video_dl._run

    async def run(cmd, *, timeout, env, cwd):
        if cmd[0] != sys.executable:
            return await real_run(cmd, timeout=timeout, env=env, cwd=cwd)
        state["calls"].append(cmd)
        assert "--use-extractors" in cmd and cmd[cmd.index("--use-extractors") + 1] == video_dl.EXTRACTORS
        assert cmd[-2] == "--" and "KEY" not in "".join(env)  # ссылка — после «--», ключей в окружении нет
        if state["fail"]:
            return 1, b"", state["fail"].encode()
        if state["filtered"] is not None:  # yt-dlp сам отказался: печатает только P и выходит с 0
            return 0, b"P" + json.dumps(state["filtered"]).encode() + b"\n", b""
        path = os.path.join(cwd, "v.mp4")
        _make_video(path, state["codec"])
        vcodec = "avc1.64001e" if state["codec"] == "libx264" else "mp4v.20.9"
        line = json.dumps({"filepath": path, "title": "Кот танцует", "vcodec": vcodec, "acodec": "mp4a.40.2",
                           "height": 240, "duration": 1.0})
        return 0, b'P{"duration": 1, "is_live": false}\nA' + line.encode() + b"\n", b""

    monkeypatch.setattr(video_dl, "_run", run)
    return state


@needs_ffmpeg
async def test_download_h264_as_is(fake_ytdlp):
    v = await video_dl.download("https://tiktok.com/@cat.lover/video/7312345678901234567")
    assert v.site == "tiktok" and v.title == "Кот танцует" and v.data[4:8] == b"ftyp"
    assert fake_ytdlp["calls"][-1][-1].startswith("https://www.tiktok.com/")  # без www yt-dlp не понимает


@needs_ffmpeg
async def test_download_other_codec_is_reencoded_to_h264(fake_ytdlp):
    fake_ytdlp["codec"] = "mpeg4"
    v = await video_dl.download("https://youtu.be/jNQXAC9IVRw")
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                            "-of", "csv=p=0", "-"], input=v.data, capture_output=True)
    assert probe.stdout.strip() == b"h264"


async def test_filtered_videos_say_why(fake_ytdlp):
    fake_ytdlp["filtered"] = {"duration": 900, "is_live": False}
    with pytest.raises(VideoError) as e:
        await video_dl.download("https://youtu.be/jNQXAC9IVRw", max_seconds=300)
    assert e.value.kind == "too_long" and "5 мин" in str(e.value)
    fake_ytdlp["filtered"] = {"duration": 120, "is_live": False}
    with pytest.raises(VideoError) as e:
        await video_dl.download("https://youtu.be/jNQXAC9IVRw", max_seconds=300)
    assert e.value.kind == "too_big"


async def test_cookies_only_for_youtube_and_only_a_copy(fake_ytdlp, tmp_path):
    fake_ytdlp["fail"] = "ERROR: [youtube] x: Sign in to confirm you’re not a bot"
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    with pytest.raises(VideoError) as e:
        await video_dl.download("https://youtu.be/jNQXAC9IVRw", cookies=str(cookies))
    assert e.value.kind == "blocked"
    cmd = fake_ytdlp["calls"][-1]
    assert "--cookies" in cmd and cmd[cmd.index("--cookies") + 1] != str(cookies)  # копия, а не оригинал
    with pytest.raises(VideoError):
        await video_dl.download(TT, cookies=str(cookies))
    assert "--cookies" not in fake_ytdlp["calls"][-1]  # в TikTok куки ютуба не уходят
    cookies.chmod(0)
    if not os.access(cookies, os.R_OK):  # нечитаемый файл (root, 600) — качаем без него, а не падаем
        with pytest.raises(VideoError):
            await video_dl.download("https://youtu.be/jNQXAC9IVRw", cookies=str(cookies))
        assert "--cookies" not in fake_ytdlp["calls"][-1]
    with pytest.raises(VideoError):
        await video_dl.download("https://example.com/a.mp4")


async def test_queue_is_one_at_a_time_and_fair():
    d = video_dl.Downloader()
    running, peak = [], []

    async def job():
        running.append(1)
        peak.append(len(running))
        await asyncio.sleep(0.02)
        running.pop()
        return "sent"

    results = await asyncio.gather(*(d.run(1, f"k{i}", job) for i in range(4)), return_exceptions=True)
    assert max(peak) == 1
    assert not any(isinstance(r, VideoError) for r in results)  # 1 качается + 3 ждут
    assert d.duplicate(1, "k0") and not d.duplicate(2, "k0") and d.waiting == {}
    assert d.claim(2, "k9") and not d.claim(2, "k9")
    d.release(2, "k9")
    assert d.claim(2, "k9")
    results = await asyncio.gather(*(d.run(1, f"x{i}", job) for i in range(6)), return_exceptions=True)
    assert sum(isinstance(r, VideoError) and r.kind == "queue" for r in results) == 2  # чату — не больше 3 в очереди


# ---------- в чате ----------
@pytest.fixture
def fake_download(monkeypatch):
    state = {"n": 0, "fail": None, "delay": 0.0}

    async def download(url, **kw):
        state["n"] += 1
        await asyncio.sleep(state["delay"])
        if state["fail"]:
            raise VideoError(*state["fail"])
        return video_dl.Video(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64, "Смешной кот", video_dl.site_of(url))

    monkeypatch.setattr(video_dl, "download", download)
    return state


async def test_link_gets_video_reply_quoting_it(brain, fake_download):
    await feed(brain, upsert(f"ахаха гляньте {TT}", msg_id="LINK1"))
    media = [m for m in brain.evo.sent if m["type"] == "media"]
    assert len(media) == 1 and media[0]["mimetype"] == "video/mp4" and media[0]["caption"] == ""
    assert media[0]["quoted"]["key"]["id"] == "LINK1"  # ответом на сообщение со ссылкой
    assert brain.llm.calls == []  # просто ссылка в группе — она не встревает, только присылает видео
    chat = await brain.db.get_chat_by_jid("stella", "120363000000000001@g.us")
    last = (await brain.db.recent_messages(chat["id"], 1))[0]
    assert last["text"] == "[видео из TikTok по ссылке из сообщения выше]" and last["quoted_wa_id"] == "LINK1"


async def test_same_video_by_different_links_once(brain, fake_download):
    await feed(brain, upsert("https://youtu.be/jNQXAC9IVRw?si=a"),
               upsert("https://www.youtube.com/watch?v=jNQXAC9IVRw&si=b", sender=PETYA, name="Петя"))
    assert fake_download["n"] == 1 and len([m for m in brain.evo.sent if m["type"] == "media"]) == 1


async def test_failed_link_can_be_retried(brain, fake_download):
    fake_download["fail"] = ("failed", "не получилось скачать")
    await feed(brain, upsert(TT))
    fake_download["fail"] = None
    await feed(brain, upsert(TT))
    assert fake_download["n"] == 2 and len([m for m in brain.evo.sent if m["type"] == "media"]) == 1


async def test_failure_is_silent_unless_asked_and_owner_told_once_per_site(brain, fake_download):
    fake_download["fail"] = ("blocked", "сайт не пускает сервер (нужен вход или блок по IP)")
    brain.connection_state = "open"
    await feed(brain, upsert(TT))
    owner_msgs = [m for m in brain.evo.sent if m["type"] == "text" and m["to"].startswith(OWNER)]
    group_msgs = [m for m in brain.evo.sent if m["to"].endswith("@g.us")]
    assert len(owner_msgs) == 1 and "TikTok" in owner_msgs[0]["text"] and group_msgs == []
    brain.llm.queue = ["щас гляну"]
    await feed(brain, upsert("стелла скачай https://www.tiktok.com/@a/video/111111"))
    assert any("не получилось скачать видео" in t for t in brain.evo.texts())
    await feed(brain, upsert("https://youtu.be/jNQXAC9IVRw"))
    owner_msgs = [m["text"] for m in brain.evo.sent if m["type"] == "text" and m["to"].startswith(OWNER)]
    assert len(owner_msgs) == 2 and "cookies" in owner_msgs[1]  # у ютуба своё предупреждение


async def test_limits_count_attempts(brain, fake_download):
    fake_download["fail"] = ("failed", "не получилось скачать")
    brain.s.video_dl_per_day = 2
    await feed(brain, *(upsert(f"https://youtu.be/aaaaaaaaaa{i}") for i in range(5)))
    assert fake_download["n"] == 2  # неудачные попытки тоже считаются — иначе можно гонять загрузки бесконечно
    brain.s.video_dl_per_day = 100
    brain.downloader.PER_SENDER_DAY = 3
    await feed(brain, *(upsert(f"https://youtu.be/bbbbbbbbbb{i}") for i in range(5)))
    assert fake_download["n"] == 3  # с одного человека — не больше PER_SENDER_DAY в сутки
    await feed(brain, upsert("https://youtu.be/ccccccccccc", sender=f"{OWNER}@s.whatsapp.net", name="Хозяин"))
    assert fake_download["n"] == 4  # владельцу — без лимита на человека
    brain.s.video_dl_enabled = False
    await feed(brain, upsert("https://youtu.be/ddddddddddd", sender=PETYA, name="Петя"))
    assert fake_download["n"] == 4


async def test_paused_chat_gets_nothing(brain, fake_download):
    from datetime import timedelta

    from bot.util import utcnow

    fake_download["delay"] = 0.2
    fake_download["fail"] = ("failed", "не получилось скачать")
    brain.llm.queue = ["ок"]
    await brain.handle_payload(upsert("стелла скачай " + TT))
    chat = await brain.db.get_chat_by_jid("stella", "120363000000000001@g.us")
    await brain.db.update_chat(chat["id"], paused_until=utcnow() + timedelta(minutes=5))
    await settle(brain, timeout=20)
    assert not any("не получилось скачать" in t for t in brain.evo.texts())  # на паузе молчит и об ошибке
    await feed(brain, upsert(TT))
    assert not [m for m in brain.evo.sent if m["type"] == "media"]


async def test_prompt_mentions_links_only_when_enabled(brain):
    from bot.persona import minimal_prompt

    assert "TikTok" in minimal_prompt(brain.s) and "не выдумывай" in minimal_prompt(brain.s)
    brain.s.video_dl_enabled = False
    assert "TikTok" not in minimal_prompt(brain.s)
