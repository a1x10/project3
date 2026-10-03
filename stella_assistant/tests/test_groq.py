import numpy as np

from stella.audio import stt
from stella.config import Config
from stella.llm.brain import make_llm
from stella.llm.groq import GroqLLM
from stella.llm.yandexgpt import LLMError


class Resp:
    def __init__(self, status=200, data=None, text="", headers=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._data = data or {}
        self.text = text or str(data)
        self.headers = headers or {}

    def json(self):
        return self._data


def chat_ok(text):
    return Resp(200, {"choices": [{"message": {"role": "assistant", "content": text}}]})


def cfg_with_groq(**extra):
    cfg = Config()
    cfg.set("groq.api_key", "gsk_test")
    for k, v in extra.items():
        cfg.set(k, v)
    return cfg


def test_groq_request_format(monkeypatch):
    g = GroqLLM(cfg_with_groq())
    sent = []
    monkeypatch.setattr(g.session, "post", lambda url, **kw: sent.append((url, kw)) or chat_ok("[joy] Привет!"))
    out = g.complete([{"role": "system", "text": "ты Стелла"}, {"role": "user", "text": "привет"}])
    assert out == "[joy] Привет!"
    url, kw = sent[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert kw["headers"]["Authorization"] == "Bearer gsk_test"
    body = kw["json"]
    assert body["model"] == "llama-3.3-70b-versatile"
    assert body["messages"][1] == {"role": "user", "content": "привет"}
    assert body["max_completion_tokens"] == 800
    assert "reasoning_effort" not in body


def test_groq_skips_decommissioned_model(monkeypatch):
    g = GroqLLM(cfg_with_groq())
    calls = []

    def post(url, json=None, **kw):
        calls.append(json["model"])
        if json["model"] == "llama-3.3-70b-versatile":
            return Resp(400, text='{"error":{"code":"model_decommissioned"}}')
        assert json["reasoning_effort"] == "low" and json["include_reasoning"] is False
        return chat_ok("[neutral] ок")
    monkeypatch.setattr(g.session, "post", post)
    assert g.complete([{"role": "user", "text": "тест"}]) == "[neutral] ок"
    assert calls == ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"]
    calls.clear()
    g.complete([{"role": "user", "text": "ещё"}])
    assert calls == ["openai/gpt-oss-120b"]          # отключённую модель больше не пробуем


def test_groq_bad_key(monkeypatch):
    g = GroqLLM(cfg_with_groq())
    monkeypatch.setattr(g.session, "post", lambda url, **kw: Resp(401, text="invalid_api_key"))
    try:
        g.complete([{"role": "user", "text": "привет"}])
        assert False, "ожидалась ошибка"
    except LLMError as e:
        assert "ключ" in str(e)


def test_chain_prefers_groq_and_falls_back_to_yandex(monkeypatch):
    cfg = cfg_with_groq(**{"yandex.api_key": "Y", "yandex.folder_id": "F"})
    llm = make_llm(cfg)
    groq, yandex = llm.providers
    assert (groq.name, yandex.name) == ("groq", "yandex") and llm.name == "groq"

    def groq_fail(*a, **k):
        raise LLMError("недоступен")
    monkeypatch.setattr(groq, "complete", groq_fail)
    monkeypatch.setattr(yandex, "complete", lambda *a, **k: "[joy] ответ YandexGPT")
    assert llm.complete([{"role": "user", "text": "привет"}]) == "[joy] ответ YandexGPT"
    cfg.set("llm.provider", "yandex")
    assert make_llm(cfg).providers[0].name == "yandex"


def test_whisper_transcription_and_hallucination_filter(monkeypatch):
    g = GroqLLM(cfg_with_groq())
    seen = {}

    def post(url, files=None, data=None, **kw):
        seen.update(url=url, data=data, name=files["file"][0])
        return Resp(200, {"text": seen.get("reply", "Стелла, какая погода завтра?")})
    monkeypatch.setattr(g.session, "post", post)
    assert g.transcribe(b"RIFF....") == "Стелла, какая погода завтра?"
    assert seen["url"].endswith("/audio/transcriptions")
    assert seen["data"]["model"] == "whisper-large-v3-turbo" and seen["data"]["language"] == "ru"
    seen["reply"] = "Продолжение следует..."
    assert g.transcribe(b"RIFF....") is None


def test_cloud_stt_selection(monkeypatch):
    cfg = cfg_with_groq()
    stt._GROQ = None
    calls = []
    monkeypatch.setattr(GroqLLM, "transcribe", lambda self, wav, language="ru": calls.append("groq") or "включи музыку")
    monkeypatch.setattr(stt, "yandex_recognize", lambda *a, **k: calls.append("yandex") or None)
    audio = np.zeros(16000, dtype=np.int16)
    assert stt.cloud_recognize(cfg, audio) == "включи музыку" and calls == ["groq"]
    cfg.set("stt.cloud", "off")
    assert stt.cloud_recognize(cfg, audio) is None
    assert stt._plain("Стелла, какая погода?") == "стелла какая погода"
    stt._GROQ = None
