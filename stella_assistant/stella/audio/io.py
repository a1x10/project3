"""Микрофон и динамик.

MicHub — один поток захвата звука (16 кГц, моно), раздаёт блоки всем подписчикам:
распознаванию речи, радионяне, интеркому, Shazam.
Speaker — воспроизведение синтезированной речи с анимацией рта по громкости.
"""
from __future__ import annotations

import logging
import queue
import shutil
import subprocess
import threading
import time
from collections import deque

import numpy as np

from ..core.events import bus
from . import dsp

log = logging.getLogger("stella.audio")

RATE = 16000
BLOCK = 1600  # 100 мс


def _sd():
    try:
        import sounddevice as sd
        return sd
    except Exception as e:  # нет PortAudio
        log.warning("sounddevice недоступен: %s", e)
        return None


def _device(spec):
    """Номер устройства по номеру или части имени ('USB', 'ReSpeaker')."""
    if spec in (None, "", "default"):
        return None
    if isinstance(spec, int) or str(spec).isdigit():
        return int(spec)
    return str(spec)


class MicHub:
    def __init__(self, cfg):
        self.device = _device(cfg.get("audio.input_device"))
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self.ring = deque(maxlen=int(15 * RATE / BLOCK))  # последние 15 секунд
        self.stream = None
        self.native_rate = RATE
        self.channels = 1
        self.level = 0.0
        self.ok = False

    def start(self) -> bool:
        """-> False, если микрофона нет: Стелла продолжит работать без голоса (веб, Telegram, экран)."""
        sd = _sd()
        if sd is None:
            log.error("Микрофон недоступен: установите libportaudio2 и sounddevice")
            return False
        try:
            self.stream = self._open(sd)
            self.stream.start()
        except Exception as e:
            log.error("Микрофон недоступен (%s). Голосовое управление выключено. Проверьте audio.input_device "
                      "(список устройств: python3 -m sounddevice)", e)
            self.stream = None
            return False
        self.ok = True
        log.info("Микрофон: %s (%s Гц, каналов: %s)", self.stream.device, self.native_rate, self.channels)
        return True

    def _open(self, sd):
        """16 кГц моно, а если устройство так не умеет — его родная частота и число каналов
        (у ReSpeaker и многих USB-микрофонов без PipeWire только стерео 48 кГц)."""
        try:
            return self._stream(sd, RATE, 1)
        except Exception as e:
            first = e
        info = sd.query_devices(self.device, "input")  # нет такого устройства — исключение уйдёт в start()
        native = int(info["default_samplerate"])
        chans = max(1, min(2, int(info.get("max_input_channels") or 1)))
        for rate, ch in ((native, 1), (RATE, chans), (native, chans)):
            if (rate, ch) == (RATE, 1):
                continue
            try:
                stream = self._stream(sd, rate, ch)
                log.info("Микрофон не умеет 16 кГц моно (%s) — пишу %s Гц, каналов: %s", first, rate, ch)
                return stream
            except Exception:
                continue
        raise first

    def _stream(self, sd, rate: int, channels: int):
        stream = sd.RawInputStream(samplerate=rate, blocksize=rate // 10, device=self.device,
                                   channels=channels, dtype="int16", callback=self._callback)
        self.native_rate, self.channels = rate, channels
        return stream

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def _callback(self, indata, frames, time_info, status):
        data = np.frombuffer(indata, dtype=np.int16)
        if self.channels > 1:
            data = data.reshape(-1, self.channels).mean(axis=1).astype(np.int16)
        else:
            data = data.copy()
        if self.native_rate != RATE:
            data = dsp.resample(data, self.native_rate, RATE)
        self.feed(data)

    def feed(self, data: np.ndarray):
        """Можно «подкармливать» звуком извне (тесты, файл, сеть)."""
        self.ring.append(data)
        self.level = dsp.level01(data)
        bus.emit("mic_level", level=self.level)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(data)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(data)
                except Exception:
                    pass

    def subscribe(self, maxsize: int = 200) -> queue.Queue:
        q = queue.Queue(maxsize=maxsize)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def record(self, seconds: float) -> np.ndarray:
        q = self.subscribe()
        chunks, need = [], int(seconds * RATE)
        got = 0
        deadline = time.time() + seconds + 3
        try:
            while got < need and time.time() < deadline:
                try:
                    c = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                chunks.append(c)
                got += len(c)
        finally:
            self.unsubscribe(q)
        return np.concatenate(chunks)[:need] if chunks else np.zeros(0, dtype=np.int16)

    def last(self, seconds: float) -> np.ndarray:
        blocks = list(self.ring)[-max(1, int(seconds * RATE / BLOCK)):]
        return np.concatenate(blocks) if blocks else np.zeros(0, dtype=np.int16)


class Speaker:
    """Воспроизведение речи/сигналов. Один звук за раз, можно прервать."""

    def __init__(self, cfg):
        self.device = _device(cfg.get("audio.output_device"))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.speaking = False
        self.speaking_until = 0.0
        self._sd = _sd()
        self._fail_until = 0.0
        self._player = None
        if self._sd is None:
            for cmd in ("paplay", "aplay", "ffplay"):
                if shutil.which(cmd):
                    self._player = cmd
                    break

    def stop(self):
        self._stop.set()

    def play(self, samples: np.ndarray, sr: int, animate: bool = True, volume: float = 1.0) -> bool:
        """Блокирующее воспроизведение. -> True, если доиграло до конца."""
        if samples is None or len(samples) == 0:
            return True
        if volume != 1.0:
            samples = dsp.to_int16(dsp.to_float(samples) * volume)
        if time.time() < self._fail_until:  # динамик недоступен — не спамим ошибками
            return False
        with self._lock:
            self._stop.clear()
            self.speaking = True
            self.speaking_until = time.time() + len(samples) / sr + 0.5
            try:
                if self._sd is not None:
                    return self._play_sd(samples, sr, animate)
                return self._play_fallback(samples, sr, animate)
            except Exception as e:
                log.error("Ошибка воспроизведения: %s (проверьте audio.output_device)", e)
                self._fail_until = time.time() + 30
                return False
            finally:
                self.speaking = False
                self.speaking_until = time.time() + 0.3
                bus.emit("speech_level", level=0.0)

    def _play_sd(self, samples, sr, animate):
        try:
            return self._play_sd_rate(samples, sr, animate)
        except Exception as e:
            # голое ALSA-устройство без PipeWire может не уметь 22 кГц — пересэмплируем в 48 кГц
            if sr == 48000 or "sample rate" not in str(e).lower():
                raise
            log.info("Динамик не поддерживает %s Гц, играю в 48 кГц", sr)
            return self._play_sd_rate(dsp.resample(samples, sr, 48000), 48000, animate)

    def _play_sd_rate(self, samples, sr, animate):
        sd = self._sd
        env = dsp.envelope(samples, sr, 30) if animate else None
        block = max(256, sr // 30)
        done = True
        with sd.OutputStream(samplerate=sr, channels=1, dtype="int16", device=self.device,
                             blocksize=block) as stream:
            lat = int((stream.latency or 0.05) * 30)
            for i, pos in enumerate(range(0, len(samples), block)):
                if self._stop.is_set():
                    done = False
                    break
                stream.write(np.ascontiguousarray(samples[pos:pos + block]).reshape(-1, 1))
                if env is not None:
                    k = max(0, i - lat)
                    bus.emit("speech_level", level=float(env[min(k, len(env) - 1)]))
            if done:
                time.sleep(min(0.3, stream.latency or 0.05))
        return done

    def _play_fallback(self, samples, sr, animate):
        """Без PortAudio: через aplay/paplay (или просто «молча», если нет и их)."""
        dur = len(samples) / sr
        proc = None
        if self._player:
            args = {"aplay": ["aplay", "-q", "-"], "paplay": ["paplay"],
                    "ffplay": ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-"]}[self._player]
            proc = subprocess.Popen(args, stdin=subprocess.PIPE)
            threading.Thread(target=self._feed_proc, args=(proc, dsp.wav_bytes(samples, sr)), daemon=True).start()
        env = dsp.envelope(samples, sr, 30) if animate else None
        t0 = time.time()
        while time.time() - t0 < dur:
            if self._stop.is_set():
                if proc:
                    proc.kill()
                return False
            if env is not None:
                k = int((time.time() - t0) * 30)
                bus.emit("speech_level", level=float(env[min(k, len(env) - 1)]))
            time.sleep(1 / 30)
        if proc:
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        return True

    @staticmethod
    def _feed_proc(proc, data):
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except Exception:
            pass
