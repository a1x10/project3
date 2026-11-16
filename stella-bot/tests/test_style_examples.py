"""«Как общаются ребята»: примеры из панели попадают в ответ Стеллы; номера скрываются; характер живой, но честный."""

import random

from bot.persona import minimal_prompt
from bot.style_examples import STORE, StyleStore, clean

from .conftest import VASYA, settle, upsert
from .test_admin import auth, login, panel, fast_login  # noqa: F401 — фикстуры панели


def test_clean_hides_contacts():
    text = clean("пиши мне +7 701 555 44 33 или vasya@mail.ru ахах")
    assert "[номер]" in text and "[почта]" in text and "555" not in text


async def test_hint_samples_within_budget():
    store = StyleStore()
    await store.add("slang", "имба — круто; кринж — стыдно")
    await store.add("chat", "— го в рб\n— ща\n" * 400)
    hint = store.hint(random.Random(1), budget=600)
    assert "имба" in hint and "переписка" in hint and len(hint) < 1100
    assert StyleStore().hint() == ""


async def test_examples_reach_the_model_and_panel_flow(panel, brain):  # noqa: F811
    h = auth((await login(panel)).json()["token"])
    r = await panel.post("/admin/api/style", json={"kind": "meme", "text": "это база, а это кринж 💀"}, headers=h)
    assert r.status_code == 200 and r.json()["item"]["kind_name"] == "мемы и шутки"
    assert (await panel.post("/admin/api/style", json={"kind": "nope", "text": "abc"}, headers=h)).status_code == 422
    items = (await panel.get("/admin/api/style", headers=h)).json()["items"]
    assert len(items) == 1
    await brain.handle_payload(upsert("стелла привет", chat=VASYA, sender=VASYA))
    await settle(brain)
    assert "это база, а это кринж" in brain.llm.calls[-1]["prompt"]
    assert (await panel.delete(f"/admin/api/style/{items[0]['id']}", headers=h)).json()["ok"]
    assert STORE.items == []
    assert (await panel.get("/admin/api/style")).status_code == 401


def test_persona_is_lively_but_honest(settings):
    p = minimal_prompt(settings)
    assert "эмоции настоящие" in p
    assert "не врёшь, что ты человек" in p and "не флиртуешь, не влюбляешься" in p
