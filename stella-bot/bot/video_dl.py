"""Видео по ссылке из чата: TikTok и YouTube скачиваются (yt-dlp) и уходят ответом на сообщение со ссылкой.

yt-dlp работает в отдельном процессе со своим временем и без ключей в окружении; разрешены только извлекатели
YouTube и TikTok (никаких «скачай что угодно по любой ссылке» — внутренние адреса сервера недоступны).
Видео приводится к тому, что WhatsApp точно покажет: H.264 + AAC в MP4, не больше 720p и VIDEO_DL_MAX_MB.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import sys
import tempfile
import time
from dataclasses import dataclass

log = logging.getLogger("stella.video")

# только ролики: ютуб (обычные, shorts, youtu.be, мобильный) и тикток (полные и короткие ссылки)
LINK_RE = re.compile(
    r"https?://(?:"
    r"(?:www\.|m\.)?youtube\.com/(?:watch\?(?:[^\s]*&)?v=[\w-]{11}|shorts/[\w-]{11}|live/[\w-]{11})"
    r"|youtu\.be/[\w-]{11}"
    r"|(?:www\.|m\.)?tiktok\.com/@[\w.-]+/(?:video|photo)/\d+"
    r"|(?:vm|vt)\.tiktok\.com/[\w-]+"
    r"|(?:www\.)?tiktok\.com/t/[\w-]+"
    r")[^\s<>\"']*",
    re.IGNORECASE,
)
EXTRACTORS = "youtube,YoutubeYtBe,TikTok,vm.tiktok"
DL_TIMEOUT = 150  # скачивание целиком
FIX_TIMEOUT = 180  # перекодирование, если формат не подходит WhatsApp
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
PASS_ENV = ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy", "SSL_CERT_FILE",
            "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


class VideoError(Exception):
    """Не получилось: kind — blocked (сайт не пускает сервер), too_long, too_big, unavailable, failed."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass
class Video:
    data: bytes
    title: str
    site: str  # youtube | tiktok


def find_links(text: str, limit: int = 1) -> list[str]:
    """Ссылки на ролики в сообщении (по порядку, без повторов)."""
    out: list[str] = []
    for m in LINK_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,!?;:)»")
        if url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


def site_of(url: str) -> str:
    return "tiktok" if "tiktok" in url.lower() else "youtube"


def _env(tmp: str) -> dict[str, str]:
    """Чистое окружение: без ключей бота. PATH — с папкой, где лежит deno (его ставит pip рядом с python)."""
    bindir = os.path.dirname(sys.executable)
    env = {"PATH": f"{bindir}:{os.environ.get('PATH', SAFE_PATH)}", "HOME": tmp, "LANG": "C.UTF-8",
           "XDG_CACHE_HOME": tmp, "PYTHONDONTWRITEBYTECODE": "1"}
    for name in PASS_ENV:  # сеть сервера (прокси, свои сертификаты) — это не секреты бота
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


async def _run(cmd: list[str], *, timeout: float, env: dict[str, str], cwd: str) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=env, cwd=cwd, start_new_session=True,
        preexec_fn=lambda: os.nice(10),
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError as exc:
        raise VideoError("failed", "слишком долго скачивается") from exc
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # и deno, и ffmpeg — вся группа
        except (ProcessLookupError, PermissionError):
            pass
        if proc.returncode is None:
            await proc.wait()
    return proc.returncode or 0, out, err


def _classify(err: str) -> VideoError:
    low = err.lower()
    if "confirm your age" in low or "age-restricted" in low or "age restricted" in low:
        return VideoError("unavailable", "видео 18+ — без входа в аккаунт не скачать")
    if "sign in to confirm" in low or "ip address is blocked" in low or "http error 429" in low or "403" in low:
        return VideoError("blocked", "сайт не пускает сервер (нужен вход или блок по IP)")
    if "does not pass filter" in low or "duration" in low and "filter" in low:
        return VideoError("too_long", "видео слишком длинное")
    if "file is larger than max-filesize" in low or "max-filesize" in low:
        return VideoError("too_big", "видео слишком большое")
    if any(s in low for s in ("private video", "video is private", "video unavailable", "been removed",
                              "is not available", "not available in your country", "no video formats",
                              "confirm your age", "age-restricted", "age restricted", "members-only")):
        return VideoError("unavailable", "видео недоступно (удалено, приватное или с ограничением)")
    return VideoError("failed", "не получилось скачать")


async def download(url: str, *, max_seconds: int = 300, max_mb: int = 45, cookies: str = "") -> Video:
    """Скачать ролик и привести к H.264/AAC MP4 ≤ 720p и ≤ max_mb. VideoError — если не вышло."""
    if not LINK_RE.fullmatch(url) and not LINK_RE.match(url):
        raise VideoError("failed", "это не ссылка на TikTok или YouTube")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VideoError("failed", "на сервере нет ffmpeg")
    tmp = tempfile.mkdtemp(prefix="stella-dl-")
    try:
        env = _env(tmp)
        cmd = [sys.executable, "-I", "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-cache-dir",
               "--use-extractors", EXTRACTORS, "--match-filter", f"duration<={int(max_seconds)} & !is_live",
               "--max-filesize", f"{int(max_mb * 2)}M",
               "-S", "res:720,vcodec:h264,acodec:aac,ext:mp4:m4a", "--merge-output-format", "mp4",
               "--ffmpeg-location", ffmpeg, "-o", os.path.join(tmp, "v.%(ext)s"),
               "--socket-timeout", "20", "--retries", "2", "--no-progress", "--no-warnings",
               "--print", "after_move:%(.{filepath,title,vcodec,acodec,height,duration})j"]
        if cookies and os.path.isfile(cookies):  # YouTube на серверах часто просит вход — cookies владельца
            cookie_copy = os.path.join(tmp, "cookies.txt")
            shutil.copyfile(cookies, cookie_copy)  # yt-dlp дописывает файл — портим копию, не оригинал
            cmd += ["--cookies", cookie_copy]
        cmd += ["--", url]
        code, out, err = await _run(cmd, timeout=DL_TIMEOUT, env=env, cwd=tmp)
        info: dict = {}
        for line in out.decode(errors="replace").splitlines()[::-1]:
            try:
                info = json.loads(line)
                break
            except ValueError:
                continue
        path = info.get("filepath") or ""
        if code != 0 or not path or not os.path.isfile(path) or not path.startswith(tmp):
            # «не прошло фильтр по длине» и «больше max-filesize» yt-dlp пишет в stdout, ошибки — в stderr
            text = err.decode(errors="replace") + "\n" + out.decode(errors="replace")
            log.info("видео не скачалось (%s): %s", site_of(url), text.strip().splitlines()[-1:] or code)
            raise _classify(text)
        path = await _fix_for_whatsapp(path, info, tmp, ffmpeg, env, max_mb)
        with open(path, "rb") as f:
            data = f.read()
        return Video(data=data, title=str(info.get("title") or "")[:200], site=site_of(url))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _fix_for_whatsapp(path: str, info: dict, tmp: str, ffmpeg: str, env: dict, max_mb: int) -> str:
    """H.264 + AAC и размер ≤ max_mb: иначе перекодируем (720p, а если не влезло — 480p и сильнее сжатие)."""
    limit = max_mb * 1024 * 1024
    vcodec = str(info.get("vcodec") or "").lower()
    acodec = str(info.get("acodec") or "").lower()
    good_codecs = vcodec.startswith(("avc", "h264")) and (acodec in ("", "none") or acodec.startswith(("mp4a", "aac")))
    if good_codecs and os.path.getsize(path) <= limit:
        return path
    duration = float(info.get("duration") or 0)
    for height, crf in ((720, 26), (480, 30)):
        out = os.path.join(tmp, f"fixed{height}.mp4")
        vf = f"scale=-2:'min({height},ih)'"
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", path, "-vf", vf,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-profile:v", "main",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", "-threads", "2"]
        if duration > 0:  # потолок битрейта, чтобы точно влезть в лимит
            kbps = max(300, int(limit * 8 / 1000 / duration * 0.9) - 100)
            cmd += ["-maxrate", f"{kbps}k", "-bufsize", f"{2 * kbps}k"]
        cmd += [out]
        code, _, err = await _run(cmd, timeout=FIX_TIMEOUT, env=env, cwd=tmp)
        if code != 0 or not os.path.isfile(out):
            log.info("видео не перекодировалось: %s", err.decode(errors="replace")[-300:])
            raise VideoError("failed", "не получилось переделать видео для WhatsApp")
        if os.path.getsize(out) <= limit:
            return out
    raise VideoError("too_big", "видео слишком большое для WhatsApp")


class Downloader:
    """Очередь скачиваний на весь бот: по одному за раз, не больше QUEUE_MAX ждущих."""

    QUEUE_MAX = 4

    def __init__(self) -> None:
        self._lock: asyncio.Lock | None = None
        self._loop = None
        self.waiting = 0
        self.recent: dict[tuple[int, str], float] = {}  # (чат, ссылка) -> когда уже скачивали
        self.blocked_note_at: float = -1e9  # когда последний раз говорили владельцу про блокировку

    def lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:  # новый цикл событий (тесты, перезапуск)
            self._lock, self._limit_lock, self._loop = asyncio.Lock(), asyncio.Lock(), loop
        return self._lock

    def limit_lock(self) -> asyncio.Lock:
        self.lock()
        return self._limit_lock

    def seen_recently(self, chat_id: int, url: str, window: float = 600) -> bool:
        now = time.monotonic()
        self.recent = {k: v for k, v in self.recent.items() if now - v < window}
        key = (chat_id, url)
        if key in self.recent:
            return True
        self.recent[key] = now
        return False

    async def fetch(self, url: str, **kw) -> Video:
        if self.waiting >= self.QUEUE_MAX:
            raise VideoError("failed", "сейчас много видео в очереди, скинь чуть позже")
        self.waiting += 1
        waiting = True
        try:
            async with self.lock():
                self.waiting -= 1
                waiting = False
                return await download(url, **kw)
        finally:
            if waiting:
                self.waiting -= 1
