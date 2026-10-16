"""Разбор сценария мультика (bot/anim/spec.py): примеры, синонимы и опечатки, ошибки с путём, лимиты, мусор."""

from __future__ import annotations

import copy
import json
import math
import pickle
import random
import subprocess
import sys
from pathlib import Path

import pytest

from bot.anim import catalog as C
from bot.anim.model import Spec, SpecError
from bot.anim.spec import clean_text, parse_spec
from bot.anim.timeline import compile_plan
from tests.anim_examples import EXAMPLES, PROMPTS

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
ROOT = Path(__file__).resolve().parent.parent


def one(beats, **shot):
    return {"shots": [dict(shot, beats=beats)]}


def has_warning(spec: Spec, *parts: str) -> bool:
    return any(all(p in w for p in parts) for w in spec.warnings)


# ---------- примеры ----------
def test_examples_cover_requested_scenarios():
    assert len(EXAMPLES) >= 7
    assert set(PROMPTS) == set(EXAMPLES)
    for name in ("birthday", "disco_cat", "cube3d", "argue", "space_robot", "school", "stress"):
        assert name in EXAMPLES


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_every_example_parses_and_compiles(name):
    raw = copy.deepcopy(EXAMPLES[name])
    spec = parse_spec(raw)
    assert spec.shots
    assert json.dumps(raw, ensure_ascii=False) == json.dumps(EXAMPLES[name], ensure_ascii=False)  # не портит вход
    plan = compile_plan(spec)
    assert 1.0 <= plan.duration <= 20.0 + 1e-6
    if name != "stress":
        assert spec.warnings == (), spec.warnings  # хорошие примеры — без поправок
        assert not plan.warnings, plan.warnings


def test_birthday_example_fields():
    spec = parse_spec(EXAMPLES["birthday"])
    assert spec.format == "square" and spec.size == (720, 720) and spec.seed == 7
    assert spec.caption == "Маша, с днём рождения! 🎂"  # подпись рисует WhatsApp — эмодзи остаются
    assert list(spec.cast) == ["stella", "masha", "barsik"]
    masha = spec.cast["masha"]
    assert masha.base == "girl" and masha.name == "Маша" and masha.hair == "long"
    assert masha.hair_color is not None and masha.hair_color[0] > masha.hair_color[2]  # рыжий
    assert masha.eyes == pytest.approx((0x3F / 255, 0xBF / 255, 0x5F / 255))
    assert masha.top is not None and masha.top.style == "dress" and masha.top.print == "heart"
    assert masha.accessories == ("party_hat",)
    assert spec.cast["barsik"].size == pytest.approx(0.8)
    s0, s1 = spec.shots
    assert s0.background.preset == "party" and s0.background.time == "evening"
    assert s0.camera.move == "zoom_in" and s0.camera.focus == "masha" and s0.camera.amount == pytest.approx(0.4)
    assert list(s0.place) == ["stella", "masha", "barsik"]
    assert s0.place["barsik"].lane == "front" and s0.place["stella"].facing == "right"
    assert [p.kind for p in s0.props] == ["cake", "balloon", "balloon"]
    assert s0.title is not None and s0.title.text == "С ДНЁМ РОЖДЕНИЯ!" and s0.title.seconds == 4
    b = s0.beats
    assert b[0].who == ("stella",) and b[0].do == "walk_in" and b[0].side == "left"
    assert b[1].line == "Маша, с днём рождения!" and b[1].line_kind == "say" and b[1].emotion == "excited"
    assert b[2].with_prev and b[2].do == "jump"
    assert b[3].effect is not None and b[3].effect.kind == "confetti" and b[3].with_prev and b[3].who == ()
    assert b[4].mark == "hearts" and b[4].emotion == "love"
    assert b[5].who == ("stella", "masha", "barsik") and b[5].style == "bounce" and b[5].seconds == 3
    assert s0.transition == "iris"
    assert list(s1.place) == ["masha"]
    text3d = s1.props[1]
    assert text3d.kind == "text3d" and text3d.text == "12" and text3d.material == "chrome"  # style chrome3d
    assert s1.beats[0].line_kind == "think" and s1.beats[0].do == "fly"
    assert s1.beats[2].camera == "shake" and s1.beats[2].amount == pytest.approx(0.3)


def test_minimal_spec_auto_cast_and_placement():
    spec = parse_spec({"shots": [{"beats": [{"who": "stella", "do": "wave"}]}]})
    assert list(spec.cast) == ["stella"] and spec.cast["stella"].base == "stella"
    assert spec.warnings == ()  # Стеллу можно не описывать в cast
    assert spec.format == "square" and spec.size == (720, 720)
    shot = spec.shots[0]
    assert list(shot.place) == ["stella"] and shot.place["stella"].x is None
    assert shot.background.preset == "park" and shot.transition == "fade"
    plan = compile_plan(spec)
    assert plan.placements[0].visible and plan.placements[0].x == pytest.approx(0.5)


def test_minimal_spec_without_who_uses_stella():
    spec = parse_spec({"shots": [{"beats": [{"do": "dance"}]}]})
    assert list(spec.cast) == ["stella"] and spec.shots[0].beats[0].who == ("stella",)


def test_top_level_beats_and_string_shot_parts():
    spec = parse_spec({"beats": [{"who": "cat", "say": "мяу"}], "background": "космос", "title": "Ура"})
    assert spec.cast["cat"].base == "cat"
    assert spec.shots[0].background.preset == "space"
    assert spec.shots[0].title is not None and spec.shots[0].title.text == "Ура"


# ---------- синонимы и опечатки ----------
def test_close_matches_fixed_with_warnings():
    raw = {
        "format": "widee",
        "cast": {"a": {"base": "gril", "hair": "pontail", "accessories": ["glases"]}},
        "shots": [{
            "background": {"preset": "partyy", "time": "nigth"},
            "transition": "crosfade",
            "props": [{"kind": "ballon", "anim": "spinn", "material": "goldd"}],
            "beats": [{"who": "a", "do": "dacne", "emotion": "happyy", "mark": "hearst"}],
        }],
    }
    spec = parse_spec(raw)
    assert spec.format == "wide" and spec.cast["a"].base == "girl" and spec.cast["a"].hair == "ponytail"
    assert spec.cast["a"].accessories == ("glasses",)
    shot = spec.shots[0]
    assert shot.background.preset == "party" and shot.background.time == "night" and shot.transition == "crossfade"
    assert shot.props[0].kind == "balloon" and shot.props[0].anim == "spin" and shot.props[0].material == "gold"
    beat = shot.beats[0]
    assert beat.do == "dance" and beat.emotion == "happy" and beat.mark == "hearts"
    assert has_warning(spec, "happyy", "happy") and has_warning(spec, "dacne", "dance")
    assert has_warning(spec, "shots[0].beats[0].emotion")


def test_russian_synonyms_without_warnings():
    raw = {
        "cast": {"кот": {"base": "котик", "hair": "кудри", "accessories": ["очки", "корона"]}},
        "shots": [{
            "background": {"preset": "школа", "time": "закат", "weather": "снег"},
            "camera": {"move": "наезд"},
            "props": [{"kind": "торт"}, {"kind": "дискошар", "anim": "вращается", "material": "хром"}],
            "effects": [{"kind": "конфетти", "amount": "много"}],
            "title": {"text": "Ура", "style": "золото", "anim": "падает", "position": "снизу"},
            "beats": [{"who": "кот", "do": "танцует", "emotion": "радость", "mark": "ноты", "with": "prev"},
                      {"who": "кот", "do": "машет", "to": "центр", "look": "в камеру"},
                      {"camera": "тряска"}],
            "transition": "затемнение",
        }],
    }
    spec = parse_spec(raw)
    assert spec.warnings == ()
    cat = spec.cast["кот"]
    assert cat.base == "cat" and cat.hair == "curly" and cat.accessories == ("glasses", "crown")
    s = spec.shots[0]
    assert (s.background.preset, s.background.time, s.background.weather) == ("classroom", "sunset", "snow")
    assert s.camera.move == "zoom_in"
    assert [p.kind for p in s.props] == ["cake", "disco_ball"] and s.props[1].anim == "spin"
    assert s.props[1].material == "chrome" and s.effects[0].kind == "confetti" and s.effects[0].amount == "lots"
    assert s.title is not None and (s.title.style, s.title.anim, s.title.position) == ("gold3d", "drop", "bottom")
    assert s.beats[0].do == "dance" and s.beats[0].emotion == "happy" and s.beats[0].mark == "music"
    assert s.beats[1].do == "wave" and s.beats[1].to == "center" and s.beats[1].look == "camera"
    assert s.beats[2].camera == "shake" and s.transition == "fade"


def test_catalog_aliases_all_resolve():
    for alias, base in C.BASE_ALIASES.items():
        spec = parse_spec({"cast": {"x": {"base": alias}}, "shots": [{"beats": [{"who": "x", "do": "idle"}]}]})
        assert spec.cast["x"].base == base, alias
    for alias, action in C.ACTION_ALIASES.items():
        spec = parse_spec(one([{"who": "stella", "do": alias}]))
        assert spec.shots[0].beats[0].do == action, alias
    for alias, emo in C.EMOTION_ALIASES.items():
        spec = parse_spec(one([{"who": "stella", "emotion": alias}]))
        assert spec.shots[0].beats[0].emotion == emo, alias
    for alias, bg in C.BACKGROUND_ALIASES.items():
        assert parse_spec(one([{"seconds": 1}], background=alias)).shots[0].background.preset == bg, alias
    for alias, kind in C.PROP_ALIASES.items():
        got = parse_spec(one([{"seconds": 1}], props=[{"kind": alias, "text": "А"}])).shots[0].props
        assert got and got[0].kind == kind, alias
    for alias, kind in C.EFFECT_ALIASES.items():
        assert parse_spec(one([{"effect": alias}])).shots[0].beats[0].effect.kind == kind, alias


def test_every_catalog_value_accepted_without_warnings():
    """Ни одно имя из catalog не вызывает поправок или ошибок."""
    for base in C.BASES:
        spec = parse_spec({"cast": {"x": {"base": base}}, "shots": [{"beats": [{"who": "x", "do": "wave"}]}]})
        assert spec.cast["x"].base == base and not spec.warnings
    for chunk in range(0, len(C.ACTIONS), 6):
        acts = C.ACTIONS[chunk:chunk + 6]
        spec = parse_spec(one([{"who": "stella", "do": a, "seconds": 0.5} for a in acts]))
        assert [b.do for b in spec.shots[0].beats] == list(acts) and not spec.warnings
    for emo in C.EMOTIONS:
        assert parse_spec(one([{"who": "stella", "emotion": emo}])).shots[0].beats[0].emotion == emo
    for mark in C.MARKS:
        assert parse_spec(one([{"who": "stella", "mark": mark}])).shots[0].beats[0].mark == mark
    for style in C.DANCE_STYLES:
        assert parse_spec(one([{"who": "stella", "do": "dance", "style": style}])).shots[0].beats[0].style == style
    for bg in C.BACKGROUNDS:
        for time in C.TIMES:
            for weather in C.WEATHER:
                s = parse_spec(one([{"seconds": 1}], background={"preset": bg, "time": time, "weather": weather}))
                assert (s.shots[0].background.preset, s.shots[0].background.time,
                        s.shots[0].background.weather) == (bg, time, weather)
    for kind in C.PROPS:
        prop = {"kind": kind, "text": "Привет"}
        if kind == "svg":
            prop["svg"] = "<svg xmlns='http://www.w3.org/2000/svg'/>"
        s = parse_spec(one([{"seconds": 1}], props=[prop]), svg_renderer=lambda svg: PNG)
        assert s.shots[0].props[0].kind == kind and not s.warnings
    for mat in C.MATERIALS:
        for anim in C.PROP_ANIMS:
            s = parse_spec(one([{"seconds": 1}], props=[{"kind": "sphere", "material": mat, "anim": anim}]))
            assert (s.shots[0].props[0].material, s.shots[0].props[0].anim) == (mat, anim)
    for eff in C.EFFECTS:
        for amount in C.AMOUNTS:
            s = parse_spec(one([{"effect": eff, "amount": amount}], effects=[{"kind": eff, "amount": amount}]))
            assert s.shots[0].effects[0].kind == eff and s.shots[0].beats[0].effect.amount == amount
    for style in C.TITLE_STYLES:
        for anim in C.TITLE_ANIMS:
            for pos in C.TITLE_POSITIONS:
                t = parse_spec(one([{"seconds": 1}], title={"text": "Ура", "style": style, "anim": anim,
                                                            "position": pos})).shots[0].title
                assert (t.style, t.anim, t.position) == (style, anim, pos)
    for move in C.CAMERA_MOVES:
        assert parse_spec(one([{"seconds": 1}], camera={"move": move})).shots[0].camera.move == move
    for cam in C.CAMERA_BEATS:
        assert parse_spec(one([{"camera": cam}])).shots[0].beats[0].camera == cam
    for tr in C.TRANSITIONS:
        assert parse_spec(one([{"seconds": 1}], transition=tr)).shots[0].transition == tr
    for fmt in C.FORMATS:
        assert parse_spec(dict(one([{"seconds": 1}]), format=fmt)).size == C.FORMATS[fmt]
    for kind in C.LINE_KINDS:
        b = parse_spec(one([{"who": "stella", kind: "Привет"}])).shots[0].beats[0]
        assert b.line == "Привет" and b.line_kind == kind
    for i, h in enumerate(C.HAIR):
        cs = {"base": "girl", "hair": h, "top": {"style": C.TOPS[i % len(C.TOPS)], "print": "number:7"},
              "bottom": {"style": C.BOTTOMS[i % 3]}, "skin": C.SKINS[i % 6],
              "accessories": list(C.ACCESSORIES[i:i + 3])}
        spec = parse_spec({"cast": {"a": cs}, "shots": [{"beats": [{"who": "a", "do": "idle"}]}]})
        got = spec.cast["a"]
        assert got.hair == h and got.top.style == C.TOPS[i % len(C.TOPS)] and got.top.print == "number:7"
        assert got.accessories == tuple(C.ACCESSORIES[i:i + 3]) and got.skin is not None and not spec.warnings
    for i, acc in enumerate(C.ACCESSORIES):
        spec = parse_spec({"cast": {"a": {"base": "boy", "accessories": [acc]}},
                           "shots": [{"beats": [{"who": "a", "do": "idle"}]}]})
        assert spec.cast["a"].accessories == (acc,), i


# ---------- ошибки: путь + что можно ----------
def test_unknown_action_error_has_path_and_allowed():
    with pytest.raises(SpecError) as ei:
        parse_spec(one([{"who": "stella", "do": "wave"}, {"who": "stella", "do": "moonwalkxx"}]))
    err = ei.value
    assert err.path == "shots[0].beats[1].do"
    assert "walk" in err.allowed and "dance" in err.allowed
    assert "shots[0].beats[1].do" in str(err) and "Можно:" in str(err) and "moonwalkxx" in str(err)


def test_unknown_base_error():
    with pytest.raises(SpecError) as ei:
        parse_spec({"cast": {"x": {"base": "qwzrtyx"}}, "shots": [{"beats": [{"who": "x", "do": "wave"}]}]})
    assert ei.value.path == "cast.x.base" and "cat" in ei.value.allowed


def test_unknown_actor_without_base_is_error():
    with pytest.raises(SpecError) as ei:
        parse_spec({"cast": {"masha": {"base": "girl"}}, "shots": [{"beats": [{"who": "vasya", "do": "wave"}]}]})
    assert "vasya" in str(ei.value) and "masha" in ei.value.allowed
    assert ei.value.path == "shots[0].beats[0].who"


def test_no_shots_is_error():
    for raw in ({}, {"shots": []}, {"shots": "много"}, {"shots": [{"beats": []}]}, {"shots": [{"beats": [{}]}]}):
        with pytest.raises(SpecError):
            parse_spec(raw)
    with pytest.raises(SpecError):
        parse_spec([1, 2, 3])  # type: ignore[arg-type]
    with pytest.raises(SpecError):
        parse_spec("не json")  # type: ignore[arg-type]


def test_json_string_is_accepted():
    spec = parse_spec(json.dumps(one([{"who": "stella", "do": "wave"}])))  # type: ignore[arg-type]
    assert spec.shots[0].beats[0].do == "wave"


# ---------- актёры ----------
def test_unknown_actor_auto_created_from_alias_with_warning():
    spec = parse_spec({"cast": {"masha": {"base": "girl"}},
                       "shots": [{"beats": [{"who": "кот", "do": "jump"}, {"who": "robot_2", "do": "wave"}]}]})
    assert spec.cast["кот"].base == "cat" and spec.cast["robot_2"].base == "robot"
    assert has_warning(spec, "кот", "добавила") and has_warning(spec, "robot_2", "добавила")
    plan = compile_plan(spec)
    visible = {p.actor for p in plan.placements if p.visible}
    assert {"кот", "robot_2", "masha"} <= visible


def test_actor_found_by_name_typo_and_base():
    spec = parse_spec({"cast": {"masha": {"base": "girl", "name": "Маша"}, "barsik": {"base": "cat"}},
                       "shots": [{"beats": [{"who": "Маша", "do": "wave"}, {"who": "barsk", "do": "jump"},
                                            {"who": "кот", "do": "spin"}]}]})
    assert [b.who for b in spec.shots[0].beats] == [("masha",), ("barsik",), ("barsik",)]
    assert list(spec.cast) == ["masha", "barsik"] and has_warning(spec, "barsk", "barsik")


def test_extra_bases_teacher_grandma():
    spec = parse_spec({"cast": {"t": {"base": "teacher"}, "g": {"base": "бабушка"}},
                       "shots": [{"beats": [{"who": "all", "do": "wave"}]}]})
    assert spec.cast["t"].base == "teen" and "glasses" in spec.cast["t"].accessories
    assert spec.cast["g"].base == "girl" and spec.cast["g"].hair == "bun"


def test_cast_as_list_and_strings():
    spec = parse_spec({"cast": [{"id": "Маша", "base": "girl"}, "dog", {"name": "Барсик", "base": "cat"}],
                       "shots": [{"beats": [{"who": "all", "do": "dance"}]}]})
    assert list(spec.cast) == ["маша", "dog", "барсик"]
    assert spec.cast["барсик"].name == "Барсик"
    assert spec.shots[0].beats[0].who == ("маша", "dog", "барсик")


def test_who_all_list_and_string_forms():
    raw = {"cast": {"a": "girl", "b": "boy", "c": "cat"},
           "shots": [{"place": {"a": {}, "b": {}}, "beats": [
               {"who": "all", "do": "wave"}, {"who": ["a", "b"], "do": "jump"}, {"who": "a, b", "do": "clap"},
               {"who": "все", "do": "nod"}, {"say": "и я"}]}, {"beats": [{"who": "c", "do": "wave"}]}]}
    spec = parse_spec(raw)
    beats = spec.shots[0].beats
    # в нескольких сценах «все» — это кто в сцене (place + биты), а не весь cast
    assert beats[0].who == ("a", "b") and beats[1].who == ("a", "b") and beats[2].who == ("a", "b")
    assert beats[3].who == ("a", "b")
    assert beats[4].who == ("a", "b")  # who не указан — как у предыдущего бита
    assert list(spec.shots[1].place) == ["c"]
    # в единственной сцене участвуют все из cast, даже если place описывает не всех
    spec = parse_spec({"cast": raw["cast"], "shots": raw["shots"][:1]})
    assert spec.shots[0].beats[0].who == ("a", "b", "c")


def test_who_wrong_types_handled():
    spec = parse_spec(one([{"who": "stella", "do": "wave"}, {"who": {}, "do": "jump"}, {"who": 5, "seconds": 1},
                           {"who": [None, {}, "stella"], "do": "nod"}]))
    beats = spec.shots[0].beats
    assert beats[1].who == ("stella",) and beats[3].who == ("stella",)
    assert has_warning(spec, "beats[1].who")


def test_on_screen_limit_and_cast_limit():
    cast = {f"a{i}": {"base": "cat"} for i in range(7)}
    spec = parse_spec({"cast": cast, "shots": [{"beats": [{"who": "all", "do": "dance"}]}]})
    assert len(spec.cast) == C.MAX_CAST and has_warning(spec, "cast")
    assert len(spec.shots[0].place) <= C.MAX_ON_SCREEN
    assert len(spec.shots[0].beats[0].who) <= C.MAX_ON_SCREEN
    with pytest.raises(SpecError):  # шестой актёр, которого создать некуда
        parse_spec({"cast": {f"a{i}": {"base": "cat"} for i in range(5)},
                    "shots": [{"beats": [{"who": "dog", "do": "wave"}]}]})


# ---------- лимиты ----------
def test_shot_and_beat_limits_trimmed():
    shots = [{"beats": [{"who": "stella", "do": "nod", "seconds": 0.3}] * 15} for _ in range(6)]
    spec = parse_spec({"shots": shots}, max_seconds=60)
    assert len(spec.shots) <= C.MAX_SHOTS
    assert all(len(s.beats) <= C.MAX_BEATS_PER_SHOT for s in spec.shots)
    assert sum(len(s.beats) for s in spec.shots) == C.MAX_BEATS
    assert has_warning(spec, "сцен больше 4") and has_warning(spec, "битов больше 12")
    assert has_warning(spec, "всего битов больше 30")
    spec = parse_spec({"shots": [{"beats": [{"who": "stella", "do": "nod"}]}] * 6})
    assert len(spec.shots) == C.MAX_SHOTS


def test_text_limits_and_truncation_warnings():
    long_line = "очень " * 40
    raw = {"cast": {"masha": {"base": "girl", "name": "Мария-Антуанетта Петровна"}},
           "caption": "к" * 400,
           "shots": [{"title": {"text": "ОЧЕНЬ ДЛИННЫЙ ЗАГОЛОВОК ДЛЯ МУЛЬТИКА ПРО ВСЁ"},
                      "props": [{"kind": "text3d", "text": "ПРИВЕТИКИ-ПИСТОЛЕТИКИ"}],
                      "beats": [{"who": "masha", "say": long_line}]}]}
    spec = parse_spec(raw)
    line = spec.shots[0].beats[0].line
    assert line is not None and len(line) <= C.MAX_LINE_CHARS and line.endswith("…")
    assert has_warning(spec, "сократила до 100")
    assert len(spec.shots[0].title.text) <= C.MAX_TITLE_CHARS
    assert len(spec.shots[0].props[0].text) <= C.MAX_TEXT3D_CHARS
    assert len(spec.cast["masha"].name) <= C.MAX_NAME_CHARS
    assert len(spec.caption) <= C.MAX_CAPTION_CHARS


def test_svg_props_limit_and_renderer():
    calls: list[str] = []

    def render(svg: str) -> bytes:
        calls.append(svg)
        return PNG

    svg = "<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'><circle r='5'/></svg>"
    props = [{"kind": "svg", "svg": svg} for _ in range(5)]
    shots = [{"props": props[:3], "beats": [{"seconds": 1}]}, {"props": props[3:], "beats": [{"seconds": 1}]}]
    spec = parse_spec({"shots": shots}, svg_renderer=render)
    got = [p for s in spec.shots for p in s.props]
    assert len(got) == C.MAX_SVG_PROPS == len(calls) and all(p.svg_png == PNG for p in got)
    assert has_warning(spec, "SVG-предметов не больше")
    # без рендерера и при сбое — предмет выкидывается с предупреждением
    spec = parse_spec(one([{"seconds": 1}], props=[{"kind": "svg", "svg": svg}]))
    assert spec.shots[0].props == () and has_warning(spec, "SVG")

    def boom(svg: str) -> bytes:
        raise RuntimeError("cairosvg упал")

    spec = parse_spec(one([{"seconds": 1}], props=[{"svg": svg}, {"kind": "svg", "svg": "не svg"}]),
                      svg_renderer=boom)
    assert spec.shots[0].props == () and has_warning(spec, "не получилось")
    spec = parse_spec(one([{"seconds": 1}], props=[{"kind": "svg", "svg": svg}]), svg_renderer=lambda s: b"GIF89")
    assert spec.shots[0].props == ()


def test_props_effects_3d_limits():
    props = [{"kind": k} for k in ("cube", "sphere", "gem", "star", "heart", "coin", "dice", "donut", "tree", "car")]
    effects = [{"kind": "confetti"}] * 8
    spec = parse_spec({"cast": {"r": {"base": "robot3d"}},
                       "shots": [{"props": props, "effects": effects,
                                  "beats": [{"who": "r", "do": "wave", "effect": "hearts"}]}]})
    s = spec.shots[0]
    assert len(s.props) <= C.MAX_PROPS_PER_SHOT
    n3d = sum(p.kind in C.PROPS_3D for p in s.props) + sum(spec.cast[a].base in C.BASES_3D for a in s.place)
    assert n3d <= C.MAX_3D_ON_SCREEN
    n_eff = len(s.effects) + sum(b.effect is not None for b in s.beats)
    assert n_eff <= C.MAX_EFFECTS_PER_SHOT
    assert has_warning(spec, "3D") and has_warning(spec, "эффектов")


def test_accessories_limit():
    spec = parse_spec({"cast": {"a": {"base": "girl", "accessories": ["glasses", "cap", "bow", "scarf", "cape"]}},
                       "shots": [{"beats": [{"who": "a", "do": "wave"}]}]})
    assert spec.cast["a"].accessories == ("glasses", "cap", "bow") and has_warning(spec, "аксессуаров")


def test_json_size_limit():
    with pytest.raises(SpecError, match="слишком длинный"):
        parse_spec(one([{"who": "stella", "say": "а" * 100}] * 10, junk="ж" * C.MAX_SPEC_JSON))
    svg = "<svg xmlns='http://www.w3.org/2000/svg'>" + "<g/>" * 10_000 + "</svg>"  # 40 КБ SVG не считается
    spec = parse_spec(one([{"seconds": 1}], props=[{"kind": "svg", "svg": svg}]), svg_renderer=lambda s: PNG)
    assert spec.shots[0].props[0].svg_png == PNG


# ---------- числа и мусор ----------
def test_numbers_nan_inf_huge_negative():
    nan, inf = float("nan"), float("inf")
    raw = {"seed": inf,
           "cast": {"a": {"base": "cat", "size": 1e308}, "b": {"base": "dog", "size": -5}},
           "shots": [{"seconds": nan, "camera": {"move": "zoom_in", "amount": 10**400},
                      "place": {"a": {"x": nan}, "b": {"x": -3}},
                      "props": [{"kind": "cube", "x": inf, "y": -inf, "size": 10**400}],
                      "effects": [{"kind": "snow", "at": -1, "seconds": 1e9, "x": nan}],
                      "title": {"text": "А", "at": inf, "seconds": -inf},
                      "beats": [{"who": "a", "do": "jump", "seconds": -5, "at": nan, "amount": 1e30},
                                {"who": "b", "do": "walk", "to": inf}, {"who": "b", "do": "walk", "to": "1e999"}]}]}
    spec = parse_spec(raw)
    a, b = spec.cast["a"], spec.cast["b"]
    assert a.size == 1.4 and b.size == 0.6
    s = spec.shots[0]
    assert s.seconds is None and s.camera.amount == 1.0
    assert s.place["a"].x is None and s.place["b"].x == 0.0
    p = s.props[0]
    assert (p.x, p.y, p.size) == (0.5, 0.5, 0.8)  # бесконечность — не число: место по умолчанию
    e = s.effects[0]
    assert e.at == 0.0 and e.seconds == 20.0 and e.x is None
    assert s.beats[0].seconds == pytest.approx(0.2) and s.beats[0].at is None and s.beats[0].amount == 1.0
    assert s.beats[1].to is None
    assert 0 <= spec.seed < 2**31
    plan = compile_plan(spec)
    assert math.isfinite(plan.duration) and plan.duration <= 20.0 + 1e-6


def test_strings_stay_plain_text():
    evil = "__import__('os').system('rm -rf /')"
    spec = parse_spec({"caption": evil, "cast": {"a": {"base": "girl", "name": evil[:20]}},
                       "shots": [{"title": {"text": "{{7*7}} ${x}"}, "background": {"preset": "classroom",
                                                                                     "text": evil},
                                  "beats": [{"who": "a", "say": evil}]}]})
    assert spec.shots[0].beats[0].line == evil and spec.caption == evil
    assert spec.shots[0].title.text == "{{7*7}} ${x}"
    assert spec.shots[0].background.text == evil


def test_clean_text_emoji_and_limits():
    text, dropped = clean_text("Привет ❤ ⭐ 🎵 😊!", 100)
    assert text == "Привет ♥ ★ ♪ ☺!" and not dropped
    text, dropped = clean_text("Торт 🎂 и 🦄", 100)
    assert text == "Торт и" and dropped
    text, dropped = clean_text("слово " * 30, 20)
    assert len(text) <= 20 and text.endswith("…") and dropped
    assert clean_text("  много    пробелов\n\n\nи строк  ", 100) == ("много пробелов\nи строк", False)
    assert clean_text(12345, 3)[0] == "12…"  # type: ignore[arg-type]
    assert clean_text("abc", 0) == ("", True)


def test_emoji_in_line_warns():
    spec = parse_spec(one([{"who": "stella", "say": "Ура 🦄🦄"}]))
    assert spec.shots[0].beats[0].line == "Ура" and has_warning(spec, "эмодзи")


# ---------- камера и прочее ----------
def test_camera_beat_promotions():
    spec = parse_spec(one([{"camera": "pan_left"}, {"camera": "static"}, {"camera": {"move": "punch", "focus": "stella",
                                                                                     "amount": 0.7}},
                           {"who": "stella", "do": "wave"}]))
    s = spec.shots[0]
    assert s.camera.move == "pan_left" and has_warning(spec, "pan_left")
    assert [b.camera for b in s.beats[:2]] == ["reset", "punch"]
    assert s.beats[1].camera_focus == "stella" and s.beats[1].amount == pytest.approx(0.7)


def test_effect_beat_forms():
    spec = parse_spec(one([{"effect": {"kind": "hearts", "amount": "lots", "seconds": 2}},
                           {"effect": "confetti", "seconds": 3, "amount": 0.9, "x": 0.3},
                           {"effect": "дракон"}, {"who": "stella", "do": "wave", "effect": "sparkles"}]))
    b = spec.shots[0].beats
    assert b[0].effect.kind == "hearts" and b[0].effect.amount == "lots" and b[0].effect.seconds == 2
    assert b[1].effect.kind == "confetti" and b[1].effect.seconds == 3 and b[1].effect.amount == "lots"
    assert b[1].effect.x == pytest.approx(0.3)
    assert len(b) == 3 and b[2].effect.kind == "sparkles" and b[2].do == "wave"
    assert has_warning(spec, "дракон")


def test_print_and_outfit_forms():
    spec = parse_spec({"cast": {
        "a": {"base": "boy", "top": {"style": "jersey", "print": "7"}, "bottom": "шорты"},
        "b": {"base": "girl", "top": "красный", "bottom": {"style": "юбка", "color": "#000"}},
        "c": {"base": "girl", "top": {"style": "tshirt", "print": "МАША"}},
        "d": {"base": "boy", "top": {"print": "text:ВАСЯВАСЯ"}},
    }, "shots": [{"beats": [{"who": "all", "do": "wave"}]}]})
    a, b, c, d = (spec.cast[k] for k in "abcd")
    assert a.top.style == "tshirt" and a.top.print == "number:7" and a.bottom.style == "shorts"
    assert b.top.style == "tshirt" and b.top.color[0] > 0.8 and b.bottom.style == "skirt"
    assert b.bottom.color == (0.0, 0.0, 0.0)
    assert c.top.print == "text:МАША"
    assert d.top.print is not None and d.top.print.startswith("text:") and len(d.top.print) <= len("text:") + 6


def test_seed_default_is_deterministic_and_content_based():
    a = parse_spec(EXAMPLES["argue"] | {"seed": None})
    b = parse_spec(copy.deepcopy(EXAMPLES["argue"]) | {"seed": None})
    c = parse_spec(EXAMPLES["school"] | {"seed": None})
    assert a.seed == b.seed != c.seed and 0 <= a.seed < 2**31
    assert parse_spec(EXAMPLES["argue"]).seed == 11


def test_parse_is_deterministic():
    for name, raw in EXAMPLES.items():
        s1, s2 = parse_spec(raw), parse_spec(copy.deepcopy(raw))
        assert s1 == s2, name
        assert pickle.dumps(s1) == pickle.dumps(s2), name


def test_max_seconds_passed_to_spec():
    assert parse_spec(EXAMPLES["birthday"], max_seconds=12).max_seconds == 12
    assert parse_spec(EXAMPLES["birthday"], max_seconds=float("nan")).max_seconds == 20.0
    spec = parse_spec(one([{"who": "stella", "do": "dance", "seconds": 50}]), max_seconds=10)
    assert spec.shots[0].beats[0].seconds == 10


def test_spec_and_timeline_do_not_import_cairo_or_numpy():
    code = ("import sys; import bot.anim.spec, bot.anim.timeline; "
            "bad = [m for m in sys.modules if m.split('.')[0] in ('cairo', 'cairocffi', 'numpy', 'fontTools', 'PIL')]; "
            "print(','.join(bad))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""


# ---------- fuzz: мусор на входе → только SpecError, лимиты всегда соблюдены ----------
_WORDS = (
    "all", "stella", "кот", "masha", "dance", "happyy", "left", "right", "prev", "offscreen", "confetti", "cube",
    "text3d", "svg", "gold", "say", "#ff00ff", "рыжий", "walk_in", "hug", "zoom_in", "iris", "", " ", "🎉🦄",
    "__import__('os')", "\x00\x01\x7f", "nan", "1e999", "-0", "0.5", "ПРИВЕТ", "все", "who", "beats",
)
_KEYS = (
    "who", "do", "say", "think", "shout", "whisper", "emotion", "mark", "to", "from", "target", "look", "style",
    "seconds", "at", "with", "effect", "camera", "amount", "focus", "kind", "x", "y", "size", "text", "material",
    "anim", "svg", "preset", "time", "weather", "move", "lane", "facing", "base", "name", "hair", "top", "bottom",
    "accessories", "color", "id", "title", "props", "effects", "place", "background", "transition", "beats",
    "shots", "cast", "format", "caption", "seed", "unknown_key", "__class__", "",
)


def _scalar(r: random.Random):
    k = r.randrange(12)
    if k == 0:
        return r.choice([None, True, False])
    if k == 1:
        return r.choice([0, -1, 1, 7, 10**400, -(10**30), 2**63])
    if k == 2:
        return r.choice([0.5, -0.5, 1e308, -1e308, float("nan"), float("inf"), -float("inf"), 1e-300, 3.7])
    if k == 3:
        return r.uniform(-2, 25)
    if k == 4:
        return "x" * (5000 if r.random() < 0.08 else r.choice([1, 30, 150]))
    if k == 5:
        return "".join(chr(r.randrange(0x20, 0x2FFFF)) for _ in range(r.randrange(1, 40)))
    if k in (6, 7):
        return r.choice(C.ACTIONS + C.EMOTIONS + C.MARKS + C.PROPS + C.EFFECTS + C.BASES + C.BACKGROUNDS)
    return r.choice(_WORDS)


def _junk(r: random.Random, depth: int = 0):
    k = r.random()
    if depth >= 4 or k < 0.45:
        return _scalar(r)
    if k < 0.7:
        return [_junk(r, depth + 1) for _ in range(r.randrange(0, 6))]
    return {r.choice(_KEYS): _junk(r, depth + 1) for _ in range(r.randrange(0, 6))}


def _deep(r: random.Random, n: int):
    obj: object = _scalar(r)
    for _ in range(n):
        obj = [obj] if r.random() < 0.5 else {"shots": obj, "beats": obj}
    return obj


def _mutate(r: random.Random, obj, rate: float = 1.0):
    """Испортить случайные места в настоящем сценарии (rate — насколько сильно)."""
    if isinstance(obj, dict):
        out = {}
        for key, val in obj.items():
            roll = r.random() / rate
            if roll < 0.08:
                continue  # выкинуть ключ
            if roll < 0.2:
                out[key] = _junk(r)
            elif roll < 0.22:
                out[key] = [val, val]
            else:
                out[key] = _mutate(r, val, rate)
        if r.random() < 0.3 * rate:
            out[r.choice(_KEYS)] = _junk(r)
        return out
    if isinstance(obj, list):
        items = [_mutate(r, v, rate) for v in obj]
        if r.random() < 0.1 * rate:
            items = items * 2
        if r.random() < 0.2 * rate:
            items.append(_junk(r))
        if r.random() < 0.1 * rate:
            r.shuffle(items)
        return items
    if r.random() < 0.15 * rate:
        return _junk(r)
    return obj


def _random_spec(r: random.Random) -> dict:
    """Похожий на настоящий сценарий, но с перебором лимитов и случайными значениями."""
    n_cast = r.randrange(0, 8) if r.random() < 0.3 else r.randrange(0, 4)
    cast = {f"a{i}": {"base": r.choice(C.BASES + ("кот", "teacher", "qwerty" if r.random() < 0.3 else "cat")),
                      "accessories": r.sample(C.ACCESSORIES, r.randrange(0, 6)),
                      "size": r.uniform(-1, 3)} for i in range(n_cast)}
    ids = list(cast) + ["all", "stella", "кот"] + (["nobody"] if r.random() < 0.2 else [])
    shots = []
    for _ in range(r.randrange(1, 7)):
        beats = []
        for _ in range(r.randrange(0, 16)):
            b = {"who": r.choice(ids + [ids[:3]]), "do": r.choice(C.ACTIONS + (None,))}
            for key in r.sample(("say", "think", "emotion", "mark", "to", "target", "seconds", "at", "with",
                                 "effect", "camera", "style", "amount", "from", "look"), r.randrange(0, 6)):
                b[key] = {
                    "say": "слово " * r.randrange(1, 25), "think": "хм", "emotion": r.choice(C.EMOTIONS),
                    "mark": r.choice(C.MARKS), "to": r.choice([r.random(), r.choice(ids), "left", "offscreen"]),
                    "target": r.choice(ids), "seconds": r.uniform(-2, 12), "at": r.uniform(-1, 25), "with": "prev",
                    "effect": r.choice(C.EFFECTS), "camera": r.choice(C.CAMERA_BEATS + C.CAMERA_MOVES),
                    "style": r.choice(C.DANCE_STYLES), "amount": r.random(), "from": "right",
                    "look": r.choice(ids + ["camera"]),
                }[key]
            beats.append(b)
        shots.append({
            "background": {"preset": r.choice(C.BACKGROUNDS), "weather": r.choice(C.WEATHER)},
            "camera": {"move": r.choice(C.CAMERA_MOVES), "focus": r.choice(ids)},
            "place": {a: {"x": r.uniform(-0.5, 1.5), "lane": r.choice(C.LANES)} for a in r.sample(ids, 2)},
            "props": [{"kind": r.choice(C.PROPS), "text": "ТЕКСТ" * r.randrange(1, 5), "svg": "<svg/>"}
                      for _ in range(r.randrange(0, 10))],
            "effects": [{"kind": r.choice(C.EFFECTS), "seconds": r.uniform(0, 30)} for _ in range(r.randrange(0, 9))],
            "title": {"text": "ЗАГОЛОВОК " * r.randrange(1, 6), "style": r.choice(C.TITLE_STYLES)},
            "beats": beats,
            "seconds": r.choice([None, r.uniform(-5, 40)]),
            "transition": r.choice(C.TRANSITIONS),
        })
    return {"format": r.choice(tuple(C.FORMATS) + ("bad",)), "cast": cast, "shots": shots,
            "caption": "п" * r.randrange(0, 400), "seed": r.choice([None, r.randrange(10**6), "abc"])}


def _check_spec_limits(spec: Spec) -> None:
    assert isinstance(spec, Spec)
    assert spec.format in C.FORMATS and spec.size == C.FORMATS[spec.format]
    assert len(spec.cast) <= C.MAX_CAST and 1 <= len(spec.shots) <= C.MAX_SHOTS
    assert sum(len(s.beats) for s in spec.shots) <= C.MAX_BEATS
    assert len(spec.caption) <= C.MAX_CAPTION_CHARS and 0 <= spec.seed < 2**31
    n_svg = 0
    for cs in spec.cast.values():
        assert cs.base in C.BASES and len(cs.name) <= C.MAX_NAME_CHARS and 0.6 <= cs.size <= 1.4
        assert len(cs.accessories) <= C.MAX_ACCESSORIES and set(cs.accessories) <= set(C.ACCESSORIES)
        assert cs.hair is None or cs.hair in C.HAIR
        for col in (cs.skin, cs.hair_color, cs.eyes, cs.shoes, cs.color, cs.accent):
            assert col is None or (len(col) == 3 and all(0.0 <= v <= 1.0 for v in col))
    for s in spec.shots:
        assert s.background.preset in C.BACKGROUNDS and s.background.time in C.TIMES
        assert s.background.weather in C.WEATHER and s.transition in C.TRANSITIONS
        assert s.camera.move in C.CAMERA_MOVES and 0.0 <= s.camera.amount <= 1.0
        assert s.camera.focus is None or s.camera.focus in s.place
        assert len(s.place) <= C.MAX_ON_SCREEN and set(s.place) <= set(spec.cast)
        for p in s.place.values():
            assert p.x is None or 0.0 <= p.x <= 1.0
            assert p.lane in C.LANES and (p.facing is None or p.facing in C.FACINGS)
        assert len(s.beats) <= C.MAX_BEATS_PER_SHOT and len(s.props) <= C.MAX_PROPS_PER_SHOT
        n3d = sum(p.kind in C.PROPS_3D for p in s.props) + sum(spec.cast[a].base in C.BASES_3D for a in s.place)
        assert n3d <= C.MAX_3D_ON_SCREEN
        assert len(s.effects) + sum(b.effect is not None for b in s.beats) <= C.MAX_EFFECTS_PER_SHOT
        for p in s.props:
            assert p.kind in C.PROPS and p.anim in C.PROP_ANIMS and p.lane in C.LANES
            assert p.material is None or p.material in C.MATERIALS
            assert 0 <= p.x <= 1 and 0 <= p.y <= 1 and 0.03 <= p.size <= 0.8
            assert len(p.text) <= (C.MAX_TEXT3D_CHARS if p.kind == "text3d" else 24)
            n_svg += p.kind == "svg"
        for e in s.effects:
            assert e.kind in C.EFFECTS and e.amount in C.AMOUNTS
        if s.title is not None:
            assert 0 < len(s.title.text) <= C.MAX_TITLE_CHARS and s.title.style in C.TITLE_STYLES
            assert s.title.anim in C.TITLE_ANIMS and s.title.position in C.TITLE_POSITIONS
        for b in s.beats:
            assert set(b.who) <= set(s.place)
            assert b.do is None or b.do in C.ACTIONS
            assert b.line is None or len(b.line) <= C.MAX_LINE_CHARS
            assert b.line_kind in C.LINE_KINDS
            assert b.emotion is None or b.emotion in C.EMOTIONS
            assert b.mark is None or b.mark in C.MARKS
            assert b.camera is None or b.camera in C.CAMERA_BEATS
            assert b.style is None or b.style in C.DANCE_STYLES + ("sync",)
            assert b.side is None or b.side in ("left", "right")
            assert b.target is None or b.target in s.place
            if isinstance(b.to, str):
                assert b.to in ("left", "right", "center", "offscreen") or b.to in s.place
            elif b.to is not None:
                assert 0.0 <= b.to <= 1.0
            for v in (b.seconds, b.at, b.amount):
                assert v is None or (math.isfinite(v) and v >= 0)
            if b.effect is not None:
                assert b.effect.kind in C.EFFECTS and b.effect.amount in C.AMOUNTS
    assert n_svg <= C.MAX_SVG_PROPS
    assert len(spec.warnings) <= 20


def _check_plan(plan) -> None:
    assert 1.0 <= plan.duration <= 20.0 + 1e-6
    times = [(ev.t0, ev.t1) for lst in (plan.clips, plan.lines, plan.marks, plan.looks, plan.effects,
                                         plan.titles, plan.cameras, plan.emotions) for ev in lst]
    for t0, t1 in times:
        assert math.isfinite(t0) and math.isfinite(t1) and -1e-6 <= t0 <= t1 <= plan.duration + 1e-6
    seen: dict[tuple[str, int], float] = {}
    for c in sorted(plan.clips, key=lambda c: c.t0):
        key = (c.actor, c.layer)
        assert c.t0 >= seen.get(key, -1.0) - 1e-6, (c, seen.get(key))
        seen[key] = c.t1


def test_fuzz_only_spec_errors_and_limits_hold():
    ok = errors = 0
    for seed in range(360):
        r = random.Random(seed)
        mode = seed % 6
        if mode == 0:
            raw = _junk(r)
            if not isinstance(raw, dict) or r.random() < 0.5:
                raw = {"shots": [_junk(r) for _ in range(r.randrange(0, 5))], "cast": _junk(r)}
        elif mode == 1:
            raw = _mutate(r, copy.deepcopy(EXAMPLES[r.choice(sorted(EXAMPLES))]))
        elif mode == 2:
            raw = _random_spec(r)
        elif mode == 3:
            raw = _deep(r, r.randrange(30, 300)) if r.random() < 0.3 else _mutate(r, _random_spec(r))
        elif mode == 4:
            raw = {"shots": [{"beats": [{r.choice(_KEYS): _junk(r) for _ in range(4)} for _ in range(5)]}],
                   "cast": {str(_scalar(r))[:30]: {r.choice(_KEYS): _junk(r)} for _ in range(3)}}
        else:
            raw = _mutate(r, copy.deepcopy(EXAMPLES[r.choice(sorted(EXAMPLES))]), rate=0.25)
        render = (lambda svg: PNG) if seed % 3 else None
        try:
            spec = parse_spec(raw, svg_renderer=render)  # type: ignore[arg-type]
        except SpecError as exc:
            errors += 1
            assert str(exc)
            continue
        _check_spec_limits(spec)
        try:
            plan = compile_plan(spec)
        except SpecError as exc:
            errors += 1
            assert "можно до" in str(exc) and "сцена 1" in str(exc)
            continue
        ok += 1
        _check_plan(plan)
    assert ok > 60 and errors > 20  # и разобранные, и отвергнутые встречаются
