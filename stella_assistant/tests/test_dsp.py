import numpy as np

from stella.audio import dsp


def _syllables(n, sr):
    """Огибающая «слогов» с паузами — как у настоящей речи."""
    t = np.arange(n) / sr
    return np.clip(np.sin(2 * np.pi * 2.5 * t), 0, None) ** 0.5 + 0.002


def _voiced(sr=16000, sec=2.0):
    t = np.arange(int(sr * sec)) / sr
    f0 = 140 + 20 * np.sin(2 * np.pi * 0.5 * t)
    phase = 2 * np.pi * np.cumsum(f0) / sr
    sig = sum(np.sin(k * phase) / k for k in range(1, 12))
    return dsp.to_int16(sig * _syllables(len(t), sr) * 0.2)


def test_whisper_detection():
    voiced = _voiced()
    assert not dsp.is_whisper(voiced)
    noise = np.random.default_rng(1).standard_normal(len(voiced)) * 0.03
    assert dsp.is_whisper(dsp.to_int16(noise * _syllables(len(voiced), 16000)))


def test_whisperize_removes_pitch():
    x = _voiced(22050)
    w = dsp.whisperize(x, 22050)
    assert len(w) == len(x)
    ratio_before, _ = dsp.voicing_ratio(dsp.resample(x, 22050, 16000))
    ratio_after, _ = dsp.voicing_ratio(dsp.resample(w, 22050, 16000))
    assert ratio_after < ratio_before


def test_wav_roundtrip_and_beeps():
    x = dsp.beep("listen")
    y, sr = dsp.read_wav(dsp.wav_bytes(x, 22050))
    assert sr == 22050 and np.array_equal(x, y)
    assert len(dsp.alarm_melody(repeats=2)) > len(dsp.alarm_melody(repeats=1))
    assert 0.0 <= dsp.level01(x) <= 1.0
