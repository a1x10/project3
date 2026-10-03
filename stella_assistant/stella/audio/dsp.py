"""Обработка звука: уровень громкости, распознавание шёпота, «шёпот» для синтеза,
звуковые сигналы и мелодия будильника. Только numpy (+ scipy, если есть)."""
from __future__ import annotations

import io
import math
import wave

import numpy as np

try:
    from scipy.signal import lfilter, resample_poly
except Exception:  # pragma: no cover
    lfilter = resample_poly = None


def to_float(x: np.ndarray) -> np.ndarray:
    if x.dtype == np.int16:
        return x.astype(np.float32) / 32768.0
    return x.astype(np.float32)


def to_int16(x: np.ndarray) -> np.ndarray:
    if x.dtype == np.int16:
        return x
    return (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)


def rms_db(x: np.ndarray) -> float:
    f = to_float(x)
    if f.size == 0:
        return -120.0
    r = float(np.sqrt(np.mean(f * f)) + 1e-9)
    return 20 * math.log10(r)


def level01(x: np.ndarray, floor_db: float = -55.0, ceil_db: float = -12.0) -> float:
    """Громкость 0..1 для анимации (микрофон, рот)."""
    return float(np.clip((rms_db(x) - floor_db) / (ceil_db - floor_db), 0.0, 1.0))


def resample(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    if sr_from == sr_to or x.size == 0:
        return x
    g = math.gcd(int(sr_from), int(sr_to))
    up, down = sr_to // g, sr_from // g
    if resample_poly is not None:
        y = resample_poly(to_float(x), up, down)
    else:  # линейная интерполяция без scipy
        n = int(len(x) * sr_to / sr_from)
        y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), to_float(x))
    return to_int16(y) if x.dtype == np.int16 else y.astype(np.float32)


# ------------------------------------------------------------- шёпот (вход) --
def voicing_ratio(x: np.ndarray, sr: int = 16000):
    """-> (доля звонких кадров среди речевых, средний уровень речи в dBFS).

    Шёпот — это речь без колебаний голосовых связок: в нём почти нет периодичности
    (основного тона), а громкость низкая.
    """
    f = to_float(x)
    frame = int(sr * 0.032)
    hop = frame // 2
    if len(f) < frame * 4:
        return 1.0, -120.0
    frames = np.lib.stride_tricks.sliding_window_view(f, frame)[::hop]
    energy = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-10)
    noise = np.percentile(energy, 15)
    speech = frames[energy > max(noise + 9, -58)]
    if len(speech) < 4:
        return 1.0, -120.0
    lo, hi = int(sr / 400), int(sr / 70)  # основной тон 70..400 Гц
    voiced = 0
    for fr in speech:
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, mode="full")[len(fr) - 1:]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        if ac[lo:hi].max() > 0.42:
            voiced += 1
    level = float(np.mean(energy[energy > max(noise + 9, -58)]))
    return voiced / len(speech), level


def is_whisper(x: np.ndarray, sr: int = 16000) -> bool:
    ratio, level = voicing_ratio(x, sr)
    return ratio < 0.22 and level < -24


# ------------------------------------------------------------ шёпот (выход) --
def _lpc(frame: np.ndarray, order: int) -> np.ndarray:
    """Коэффициенты линейного предсказания (Левинсон–Дарбин)."""
    r = np.correlate(frame, frame, mode="full")[len(frame) - 1:len(frame) + order]
    if r[0] <= 1e-9:
        return np.concatenate(([1.0], np.zeros(order)))
    a = np.zeros(order + 1)
    a[0] = 1.0
    err = r[0]
    for i in range(1, order + 1):
        acc = r[i] + np.dot(a[1:i], r[i - 1:0:-1])
        k = -acc / err
        a_prev = a.copy()
        for j in range(1, i):
            a[j] = a_prev[j] + k * a_prev[i - j]
        a[i] = k
        err *= (1 - k * k)
        if err <= 1e-12:
            break
    return a


def whisperize(x: np.ndarray, sr: int, order: int = 18, gain: float = 0.55) -> np.ndarray:
    """Превращает обычную речь в шёпот: заменяет голосовой источник шумом,
    сохраняя огибающую спектра (тембр и артикуляцию)."""
    if lfilter is None:
        return to_int16(to_float(x) * 0.4)
    f = to_float(x)
    n = int(sr * 0.025)
    hop = n // 2
    win = np.hanning(n).astype(np.float32)
    out = np.zeros(len(f) + n, dtype=np.float32)
    rng = np.random.default_rng(7)
    pre = np.append(f[0], f[1:] - 0.9 * f[:-1])  # предыскажение
    for start in range(0, len(f) - n, hop):
        fr = pre[start:start + n] * win
        a = _lpc(fr.astype(np.float64), order)
        resid = lfilter(a, [1.0], fr)
        e = float(np.sqrt(np.mean(resid ** 2)) + 1e-9)
        noise = rng.standard_normal(n).astype(np.float32) * e
        y = lfilter([1.0], a, noise).astype(np.float32)
        out[start:start + n] += y * win
    out = lfilter([1.0], [1.0, -0.9], out[: len(f)]).astype(np.float32)  # снимаем предыскажение
    out = lfilter([1.0, -1.0], [1.0, -0.95], out).astype(np.float32)    # убираем гул на низах
    peak = float(np.max(np.abs(out)) + 1e-9)
    return to_int16(out / peak * gain)


# ----------------------------------------------------------------- сигналы --
def tone(freq: float, dur: float, sr: int = 22050, vol: float = 0.3, fade: float = 0.01) -> np.ndarray:
    t = np.arange(int(sr * dur)) / sr
    y = np.sin(2 * np.pi * freq * t) * vol
    y += np.sin(4 * np.pi * freq * t) * vol * 0.15
    nf = max(1, int(sr * fade))
    env = np.ones_like(y)
    env[:nf] = np.linspace(0, 1, nf)
    env[-nf:] = np.linspace(1, 0, nf)
    return to_int16(y * env)


def beep(kind: str = "listen", sr: int = 22050) -> np.ndarray:
    if kind == "listen":
        return np.concatenate([tone(880, 0.07, sr, 0.18), tone(1320, 0.09, sr, 0.18)])
    if kind == "done":
        return np.concatenate([tone(1320, 0.06, sr, 0.15), tone(880, 0.08, sr, 0.15)])
    if kind == "error":
        return np.concatenate([tone(330, 0.12, sr, 0.2), tone(262, 0.18, sr, 0.2)])
    return tone(1000, 0.1, sr, 0.2)


def alarm_melody(sr: int = 22050, repeats: int = 1) -> np.ndarray:
    """Нежная мелодия будильника (арпеджио), громкость растёт с повторами."""
    notes = [523.25, 659.25, 783.99, 1046.5, 783.99, 659.25]
    parts = []
    for r in range(repeats):
        vol = min(0.5, 0.15 + 0.07 * r)
        for f in notes:
            parts.append(tone(f, 0.16, sr, vol, 0.02))
        parts.append(np.zeros(int(sr * 0.35), dtype=np.int16))
    return np.concatenate(parts)


def timer_melody(sr: int = 22050) -> np.ndarray:
    seq = []
    for _ in range(3):
        seq += [tone(1568, 0.1, sr, 0.3), np.zeros(int(sr * 0.06), np.int16), tone(1568, 0.1, sr, 0.3),
                np.zeros(int(sr * 0.4), np.int16)]
    return np.concatenate(seq)


# --------------------------------------------------------------------- WAV --
def wav_bytes(samples: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(to_int16(samples).tobytes())
    return buf.getvalue()


def read_wav(data_or_path) -> tuple[np.ndarray, int]:
    src = io.BytesIO(data_or_path) if isinstance(data_or_path, (bytes, bytearray)) else data_or_path
    with wave.open(src, "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        width = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if width == 2:
        x = np.frombuffer(raw, dtype=np.int16)
    elif width == 4:
        x = (np.frombuffer(raw, dtype=np.int32) >> 16).astype(np.int16)
    else:
        x = ((np.frombuffer(raw, dtype=np.uint8).astype(np.int16) - 128) << 8).astype(np.int16)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1).astype(np.int16)
    return x, sr


def envelope(samples: np.ndarray, sr: int, fps: int = 30) -> np.ndarray:
    """Огибающая громкости по кадрам анимации (для движения рта)."""
    hop = max(1, sr // fps)
    f = to_float(samples)
    n = len(f) // hop
    if n == 0:
        return np.zeros(1, dtype=np.float32)
    fr = f[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt(np.mean(fr * fr, axis=1)) + 1e-9)
    return np.clip((db + 50) / 38, 0, 1).astype(np.float32)
