"""Музыкальный плеер на mpv (JSON IPC): очередь треков, радио, подкасты, аудиокниги,
приглушение музыки, когда Стелла слушает или говорит, и мультирум через Snapcast."""
from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("stella.player")


@dataclass
class Track:
    title: str
    artist: str = ""
    url: str | None = None
    resolver: Callable[[], str] | None = None   # ленивое получение ссылки (у Яндекс Музыки она живёт недолго)
    source: str = "local"                        # yandex / radio / podcast / audiobook / local / url
    id: str | None = None
    start: float = 0.0
    meta: dict = field(default_factory=dict)

    def display(self) -> str:
        return f"{self.artist} — {self.title}" if self.artist else self.title

    def resolve(self) -> str | None:
        if self.resolver is not None:
            try:
                self.url = self.resolver()
            except Exception as e:
                log.warning("Не удалось получить ссылку на «%s»: %s", self.title, e)
                return None
        return self.url


class MPV:
    """Минимальный клиент JSON IPC для mpv."""

    def __init__(self, extra_args: list[str] | None = None, volume: int = 70):
        if not shutil.which("mpv"):
            raise RuntimeError("Не найден mpv (sudo apt install mpv)")
        self.sock_path = os.path.join(tempfile.gettempdir(), f"stella-mpv-{os.getpid()}.sock")
        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)
        args = ["mpv", "--idle=yes", "--no-video", "--no-terminal", "--audio-display=no",
                f"--input-ipc-server={self.sock_path}", f"--volume={volume}", "--volume-max=130",
                "--cache=yes", "--demuxer-max-bytes=8MiB"] + (extra_args or [])
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.sock = None
        for _ in range(60):
            if os.path.exists(self.sock_path):
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.connect(self.sock_path)
                    self.sock = s
                    break
                except OSError:
                    pass
            time.sleep(0.05)
        if self.sock is None:
            self.proc.kill()
            raise RuntimeError("mpv не запустился")
        self._req = 0
        self._pending: dict[int, list] = {}
        self._lock = threading.Lock()
        self.on_event: Callable[[dict], None] = lambda ev: None
        threading.Thread(target=self._reader, daemon=True, name="mpv-ipc").start()

    def _reader(self):
        buf = b""
        while True:
            try:
                data = self.sock.recv(65536)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "request_id" in msg and msg["request_id"] in self._pending:
                    slot = self._pending[msg["request_id"]]
                    slot.append(msg)
                    slot[0].set()
                elif "event" in msg:
                    try:
                        self.on_event(msg)
                    except Exception:
                        log.exception("ошибка обработчика события mpv")

    def command(self, *args, timeout: float = 3.0):
        with self._lock:
            self._req += 1
            rid = self._req
            ev = threading.Event()
            self._pending[rid] = [ev]
            try:
                self.sock.sendall((json.dumps({"command": list(args), "request_id": rid}) + "\n").encode())
            except OSError as e:
                self._pending.pop(rid, None)
                raise RuntimeError(f"mpv недоступен: {e}")
        ev.wait(timeout)
        slot = self._pending.pop(rid, [None])
        if len(slot) > 1:
            msg = slot[1]
            if msg.get("error") not in (None, "success"):
                raise RuntimeError(msg.get("error"))
            return msg.get("data")
        return None

    def get(self, prop: str, default=None):
        try:
            return self.command("get_property", prop)
        except RuntimeError:
            return default

    def set(self, prop: str, value):
        return self.command("set_property", prop, value)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self):
        try:
            self.command("quit", timeout=1)
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


class MusicPlayer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.queue: list[Track] = []
        self.index = -1
        self.volume = 60
        self.ducked = False
        self.mode = "list"
        self.refill: Callable[[], list[Track]] | None = None
        self.on_track: list[Callable[[Track], None]] = []
        self.position_saver: Callable[[Track, float], None] | None = None
        self.multiroom = False
        self._mpv: MPV | None = None
        self._lock = threading.RLock()
        self._errors = 0
        self._paused_by_user = False
        self._stopped = True
        threading.Thread(target=self._position_loop, daemon=True, name="player-pos").start()

    # ---------------------------------------------------------- mpv --
    def _ensure(self) -> MPV:
        if self._mpv is None or not self._mpv.alive():
            extra = []
            if self.multiroom:
                fifo = self.cfg.get("multiroom.fifo", "/tmp/snapfifo")
                extra = ["--ao=pcm", f"--ao-pcm-file={fifo}", "--ao-pcm-waveheader=no",
                         "--audio-samplerate=48000", "--audio-format=s16", "--audio-channels=stereo"]
            self._mpv = MPV(extra, self.volume)
            self._mpv.on_event = self._on_event
        return self._mpv

    def _on_event(self, ev: dict):
        if ev.get("event") == "end-file":
            reason = ev.get("reason")
            if reason == "eof":
                self._errors = 0
                threading.Thread(target=self._advance, daemon=True).start()
            elif reason == "error":
                self._errors += 1
                log.warning("mpv не смог воспроизвести трек (ошибок подряд: %s)", self._errors)
                if self._errors < 4:
                    threading.Thread(target=self._advance, daemon=True).start()

    def _advance(self):
        with self._lock:
            if self._stopped:
                return
            cur = self.current()
            if cur and cur.source == "audiobook" and self.position_saver:
                self.position_saver(cur, -1)  # глава дослушана
            if self.index + 1 >= len(self.queue) and self.refill:
                try:
                    more = self.refill() or []
                except Exception as e:
                    log.warning("Не удалось получить ещё треков: %s", e)
                    more = []
                self.queue.extend(more)
            if self.index + 1 < len(self.queue):
                self._play_index(self.index + 1)
            else:
                self._stopped = True
                log.info("Очередь закончилась")

    def _play_index(self, i: int) -> bool:
        with self._lock:
            if not (0 <= i < len(self.queue)):
                return False
            track = self.queue[i]
            url = track.resolve()
            if not url:
                self._errors += 1
                if self._errors < 4 and i + 1 < len(self.queue):
                    return self._play_index(i + 1)
                return False
            self.index = i
            self._stopped = False
            m = self._ensure()
            opts = f"start={track.start}" if track.start else ""
            if opts:
                m.command("loadfile", url, "replace", opts)
            else:
                m.command("loadfile", url, "replace")
            m.set("pause", False)
            self._paused_by_user = False
            log.info("Играет: %s", track.display())
            for cb in self.on_track:
                try:
                    cb(track)
                except Exception:
                    log.exception("on_track")
            return True

    # -------------------------------------------------------------- API --
    def play(self, tracks: list[Track], mode: str = "list", refill=None, start_index: int = 0) -> bool:
        with self._lock:
            self.queue = list(tracks)
            self.mode = mode
            self.refill = refill
            self._errors = 0
            return self._play_index(start_index)

    def enqueue(self, tracks: list[Track]):
        with self._lock:
            self.queue.extend(tracks)
            if self._stopped:
                self._play_index(len(self.queue) - len(tracks))

    def current(self) -> Track | None:
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    def next(self) -> bool:
        with self._lock:
            if self.index + 1 >= len(self.queue) and self.refill:
                self.queue.extend(self.refill() or [])
            return self._play_index(self.index + 1)

    def prev(self) -> bool:
        with self._lock:
            pos = self.position()
            if pos and pos > 5:
                self.seek(0, relative=False)
                return True
            return self._play_index(max(0, self.index - 1))

    def pause(self):
        if self._mpv and self._mpv.alive():
            self._mpv.set("pause", True)
            self._paused_by_user = True

    def resume(self):
        if self._mpv and self._mpv.alive() and not self._stopped:
            self._mpv.set("pause", False)
            self._paused_by_user = False
            return True
        return False

    def stop(self):
        with self._lock:
            cur = self.current()
            if cur and cur.source == "audiobook" and self.position_saver:
                self.position_saver(cur, self.position() or 0)
            self._stopped = True
            if self._mpv and self._mpv.alive():
                try:
                    self._mpv.command("stop")
                except RuntimeError:
                    pass

    def is_playing(self) -> bool:
        if self._stopped or not self._mpv or not self._mpv.alive():
            return False
        return not self._mpv.get("pause", False) and not self._mpv.get("idle-active", True)

    def is_active(self) -> bool:
        """Есть что продолжать (играет или на паузе)."""
        return not self._stopped and self._mpv is not None and self._mpv.alive()

    def position(self) -> float | None:
        return self._mpv.get("time-pos") if self._mpv and self._mpv.alive() else None

    def seek(self, seconds: float, relative: bool = True):
        if self._mpv and self._mpv.alive():
            self._mpv.command("seek", seconds, "relative" if relative else "absolute")

    def stream_title(self) -> str | None:
        """Название песни из потока интернет-радио (ICY)."""
        if not self._mpv:
            return None
        return self._mpv.get("metadata/by-key/icy-title") or self._mpv.get("media-title")

    def set_volume(self, v: int):
        self.volume = max(0, min(130, int(v)))
        if self._mpv and self._mpv.alive() and not self.ducked:
            self._mpv.set("volume", self.volume)

    def duck(self):
        if self._mpv and self._mpv.alive() and not self.ducked:
            self.ducked = True
            try:
                self._mpv.set("volume", min(self.volume, int(self.cfg.get("audio.duck_volume", 25))))
            except RuntimeError:
                pass

    def unduck(self):
        if self._mpv and self._mpv.alive() and self.ducked:
            self.ducked = False
            try:
                self._mpv.set("volume", self.volume)
            except RuntimeError:
                pass

    def set_multiroom(self, on: bool):
        if on == self.multiroom:
            return
        with self._lock:
            cur, pos = self.current(), self.position() or 0
            playing = self.is_playing()
            self.multiroom = on
            if self._mpv:
                self._mpv.close()
                self._mpv = None
            if cur and playing:
                cur.start = pos
                self._play_index(self.index)
                cur.start = 0

    def _position_loop(self):
        """Раз в 15 с сохраняем место в аудиокниге."""
        while True:
            time.sleep(15)
            try:
                cur = self.current()
                if cur and cur.source == "audiobook" and self.position_saver and self.is_playing():
                    self.position_saver(cur, self.position() or 0)
            except Exception:
                pass

    def close(self):
        self.stop()
        if self._mpv:
            self._mpv.close()
