"""Распознавание речи: faster-whisper локально на VPS."""
import tempfile

from . import config

_model = None


def transcribe(data: bytes, suffix: str = ".wav") -> str:
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(data)
        f.flush()
        segs, _ = _model.transcribe(f.name, language=config.WHISPER_LANG or None, vad_filter=True)
        return " ".join(s.text.strip() for s in segs).strip()
