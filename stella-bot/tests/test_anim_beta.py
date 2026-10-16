"""Мультики (бета): разбор сценария, кадры, настоящий рендер и «объявить → нарисовать → прислать»."""

import asyncio
import math
import random
import shutil

import pytest

from bot.anim_beta import runner, spec

from .conftest import OWNER, settle, upsert

GOOD = {
    "caption": "Мурка нашла кристалл",
    "cast": {"murka": {"kind": "cat", "color": "#ff9f43"}, "zhora": {"kind": "лиса"}, "bobo": {"kind": "toy"}},
    "things": {"gem": {"shape": "gem"}},
    "scenes": [{"seconds": 5.5, "background": "meadow",
                "place": {"murka": {"x": 0.2}, "zhora": {"x": 0.8}, "bobo": {"x": 0.5}, "gem": {"x": 0.5, "y": 0.3}},
                "events": [{"t": 0, "who": "murka", "do": "walk", "to": 0.4},
                           {"t": 0.5, "who": "zhora", "do": "wave", "say": "Привет! ❤️🎉"},
                           {"t": 1.5, "who": "murka", "emotion": "love"},
                           {"t": 2, "fx": "confetti", "x": 0.5, "y": 0.3},
                           {"t": 2, "who": "gem", "do": "spin"},
                           {"t": 2.2, "who": "bobo", "do": "dance", "emotion": "happy"}]}],
}


async def feed(brain, *payloads):
    for p in payloads:
        await brain.handle_payload(p)
    await settle(brain, timeout=20)


# ---------- сценарий ----------
def test_parse_good_spec():
    plan, warnings, caption = spec.parse(GOOD)
    assert caption == "Мурка нашла кристалл" and plan["size"] == [720, 720] and plan["fps"] == 24
    assert plan["cast"]["zhora"]["kind"] == "fox"
    sc = plan["scenes"][0]
    assert set(sc["place"]) == {"murka", "zhora", "bobo", "gem"}
    say = next(e for e in sc["events"] if "say" in e)
    assert say["say"] == "Привет! ♥"  # эмодзи — на значок из шрифта, остальное выкинуто
    walk = next(e for e in sc["events"] if e.get("act") == "walk")
    assert walk["to"] == [0.4, sc["place"]["murka"]["y"]]
    assert not warnings


def test_parse_fixes_and_warns():
    raw = {"format": "tall", "scenes": [{"background": "ночь", "events": [
        {"who": "кот", "do": "прыгает", "emotion": "радость"},
        {"who": "кот", "do": "moonwalk"},
        {"who": "nobody", "say": "x"},
        {"fx": "салют"},
        {"who": "кот", "emotion": "happyy"}]}]}
    plan, warnings, _ = spec.parse(raw)
    assert plan["size"] == [720, 1280] and plan["scenes"][0]["bg"] == "night"
    assert plan["cast"]["кот"]["kind"] == "cat"  # актёра из событий создала сама
    acts = [e.get("act") for e in plan["scenes"][0]["events"]]
    assert acts[:2] == ["jump", "walk"]  # «moonwalk» — похоже на walk
    text = " ".join(warnings)
    assert "добавила" in text and "moonwalk» → walk" in text and "nobody" in text and "салют" in text
    assert "happyy» → happy" in text


def test_parse_limits_and_garbage():
    with pytest.raises(spec.SpecError):
        spec.parse("кот танцует")
    with pytest.raises(spec.SpecError):
        spec.parse({"cast": {"a": {"kind": "cat"}}})
    with pytest.raises(spec.SpecError, match="длинный"):
        spec.parse({"scenes": [{"events": [{"who": "кот", "say": "а" * 30000}]}]})
    with pytest.raises(spec.SpecError, match="длинно"):
        spec.parse({"cast": {"a": {"kind": "cat"}}, "scenes": [{"seconds": 20, "events": []}] * 3})
    many = {"cast": {f"c{i}": {"kind": "cat"} for i in range(9)},
            "things": {f"t{i}": {"shape": "star"} for i in range(9)},
            "scenes": [{"seconds": 7, "zoom": float("nan"), "events": [
                {"t": -5, "who": "c0", "do": "walk", "to": 99, "dur": float("inf"), "say": "x" * 90}] * 25}] * 5}
    plan, warnings, _ = spec.parse(many)
    assert len(plan["cast"]) == 4 and len(plan["things"]) == 3 and len(plan["scenes"]) == 4
    assert sum(s["dur"] for s in plan["scenes"]) <= 20.0 + 1e-6 and any("сжала" in w for w in warnings)
    for sc in plan["scenes"]:
        assert len(sc["events"]) <= spec.MAX_EVENTS and 1.0 <= sc["camera"][1]["zoom"] <= 1.3
        for e in sc["events"]:
            assert 0.08 <= e["to"][0] <= 0.92 and len(e.get("say", "")) <= spec.MAX_SAY and math.isfinite(e["dur"])


def test_parse_fuzz_never_crashes():
    rng = random.Random(7)
    pool = [None, 1, -1.5, float("nan"), float("inf"), "", "кот", "walk", "#zzzzzz", "#ff0000", [], {}, [1, 2],
            {"kind": "cat"}, "x" * 300, True, 1e300]

    def junk(depth=0):
        if depth > 3 or rng.random() < 0.3:
            return rng.choice(pool)
        if rng.random() < 0.5:
            return [junk(depth + 1) for _ in range(rng.randint(0, 4))]
        keys = ["cast", "things", "scenes", "events", "who", "do", "say", "t", "to", "dur", "fx", "place", "x", "y",
                "kind", "shape", "emotion", "seconds", "background", "format", "zoom", "facing"]
        return {rng.choice(keys): junk(depth + 1) for _ in range(rng.randint(0, 5))}

    for _ in range(400):
        raw = junk()
        if isinstance(raw, dict) and rng.random() < 0.5:
            raw["scenes"] = [{"events": [junk(2) for _ in range(3)], "place": junk(2)}]
            raw["cast"] = {"a": {"kind": rng.choice(spec.KINDS)}}
        try:
            plan, _, _ = spec.parse(raw)
        except spec.SpecError:
            continue
        assert plan["cast"] or plan["things"]
        for sc in plan["scenes"]:
            for e in sc["events"]:
                assert "fx" in e or e["who"] in sc["place"]


# ---------- кадры ----------
def test_frames_render_every_kind_shape_background():
    import cairocffi as cairo

    from bot.anim_beta.frame import render_frame

    cast = {k: {"kind": k} for k in spec.KINDS}
    things = {s: {"shape": s} for s in spec.SHAPES}
    events = [{"t": 0.1 * i, "who": k, "do": a, "emotion": e, "say": "Привет"}
              for i, (k, a, e) in enumerate(zip(list(spec.KINDS) * 2, spec.ACTS * 2, spec.EMOTIONS, strict=False))]
    events += [{"t": 0.2, "who": s, "do": "spin"} for s in spec.SHAPES] + [{"t": 0.3, "fx": "confetti"}]
    for bg in spec.BACKGROUNDS:
        plan, _, _ = spec.parse({"cast": cast, "things": things, "scenes": [{"seconds": 2, "background": bg,
                                                                             "events": events}]})
        plan["cast"] = dict(list(plan["cast"].items()))
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, *plan["size"])
        for i in (12, 30):
            render_frame(plan, i, surf)
            data = bytes(surf.get_data())
            assert len(set(data[::997])) > 20  # не пустой кадр


def test_frame_is_deterministic():
    import cairocffi as cairo

    from bot.anim_beta.frame import render_frame

    plan, _, _ = spec.parse(GOOD)
    a = cairo.ImageSurface(cairo.FORMAT_ARGB32, 720, 720)
    b = cairo.ImageSurface(cairo.FORMAT_ARGB32, 720, 720)
    render_frame(plan, 50, a)
    render_frame(plan, 10, b)
    render_frame(plan, 50, b)
    assert bytes(a.get_data()) == bytes(b.get_data())


def test_eta_text():
    assert runner.human_eta(8) == "секунд через 10"
    assert runner.human_eta(21) == "секунд через 25"
    assert runner.human_eta(70) == "примерно через минуту"
    assert runner.human_eta(300) == "минут через 5"


# ---------- настоящий рендер ----------
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")
async def test_real_render_tiny():
    plan, _, _ = spec.parse(GOOD)
    plan["size"], plan["fps"] = [160, 160], 6
    for sc in plan["scenes"]:
        sc["dur"] = 1.0
    data = await runner.render(plan, 999, timeout=60)
    assert data[4:8] == b"ftyp" and len(data) > 1000
    assert 999 not in runner.STATE.busy_chats


# ---------- в чате: объявить → нарисовать → прислать ----------
def _cartoon_tool(reply: str):
    async def talk(tools, prompt):
        out = await tools["make_cartoon"].handler(GOOD)
        assert "уже рисуется" in out
        return reply
    return talk


@pytest.fixture
def fake_render(monkeypatch):
    calls = {"n": 0, "delay": 0.0, "fail": None}

    async def render(plan, chat_id, *, timeout=150, on_start=None):
        calls["n"] += 1
        runner.STATE.busy_chats.add(chat_id)
        try:
            await asyncio.sleep(calls["delay"])
            if calls["fail"]:
                raise runner.RenderError(calls["fail"])
            return b"\x00\x00\x00\x18ftypmp42" + b"0" * 100
        finally:
            runner.STATE.busy_chats.discard(chat_id)

    monkeypatch.setattr(runner, "render", render)
    return calls


async def test_reply_first_then_video(brain, fake_render):
    brain.llm.queue = [_cartoon_tool("щас нарисую мультик, секунд 15 🎬")]
    await feed(brain, upsert("стелла сделай мультик про кота"))
    kinds = [m["type"] for m in brain.evo.sent]
    assert kinds == ["text", "media"] and brain.evo.sent[0]["text"].startswith("щас нарисую")
    assert brain.evo.sent[1]["mimetype"] == "video/mp4" and brain.evo.sent[1]["caption"] == "Мурка нашла кристалл"


async def test_silent_model_still_announces(brain, fake_render):
    brain.llm.queue = [_cartoon_tool("<молчу>")]
    await feed(brain, upsert("стелла мультик"))
    assert brain.evo.texts()[0].startswith("делаю мультик 🎬 будет готов")
    assert brain.evo.sent[-1]["type"] == "media"


async def test_render_failure_message(brain, fake_render):
    fake_render["fail"] = "не получилось собрать мультик"
    brain.llm.queue = [_cartoon_tool("рисую!")]
    await feed(brain, upsert("стелла мультик"))
    assert brain.evo.texts()[-1].startswith("мультик не получился 😕")
    assert not [m for m in brain.evo.sent if m["type"] == "media"]
    chat = await brain.db.get_chat_by_jid("stella", "120363000000000001@g.us")
    from datetime import date

    used = await brain.db.kv_get(f"anim:{chat['id']}:{date.today().isoformat()}")
    assert not used or used[1] == 0  # неудачный мультик не съедает дневной лимит


async def test_chat_is_not_blocked_while_rendering(brain, fake_render):
    fake_render["delay"] = 1.0
    brain.llm.queue = [_cartoon_tool("рисую!"), "я тут"]
    await brain.handle_payload(upsert("стелла мультик"))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if brain.evo.texts():
            break
    await brain.handle_payload(upsert("стелла ты тут?"))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if "я тут" in brain.evo.texts():
            break
    assert "я тут" in brain.evo.texts()
    assert not [m for m in brain.evo.sent if m["type"] == "media"]  # видео ещё рисуется
    await settle(brain, timeout=20)
    assert brain.evo.sent[-1]["type"] == "media"


async def test_one_cartoon_per_chat_and_daily_limit(brain, fake_render):
    from bot.tools import ToolError

    results = []

    async def twice(tools, prompt):
        await tools["make_cartoon"].handler(GOOD)
        try:
            await tools["make_cartoon"].handler(GOOD)
        except ToolError as exc:
            results.append(str(exc))
        return "ок"

    brain.s.anim_per_day = 1
    brain.llm.queue = [twice]
    await feed(brain, upsert("стелла мультик"))
    assert results == ["за один ответ — один мультик"]

    async def again(tools, prompt):
        try:
            await tools["make_cartoon"].handler(GOOD)
        except ToolError as exc:
            results.append(str(exc))
        return "ок"

    brain.llm.queue = [again, _cartoon_tool("ок")]
    await feed(brain, upsert("стелла ещё мультик"))
    assert "хватит" in results[-1]
    await feed(brain, upsert("стелла мультик", sender=f"{OWNER}@s.whatsapp.net", name="Хозяин"))  # владельцу можно
    assert len([m for m in brain.evo.sent if m["type"] == "media"]) == 2


async def test_disabled_and_schema(brain, fake_render):
    tools = {}

    async def grab(t, prompt):
        tools.update(t)
        return "ок"

    brain.llm.queue = [grab]
    await feed(brain, upsert("стелла привет"))
    schema = tools["make_cartoon"].input_schema
    assert schema["properties"]["cast"]["additionalProperties"]["properties"]["kind"]["enum"] == list(spec.KINDS)
    assert "make_cartoon" in brain.llm.calls[0]["system"]
    brain.s.anim_enabled = False
    from bot.tools import ToolError

    with pytest.raises(ToolError, match="выключены"):
        await tools["make_cartoon"].handler(GOOD)


# ---------- после ревью ----------
def test_place_ids_with_capitals_and_spaces():
    plan, _, _ = spec.parse({"cast": {"Барсик": {"kind": "cat"}, "Лиса Алиса": {"kind": "fox"}},
                             "scenes": [{"seconds": 3, "place": {"Барсик": {"x": 0.8, "facing": "left"},
                                                                 "Лиса Алиса": {"x": 0.2, "facing": "right"}},
                                         "events": [{"who": "Барсик", "say": "Привет"}]}]})
    place = plan["scenes"][0]["place"]
    assert place["барсик"]["x"] > 0.6 and place["барсик"]["face"] == -1
    assert place["лиса_алиса"]["x"] < 0.4 and place["лиса_алиса"]["face"] == 1


@pytest.mark.parametrize("fmt", ["square", "tall", "wide"])
def test_characters_do_not_overlap_or_leave_frame(fmt):
    cast = {k: {"kind": k} for k in ("cat", "fox", "bear", "bunny")}
    raw = {"format": fmt, "cast": cast, "scenes": [
        {"seconds": 3, "events": []},
        {"seconds": 3, "place": {"cat": {"x": 0.4}, "fox": {"x": 0.45}, "bear": {"x": 0.02}},
         "events": [{"who": "cat", "do": "walk", "to": 0.99}]}]}
    plan, _, _ = spec.parse(raw)
    w, h = plan["size"]
    for sc in plan["scenes"]:
        zoom = sc["camera"][1]["zoom"]
        xs = sorted((p["x"], plan["cast"][k]) for k, p in sc["place"].items() if k in plan["cast"])
        for x, c in xs:
            half = spec._char_w(c, w, h) / 2
            assert x - half >= 0.5 - 0.5 / zoom - 1e-6 and x + half <= 0.5 + 0.5 / zoom + 1e-6
        for (a, ca), (b, _) in zip(xs, xs[1:], strict=False):
            assert b - a >= spec._char_w(ca, w, h) * 0.75  # лица не закрывают друг друга
        for e in sc["events"]:
            if e.get("act") == "walk":
                assert e["to"][0] + spec._char_w(plan["cast"][e["who"]], w, h) / 2 <= 0.5 + 0.5 / zoom + 1e-6


def test_scene_grows_to_fit_events_and_place_omitted_means_everyone():
    plan, warnings, _ = spec.parse({"cast": {"cat": {"kind": "cat"}, "fox": {"kind": "fox"}, "bear": {"kind": "bear"}},
                                    "scenes": [{"seconds": 4, "events": [
                                        {"t": 0.5, "who": "cat", "do": "wave"},
                                        {"t": 3.5, "who": "cat", "say": "Это длинная реплика котика про звёзды"},
                                        {"t": 5, "who": "cat", "do": "jump"}]}]})
    sc = plan["scenes"][0]
    assert sc["dur"] >= 5.9 and any("продлила" in w for w in warnings)
    assert set(sc["place"]) == {"cat", "fox", "bear"}


def test_long_bubble_text_is_shrunk_not_cut():
    import cairocffi as cairo

    from bot.anim_beta import frame

    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 720, 720)
    ctx = cairo.Context(surf)
    text = spec.clean_text("Привет, друзья! Сегодня мы пойдём гулять в большой зелёный парк и будем там играть", 80)
    ctx.set_font_size(30)
    ctx.select_font_face("DejaVu Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    assert len(frame._wrap(ctx, "Ш" * 80, 300)) > 1  # слово без пробелов режется
    frame.bubble(ctx, 720, 720, text, 360, 400, 1.0)
    frame.bubble(ctx, 720, 720, "Ш" * 80, 360, 400, 1.0)


async def test_paused_chat_gets_no_video_and_limit_is_refunded(brain, fake_render):
    from datetime import date

    fake_render["delay"] = 0.3

    async def talk(tools, prompt):
        await tools["make_cartoon"].handler(GOOD)
        chat = await brain.db.get_chat_by_jid("stella", "120363000000000001@g.us")
        from datetime import timedelta

        from bot.util import utcnow

        await brain.db.update_chat(chat["id"], paused_until=utcnow() + timedelta(minutes=5))
        return "рисую"

    brain.llm.queue = [talk]
    await feed(brain, upsert("стелла мультик"))
    assert not [m for m in brain.evo.sent if m["type"] == "media"]
    chat = await brain.db.get_chat_by_jid("stella", "120363000000000001@g.us")
    used = await brain.db.kv_get(f"anim:{chat['id']}:{date.today().isoformat()}")
    assert not used or used[1] == 0
