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
    r"(?:www\.|m\.)?youtube\.com/(?:watch\?(?:[^\s&#]{0,200}&){0,20}v=([\w-]{11})|shorts/([\w-]{11})|live/([\w-]{11}))"
    r"|youtu\.be/([\w-]{11})"
    r"|(?:www\.|m\.)?tiktok\.com/@[\w.-]{1,64}/video/(\d{5,25})"
    r"|(?:vm|vt)\.tiktok\.com/([\w-]{1,32})"
    r"|(?:www\.)?tiktok\.com/t/([\w-]{1,32})"
    r")[^\s<>\"']{0,300}",
    re.IGNORECASE,
)
MAX_SCAN = 4000  # дальше в длинном сообщении ссылки не ищем (и регулярка не тормозит бота)
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
    for m in LINK_RE.finditer((text or "")[:MAX_SCAN]):
        url = m.group(0).rstrip(".,!?;:)»")
        if url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


def video_key(url: str) -> str:
    """Один и тот же ролик по разным ссылкам (?si=…, ?is_from_webapp=…) — один ключ: сайт + ID."""
    m = LINK_RE.search(url)
    if m:
        ident = next((g for g in m.groups() if g), "")
        if ident:
            return f"{site_of(url)}:{ident}"
    return url


def canonical(url: str) -> str:
    """tiktok.com/@… и m.tiktok.com/@… yt-dlp понимает только с www — переписываем."""
    return re.sub(r"^https?://(?:m\.)?tiktok\.com/", "https://www.tiktok.com/", url, flags=re.IGNORECASE)


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
    if "cookies" in low and ("netscape" in low or "invalid" in low or "load" in low or "format" in low):
        return VideoError("cookies", "файл cookies не подходит")
    if any(s in low for s in ("private video", "video is private", "video unavailable", "been removed",
                              "not available", "no video formats",
                              "members-only")):
        return VideoError("unavailable", "видео недоступно (удалено, приватное или с ограничением)")
    if any(s in low for s in ("sign in to confirm", "ip address is blocked", "http error 429", "http error 403",
                              "403: forbidden")):
        return VideoError("blocked", "сайт не пускает сервер (нужен вход или блок по IP)")
    if "does not pass filter" in low:
        return VideoError("too_long", "видео слишком длинное")
    if "max-filesize" in low:
        return VideoError("too_big", "видео слишком большое")
    return VideoError("failed", "не получилось скачать")


async def download(url: str, *, max_seconds: int = 300, max_mb: int = 30, cookies: str = "") -> Video:
    """Скачать ролик и привести к H.264/AAC MP4 ≤ 720p и ≤ max_mb. VideoError — если не вышло."""
    if not LINK_RE.match(url):
        raise VideoError("failed", "это не ссылка на TikTok или YouTube")
    url = canonical(url)
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
               # P — до фильтра по длине (чтобы понять, почему не скачалось), A — готовый файл
               "--print", "pre_process:P%(.{duration,is_live})j",
               "--print", "after_move:A%(.{filepath,title,vcodec,acodec,height,duration})j"]
        if cookies and site_of(url) == "youtube" and os.path.isfile(cookies):  # YouTube на серверах просит вход
            cookie_copy = os.path.join(tmp, "cookies.txt")
            try:
                shutil.copyfile(cookies, cookie_copy)  # yt-dlp дописывает файл — портим копию, не оригинал
                cmd += ["--cookies", cookie_copy]
            except OSError as exc:
                log.warning("cookies для YouTube не читаются (%s) — качаю без них", exc)
        cmd += ["--", url]
        code, out, err = await _run(cmd, timeout=DL_TIMEOUT, env=env, cwd=tmp)
        pre: dict = {}
        info: dict = {}
        for line in out.decode(errors="replace").splitlines():
            try:
                if line.startswith("P"):
                    pre = json.loads(line[1:])
                elif line.startswith("A"):
                    info = json.loads(line[1:])
            except ValueError:
                continue
        path = info.get("filepath") or ""
        if code != 0 or not path or not os.path.isfile(path) or not path.startswith(tmp):
            text = err.decode(errors="replace")
            log.info("видео не скачалось (%s): %s", site_of(url), text.strip().splitlines()[-1:] or code)
            if code == 0 and pre:  # yt-dlp сам отказался: длинное/эфир или файл больше лимита
                if pre.get("is_live") or float(pre.get("duration") or 0) > max_seconds:
                    raise VideoError("too_long", f"видео длиннее {max_seconds // 60} мин — такие не качаю")
                raise VideoError("too_big", "видео слишком большое для WhatsApp")
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
    """Очередь скачиваний на весь бот: качает по одному; у каждого чата и человека — свои места и лимиты."""

    QUEUE_MAX = 12  # всего ждущих
    PER_CHAT_WAITING = 3
    PER_SENDER_DAY = 10  # попыток с одного человека в сутки (во всех чатах)
    GLOBAL_DAY = 300  # попыток на весь бот в сутки

    def __init__(self) -> None:
        self._lock: asyncio.Lock | None = None
        self._limit_lock: asyncio.Lock | None = None
        self._loop = None
        self.waiting: dict[int, int] = {}  # чат -> сколько ждут
        self.in_flight: set[tuple[int, str]] = set()  # (чат, ролик) — качается или ждёт
        self.sent: dict[tuple[int, str], float] = {}  # (чат, ролик) -> когда прислали
        self.note_at: dict[str, float] = {}  # сайт -> когда последний раз писали владельцу

    def lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:  # новый цикл событий (тесты, перезапуск)
            self._lock, self._limit_lock, self._loop = asyncio.Lock(), asyncio.Lock(), loop
        return self._lock

    def limit_lock(self) -> asyncio.Lock:
        self.lock()
        assert self._limit_lock is not None
        return self._limit_lock

    def duplicate(self, chat_id: int, key: str, window: float = 600) -> bool:
        """Этот ролик в этом чате уже качается или его только что прислали."""
        now = time.monotonic()
        self.sent = {k: v for k, v in self.sent.items() if now - v < window}
        return (chat_id, key) in self.in_flight or (chat_id, key) in self.sent

    def claim(self, chat_id: int, key: str) -> bool:
        """Занять ролик для этого чата (без await — две одинаковые ссылки подряд не проскочат). False — дубль."""
        if self.duplicate(chat_id, key):
            return False
        self.in_flight.add((chat_id, key))
        return True

    def release(self, chat_id: int, key: str) -> None:
        self.in_flight.discard((chat_id, key))

    def queue_full(self, chat_id: int) -> bool:
        return (sum(self.waiting.values()) >= self.QUEUE_MAX
                or self.waiting.get(chat_id, 0) >= self.PER_CHAT_WAITING)

    async def run(self, chat_id: int, key: str, job):
        """Выполнить job() в очереди (скачать и отправить — целиком, чтобы два больших видео не висели
        в памяти одновременно). VideoError «queue» — если мест нет."""
        if self.queue_full(chat_id):
            raise VideoError("queue", "сейчас много видео в очереди — скинь чуть позже")
        self.waiting[chat_id] = self.waiting.get(chat_id, 0) + 1
        waiting = True
        try:
            async with self.lock():
                self.waiting[chat_id] -= 1
                waiting = False
                result = await job()
                if result == "sent":
                    self.sent[(chat_id, key)] = time.monotonic()
                return result
        finally:
            if waiting:
                self.waiting[chat_id] -= 1
            if not self.waiting.get(chat_id):
                self.waiting.pop(chat_id, None)
