import tempfile

from stella.config import Config
from stella.core.assistant import Assistant
from stella.llm.brain import parse_answer
from stella.llm.yandexgpt import YandexGPT


def test_parse_answer():
    th = parse_answer("[joy] Привет! Как дела?")
    assert th.emotion == "joy" and th.text == "Привет! Как дела?"
    th = parse_answer("[neutral] КОМАНДА: включи свет на кухне.")
    assert th.command == "включи свет на кухне" and th.text == ""
    th = parse_answer("[interest] ПОИСК: курс биткоина сегодня")
    assert th.search == "курс биткоина сегодня"
    assert parse_answer("Текст без тега").emotion is None
    assert parse_answer("[злость] Ну всё!").emotion == "anger"


class _Resp:
    ok = True
    status_code = 200

    def json(self):
        return {"result": {"alternatives": [{"message": {"role": "assistant", "text": "[joy] Привет!"},
                                             "status": "ALTERNATIVE_STATUS_FINAL"}]}}


def test_yandexgpt_request_format(monkeypatch):
    cfg = Config()
    cfg.set("yandex.api_key", "KEY")
    cfg.set("yandex.folder_id", "b1gfolder")
    gpt = YandexGPT(cfg)
    sent = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, json=json, headers=headers)
        return _Resp()
    monkeypatch.setattr(gpt.session, "post", fake_post)
    out = gpt.complete([{"role": "system", "text": "ты Стелла"}, {"role": "user", "text": "привет"}])
    assert out == "[joy] Привет!"
    assert sent["url"].endswith("/foundationModels/v1/completion")
    assert sent["json"]["modelUri"] == "gpt://b1gfolder/yandexgpt-5-lite"
    assert sent["json"]["completionOptions"]["maxTokens"] == "800"
    assert sent["headers"]["Authorization"] == "Api-Key KEY"


def test_llm_command_and_emotion(monkeypatch):
    cfg = Config()
    cfg.set("data_dir", tempfile.mkdtemp())
    cfg.set("smarthome.scenarios_file", tempfile.mktemp(suffix=".yaml"))
    cfg.set("yandex.api_key", "KEY")
    cfg.set("yandex.folder_id", "folder")
    a = Assistant(cfg, voice=False)
    a.say = lambda *args, **kw: None
    answers = iter(["[neutral] КОМАНДА: добавь сыр в список покупок", "[love] Ты тоже мне нравишься!"])
    monkeypatch.setattr(a.brain.llm, "complete", lambda *args, **kw: next(answers))
    r = a.ask("ну это… надо бы сыра купить, кончился", source="test")
    assert "сыр" in r.text
    assert any(i["text"] == "сыр" for i in a.memory.list_items("покупки"))
    r = a.ask("как ты относишься к котикам", source="test")
    assert r.emotion == "love"
    a.shutdown()
