import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exchange.analyst import Analyst  # noqa: E402


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    a = Analyst()
    assert not a.enabled and not a.due() and a.view()["enabled"] is False


def test_failure_hides_block(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    a = Analyst(interval=0)
    if not a.enabled:  # пакет anthropic не установлен — блок и так скрыт
        return

    class Boom:
        class messages:
            @staticmethod
            async def create(**kw):
                raise ConnectionError("нет интернета")

    a._client = Boom()
    a.text = "старый комментарий"
    for _ in range(3):
        asyncio.run(a.run(lambda: {"x": 1}))
    assert a.text is None and a.view()["enabled"] is False


def test_success_shows_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    a = Analyst(interval=0)
    if not a.enabled:
        return

    class OK:
        class messages:
            @staticmethod
            async def create(**kw):
                assert "Данные" in kw["messages"][0]["content"]
                return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ИИ торгует спокойно.")])

    a._client = OK()
    asyncio.run(a.run(lambda: {"цена": 65000}))
    assert a.view() == {"enabled": True, "text": "ИИ торгует спокойно.", "ts": a.updated}
