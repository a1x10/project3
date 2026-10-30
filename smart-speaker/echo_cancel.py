"""Эхоподавление: вычитает из микрофона то, что в этот момент играет колонка (WebRTC AEC).

Благодаря этому колонка не слышит сама себя, а вы можете перебить её голосом.
Если библиотека aec-audio-processing не установлена, speaker.py работает по-старому:
пока колонка говорит, микрофон просто выключается.
"""
import os
import threading
from array import array
from collections import deque

try:
    from aec_audio_processing import AudioProcessor
except Exception:  # нет колеса под эту платформу
    AudioProcessor = None

FRAME = 160          # 10 мс при 16 кГц
FRAME_BYTES = FRAME * 2


def available() -> bool:
    return AudioProcessor is not None and os.getenv("AEC", "1") != "0"


def _rms(b: bytes) -> float:
    a = array("h")
    a.frombytes(b)
    return (sum(x * x for x in a) / max(1, len(a))) ** 0.5


class EchoCanceller:
    def __init__(self, rate=16000, ref_delay_ms=0, gate=200):
        self.apm = AudioProcessor(enable_aec=True, enable_ns=False, enable_agc=False, enable_vad=False)
        self.apm.set_stream_format(rate, 1, rate, 1)
        self.apm.set_reverse_stream_format(rate, 1)
        self.ref = bytearray()
        self.lock = threading.Lock()
        # Для очень медленных колонок: опору задерживаем, чтобы относительная задержка влезла в диапазон AEC
        self.delay = deque(bytes(FRAME_BYTES) for _ in range(max(0, int(ref_delay_ms) // 10)))
        self.gate = gate
        self.pending = bytearray()

    def feed_reference(self, pcm: bytes):
        """Вызывается с тем, что отправляется на колонку."""
        with self.lock:
            self.ref += pcm
            if len(self.ref) > 64000:               # не копим больше ~2 с
                del self.ref[: len(self.ref) - 64000]

    def process(self, mic: bytes, playing: bool) -> bytes:
        """Возвращает микрофон без эха. Пока колонка играет, остаточный тихий шум обнуляется (gate)."""
        self.pending += mic
        out = bytearray()
        while len(self.pending) >= FRAME_BYTES:
            frame = bytes(self.pending[:FRAME_BYTES])
            del self.pending[:FRAME_BYTES]
            with self.lock:
                ref = bytes(self.ref[:FRAME_BYTES])
                del self.ref[:FRAME_BYTES]
            ref += bytes(FRAME_BYTES - len(ref))
            if self.delay:
                self.delay.append(ref)
                ref = self.delay.popleft()
            self.apm.process_reverse_stream(ref)
            cleaned = self.apm.process_stream(frame)
            if playing and _rms(cleaned) < self.gate:
                cleaned = bytes(FRAME_BYTES)
            out += cleaned
        return bytes(out)
