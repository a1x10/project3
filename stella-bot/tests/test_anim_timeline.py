"""План мультика по времени (bot/anim/timeline.py): порядок битов, реплики, сжатие, позиции, камера, эффекты."""

from __future__ import annotations

import copy
import dataclasses
import pickle

import pytest

from bot.anim import catalog as C
from bot.anim import timeline as T
from bot.anim.model import Plan, SpecError
from bot.anim.spec import parse_spec
from bot.anim.timeline import compile_plan, line_seconds
from tests.anim_examples import EXAMPLES

LEAD, BREATH, STAGGER = T.LEAD, T.BREATH, T.STAGGER


def plan_of(beats, cast=None, max_seconds=20.0, **shot) -> Plan:
    raw = {"shots": [dict(shot, beats=beats)]}
    if cast is not None:
        raw["cast"] = cast
    return compile_plan(parse_spec(raw, max_seconds=max_seconds))


def clips(plan: Plan, actor: str | None = None, action: str | None = None):
    return [c for c in plan.clips if (actor is None or c.actor == actor) and (action is None or c.action == action)]


def placement(plan: Plan, actor: str, shot: int = 0):
    return next(p for p in plan.placements if p.actor == actor and p.shot == shot)


def check_invariants(plan: Plan) -> None:
    """Общие гарантии плана: всё в пределах ролика и своей сцены, на слое без перекрытий, эмоции не пересекаются."""
    assert plan.shots[0].t0 == 0.0 and plan.shots[-1].t1 == pytest.approx(plan.duration)
    for a, b in zip(plan.shots, plan.shots[1:], strict=False):
        assert a.t1 == pytest.approx(b.t0)
    assert plan.shots[-1].transition == "cut"
    for lst in (plan.clips, plan.lines, plan.marks, plan.looks, plan.effects, plan.titles, plan.cameras,
                plan.emotions):
        for ev in lst:
            assert -1e-9 <= ev.t0 < ev.t1 + 1e-9 and ev.t1 <= plan.duration + 1e-6, ev
    for c in plan.clips:  # клип не вылезает из своей сцены
        shot = plan.shot_at(c.t0 + 1e-6)
        assert c.t1 <= shot.t1 + 1e-6, c
        assert c.action in C.ACTIONS and c.layer in (0, 1)
    last: dict[tuple[str, int], float] = {}
    for c in sorted(plan.clips, key=lambda c: c.t0):
        assert c.t0 >= last.get((c.actor, c.layer), -1.0) - 1e-6, c
        last[(c.actor, c.layer)] = c.t1
    by_actor: dict[str, float] = {}
    for e in sorted(plan.emotions, key=lambda e: e.t0):
        assert e.emotion in C.EMOTIONS
        assert e.t0 >= by_actor.get(e.actor, 0.0) - 1e-6, e
        by_actor[e.actor] = e.t1
    for p in plan.placements:
        assert p.actor in plan.cast and 0 <= p.shot < len(plan.shots) and p.facing in (-1, 0, 1)
    assert len(plan.placements) == len(plan.cast) * len(plan.shots)
    for e in plan.effects:
        assert e.kind in C.EFFECTS and e.amount in C.AMOUNTS
    for c in plan.cameras:
        assert c.kind in C.CAMERA_MOVES + C.CAMERA_BEATS


# ---------- длительности и порядок битов ----------
def test_line_seconds():
    assert line_seconds("") == 1.0
    assert line_seconds("а" * 13) == pytest.approx(1.6)
    assert line_seconds("а" * 26) == pytest.approx(2.6)
    assert line_seconds("а" * 100) == 6.0
    assert line_seconds("а" * 32, cps=16) == pytest.approx(2.6)


def test_sequential_beats_with_breath():
    plan = plan_of([{"who": "stella", "do": "wave"}, {"who": "stella", "do": "jump"},
                    {"who": "stella", "do": "spin", "seconds": 2}])
    wave, jump, spin = clips(plan, "stella")
    assert wave.t0 == pytest.approx(LEAD) and wave.t1 == pytest.approx(LEAD + 1.2)
    assert jump.t0 == pytest.approx(wave.t1 + BREATH) and jump.t1 - jump.t0 == pytest.approx(1.0)
    assert spin.t0 == pytest.approx(jump.t1 + BREATH) and spin.t1 - spin.t0 == pytest.approx(2.0)
    assert plan.duration == pytest.approx(spin.t1 + T.TAIL)
    check_invariants(plan)


def test_with_prev_and_at():
    cast = {"a": "girl", "b": "cat"}
    plan = plan_of([{"who": "a", "do": "dance"}, {"who": "b", "do": "jump", "with": "prev"},
                    {"who": "b", "do": "spin", "at": 5.0}, {"who": "a", "do": "wave"},
                    {"who": "b", "do": "nod", "with": "prev"}], cast=cast)
    dance, wave = clips(plan, "a", "dance")[0], clips(plan, "a", "wave")[0]
    jump, spin, nod = clips(plan, "b", "jump")[0], clips(plan, "b", "spin")[0], clips(plan, "b", "nod")[0]
    assert jump.t0 == pytest.approx(dance.t0)
    assert spin.t0 == pytest.approx(5.0)
    assert wave.t0 == pytest.approx(dance.t1 + BREATH)  # at-бит не сдвигает очередь
    assert nod.t0 == pytest.approx(wave.t0)  # with_prev после at-бита — вместе с предыдущим по списку
    check_invariants(plan)


def test_group_stagger_and_sync():
    cast = {"a": "girl", "b": "boy", "c": "cat"}
    plan = plan_of([{"who": "all", "do": "jump"}], cast=cast)
    t0s = [clips(plan, a, "jump")[0].t0 for a in "abc"]
    assert t0s == pytest.approx([LEAD, LEAD + STAGGER, LEAD + 2 * STAGGER])
    plan = plan_of([{"who": "all", "do": "dance", "style": "sync"}], cast=cast)
    t0s = [clips(plan, a, "dance")[0].t0 for a in "abc"]
    assert t0s == pytest.approx([LEAD] * 3)
    assert all(c.params["style"] == "bounce" for c in clips(plan, action="dance"))
    plan = plan_of([{"who": ["c", "a"], "do": "dance", "style": "robot"}], cast=cast)
    assert clips(plan, "c")[0].t0 < clips(plan, "a")[0].t0
    assert clips(plan, "c")[0].params == {"style": "robot"}


def test_line_and_action_together():
    text = "Маша, с днём рождения!"
    plan = plan_of([{"who": "stella", "do": "wave", "say": text, "emotion": "excited", "mark": "hearts"},
                    {"who": "stella", "do": "nod"}])
    line = plan.lines[0]
    wave = clips(plan, "stella", "wave")[0]
    assert line.t0 == pytest.approx(wave.t0) and line.kind == "say" and line.text == text
    assert line.t1 - line.t0 == pytest.approx(line_seconds(text))
    assert wave.t1 - wave.t0 == pytest.approx(1.2)  # жест короче реплики — не растягивается
    nod = clips(plan, "stella", "nod")[0]
    assert nod.t0 == pytest.approx(line.t1 + BREATH)
    mark = plan.marks[0]
    assert mark.kind == "hearts" and mark.t1 - mark.t0 == pytest.approx(T.MARK_SECONDS)
    assert plan.emotions[0].emotion == "excited" and plan.emotions[0].t0 == pytest.approx(line.t0)


def test_loopable_action_stretches_to_line_and_resumes_after_interrupt():
    long_text = "Я танцую и рассказываю длинную-длинную историю"
    plan = plan_of([{"who": "stella", "do": "dance", "say": long_text}])
    dance = clips(plan, "stella", "dance")[0]
    assert dance.t1 - dance.t0 == pytest.approx(line_seconds(long_text))
    plan = plan_of([{"who": "stella", "do": "dance", "seconds": 4}, {"who": "stella", "do": "jump", "at": 1.5}])
    parts = [(c.action, round(c.t0, 2), round(c.t1, 2)) for c in clips(plan, "stella")]
    assert parts == [("dance", LEAD, 1.5), ("jump", 1.5, 2.5), ("dance", 2.5, LEAD + 4)]
    check_invariants(plan)


def test_talk_without_line_and_think_line():
    plan = plan_of([{"who": "stella", "do": "talk"}, {"who": "stella", "think": "Хм"}])
    assert clips(plan, "stella", "talk")[0].layer == 1
    assert plan.lines[0].kind == "think"


def test_pause_effect_and_camera_beats_take_time():
    plan = plan_of([{"seconds": 2}, {"who": "stella", "do": "wave"}])
    assert clips(plan, "stella", "wave")[0].t0 == pytest.approx(LEAD + 2 + BREATH)
    plan = plan_of([{"effect": "confetti"}, {"who": "stella", "do": "wave"}])
    eff = plan.effects[0]
    assert eff.t0 == pytest.approx(LEAD)
    assert eff.t1 == pytest.approx(min(LEAD + T.EFFECT_SECONDS["confetti"], plan.duration))  # не дольше сцены
    assert clips(plan, "stella", "wave")[0].t0 == pytest.approx(LEAD + T.PAUSE + BREATH)
    plan = plan_of([{"camera": "zoom_in"}, {"who": "stella", "do": "wave"}])
    assert clips(plan, "stella", "wave")[0].t0 == pytest.approx(LEAD + 0.6 + BREATH)


# ---------- сжатие и предел ----------
def _long_spec(n_shots: int, line_len: int) -> dict:
    line = ("слово " * 30)[:line_len]
    return {"cast": {"a": "girl", "b": "boy"},
            "shots": [{"beats": [{"who": "a", "say": line}, {"who": "b", "say": line}, {"who": "a", "do": "dance"}]}
                      for _ in range(n_shots)]}


def test_compression_up_to_30_percent_with_warning():
    spec = parse_spec(_long_spec(2, 40))
    natural = T._Build(spec, 24, T._Level())
    natural.run()
    assert 20.0 < natural.duration <= 26.0
    plan = compile_plan(spec)
    assert plan.duration <= 20.0 + 1e-6 and plan.duration > 19.0  # ужали ровно столько, сколько нужно
    assert any("ужала" in w for w in plan.warnings)
    check_invariants(plan)


def test_over_limit_error_lists_shot_durations():
    spec = parse_spec(_long_spec(4, 95))
    with pytest.raises(SpecError) as ei:
        compile_plan(spec)
    msg = str(ei.value)
    assert ei.value.path == "shots" and "можно до 20 с" in msg
    assert "сцена 1 —" in msg and "сцена 4 —" in msg and "Сократи" in msg
    plan = compile_plan(parse_spec(_long_spec(4, 95), max_seconds=60))  # с большим пределом — влезает
    assert plan.duration <= 60


def test_explicit_shot_seconds():
    plan = plan_of([{"who": "stella", "do": "wave"}], seconds=6)
    assert plan.duration == pytest.approx(6.0)
    plan = plan_of([{"who": "stella", "say": "Очень длинная реплика, которую нельзя обрезать на полуслове"}],
                   seconds=1.5)
    assert plan.duration >= plan.lines[0].t1 and any("seconds" in w for w in plan.warnings)


def test_title_card_shot_without_beats():
    plan = compile_plan(parse_spec({"shots": [{"title": {"text": "КОНЕЦ"}}, {"beats": [{"who": "stella",
                                                                                         "do": "bow"}]}]}))
    assert plan.shots[0].t1 == pytest.approx(T.TITLE_CARD)
    assert plan.titles[0].t0 == 0.0 and plan.titles[0].t1 == pytest.approx(T.TITLE_CARD)


# ---------- детерминизм ----------
@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_examples_compile_deterministically(name):
    p1 = compile_plan(parse_spec(EXAMPLES[name]))
    p2 = compile_plan(parse_spec(copy.deepcopy(EXAMPLES[name])))
    assert pickle.dumps(p1) == pickle.dumps(p2)
    assert dataclasses.asdict(p1) == dataclasses.asdict(p2)
    assert p1.seed == EXAMPLES[name]["seed"]
    check_invariants(p1)


def test_plan_basics():
    spec = parse_spec(dict(EXAMPLES["school"]))
    plan = compile_plan(spec, fps=1000, quality="ultra")
    assert (plan.w, plan.h, plan.format) == (720, 1280, "tall")
    assert plan.fps == 60 and plan.quality == "normal"
    assert compile_plan(spec, fps=12, quality="fast").quality == "fast"
    assert plan.caption == spec.caption and plan.cast == spec.cast
    assert plan.n_frames == round(plan.duration * plan.fps)


# ---------- расстановка и перемещения ----------
def test_auto_placement_spread_and_facing():
    plan = plan_of([{"who": "all", "do": "wave"}], cast={"a": "girl", "b": "boy"})
    xa, xb = placement(plan, "a").x, placement(plan, "b").x
    assert [xa, xb] == pytest.approx(T.spread_x(2, "square"))
    assert placement(plan, "a").facing == 1 and placement(plan, "b").facing == -1
    plan = plan_of([{"who": "stella", "do": "wave"}])
    assert placement(plan, "stella").x == pytest.approx(0.5) and placement(plan, "stella").facing == 0
    plan = plan_of([{"who": "all", "do": "wave"}], cast={"a": "girl", "b": "boy", "c": "cat"},
                   place={"b": {"x": 0.21, "facing": "left", "lane": "back"}})
    xs = {a: placement(plan, a).x for a in "abc"}
    assert xs["b"] == pytest.approx(0.21) and placement(plan, "b").facing == -1 and placement(plan, "b").lane == "back"
    assert sorted([xs["a"], xs["c"]]) == pytest.approx(T.spread_x(3, "square")[1:])


def test_walks_chain_positions_between_beats_and_shots():
    raw = {"cast": {"a": "girl"}, "shots": [
        {"place": {"a": {"x": 0.2}}, "beats": [{"who": "a", "do": "walk", "to": 0.7},
                                               {"who": "a", "do": "run", "to": 0.4}]},
        {"beats": [{"who": "a", "do": "walk", "to": "right"}, {"who": "a", "do": "fly", "to": "center"}]},
    ]}
    plan = compile_plan(parse_spec(raw))
    walk1, run, walk2, fly = clips(plan, "a")
    assert (walk1.params["x0"], walk1.params["x1"]) == pytest.approx((0.2, 0.7))
    assert walk1.t1 - walk1.t0 == pytest.approx(0.5 / T.SPEED["walk"])
    assert (run.params["x0"], run.params["x1"]) == pytest.approx((0.7, 0.4))
    assert run.t1 - run.t0 == pytest.approx(T.MIN_MOVE)  # 0.3 / 0.6 = 0.5 < 0.6
    assert placement(plan, "a", 1).x == pytest.approx(0.4)  # следующая сцена — там, где закончил
    assert walk2.params["x0"] == pytest.approx(0.4) and walk2.params["x1"] == pytest.approx(T._bounds("square")[1])
    assert fly.params["x0"] == pytest.approx(walk2.params["x1"]) and fly.params["x1"] == pytest.approx(0.5)
    assert fly.params["height"] == pytest.approx(0.3)
    check_invariants(plan)


def test_walk_in_and_walk_out():
    raw = {"cast": {"a": "girl", "b": "boy"}, "shots": [
        {"place": {"a": {"x": 0.3}, "b": {"x": 0.7}},
         "beats": [{"who": "a", "do": "walk_in", "from": "left"}, {"who": "b", "do": "walk_in"},
                   {"who": "a", "do": "walk_out", "from": "right"}]},
        {"beats": [{"who": "all", "do": "wave"}]},
    ]}
    plan = compile_plan(parse_spec(raw))
    a_in, a_out = clips(plan, "a", "walk_in")[0], clips(plan, "a", "walk_out")[0]
    b_in = clips(plan, "b", "walk_in")[0]
    assert a_in.params["x0"] == T.OFFSCREEN_L and a_in.params["x1"] == pytest.approx(0.3)
    assert b_in.params["x0"] == T.OFFSCREEN_R and b_in.params["x1"] == pytest.approx(0.7)  # ближний край
    assert placement(plan, "a").x == T.OFFSCREEN_L and placement(plan, "b").x == T.OFFSCREEN_R  # сначала за кадром
    assert a_out.params["x0"] == pytest.approx(0.3) and a_out.params["x1"] == T.OFFSCREEN_R
    assert 0.0 < placement(plan, "a", 1).x < 1.0  # ушедший за кадр в новой сцене снова на месте
    assert placement(plan, "b", 1).x == pytest.approx(0.7)
    check_invariants(plan)


def test_walk_to_actor_stands_near_side():
    plan = plan_of([{"who": "a", "do": "walk", "to": "b"}], cast={"a": "girl", "b": "boy"},
                   place={"a": {"x": 0.2}, "b": {"x": 0.7}})
    walk = clips(plan, "a", "walk")[0]
    assert walk.params["x1"] == pytest.approx(0.7 - T.NEAR)
    plan = plan_of([{"who": "a", "do": "run", "to": "b"}], cast={"a": "girl", "b": "boy"},
                   place={"a": {"x": 0.9}, "b": {"x": 0.3}})
    assert clips(plan, "a", "run")[0].params["x1"] == pytest.approx(0.3 + T.NEAR)


def test_action_with_to_walks_first():
    plan = plan_of([{"who": "a", "do": "jump", "to": 0.8}, {"who": "a", "do": "wave", "to": 0.2}],
                   cast={"a": "girl"}, place={"a": {"x": 0.3}})
    walk1, jump, walk2 = clips(plan, "a", "walk")[0], clips(plan, "a", "jump")[0], clips(plan, "a", "walk")[1]
    wave = clips(plan, "a", "wave")[0]
    assert jump.t0 == pytest.approx(walk1.t1)  # сначала дойти, потом прыгать
    assert wave.t0 == pytest.approx(walk2.t0)  # помахать можно на ходу
    assert walk2.params["x0"] == pytest.approx(0.8)


def test_side_on_run_enters_from_offscreen():
    plan = plan_of([{"who": "a", "do": "run", "from": "right"}], cast={"a": "dog"}, place={"a": {"x": 0.4}})
    run = clips(plan, "a", "run")[0]
    assert run.params["x0"] == T.OFFSCREEN_R and run.params["x1"] == pytest.approx(0.4)
    assert placement(plan, "a").x == T.OFFSCREEN_R


def test_hug_and_high_five_bring_actors_together():
    cast = {"a": "girl", "b": "boy", "c": "cat"}
    plan = plan_of([{"who": ["a", "b"], "do": "hug"}], cast=cast, place={"a": {"x": 0.2}, "b": {"x": 0.8}})
    wa, wb = clips(plan, "a", "walk")[0], clips(plan, "b", "walk")[0]
    ha, hb = clips(plan, "a", "hug")[0], clips(plan, "b", "hug")[0]
    assert wa.t0 == pytest.approx(wb.t0) and ha.t0 == pytest.approx(max(wa.t1, wb.t1)) == pytest.approx(hb.t0)
    assert wb.params["x1"] - wa.params["x1"] == pytest.approx(T.GAP["hug"])
    assert (wa.params["x1"] + wb.params["x1"]) / 2 == pytest.approx(0.5)
    assert ha.params == {"target": "b", "tx": pytest.approx(wb.params["x1"])}
    assert hb.params == {"target": "a", "tx": pytest.approx(wa.params["x1"])}
    assert {e.emotion for e in plan.emotions} == {"love"}  # обнимашки — с любовью, если эмоция не задана
    # одиночный who + target; уже рядом — без ходьбы
    plan = plan_of([{"who": "a", "do": "high_five", "target": "c"}], cast=cast,
                   place={"a": {"x": 0.4}, "c": {"x": 0.61}, "b": {"x": 0.9}})
    assert not clips(plan, action="walk")
    assert clips(plan, "a", "high_five")[0].params["target"] == "c"
    assert clips(plan, "c", "high_five")[0].params["target"] == "a"
    assert not clips(plan, "b", "high_five")
    # без цели — с ближайшим
    plan = plan_of([{"who": "a", "do": "hug"}], cast=cast, place={"a": {"x": 0.2}, "b": {"x": 0.5}, "c": {"x": 0.9}})
    assert clips(plan, "a", "hug")[0].params["target"] == "b"
    # не с кем — праздник с предупреждением
    plan = plan_of([{"who": "stella", "do": "hug"}])
    assert clips(plan, "stella", "celebrate") and any("не с кем" in w for w in plan.warnings)


def test_point_target_and_look():
    plan = plan_of([{"who": "a", "do": "point", "target": "b"}, {"who": "a", "do": "point", "to": "left"},
                    {"who": "b", "do": "wave", "look": "camera"}], cast={"a": "girl", "b": "boy"},
                   place={"a": {"x": 0.3}, "b": {"x": 0.7}})
    p1, p2 = clips(plan, "a", "point")
    assert p1.params == {"target": "b", "tx": pytest.approx(0.7)} and p1.layer == 1
    assert p2.params == {"target": None, "tx": 0.0}
    assert any(lk.actor == "a" and lk.target == "b" for lk in plan.looks)
    assert any(lk.actor == "b" and lk.target == "camera" for lk in plan.looks)


def test_action_params():
    plan = plan_of([{"who": "a", "do": "jump", "amount": 1.0}, {"who": "a", "do": "spin", "amount": 1.0},
                    {"who": "a", "do": "grow"}, {"who": "a", "do": "shrink", "amount": 1.0},
                    {"who": "a", "do": "turn"}, {"who": "a", "do": "dance", "style": "disco"},
                    {"who": "a", "do": "wave"}, {"who": "a", "do": "hop"}], cast={"a": "girl"},
                   place={"a": {"x": 0.3}}, max_seconds=60)
    got = {c.action: c.params for c in plan.clips}
    assert got["jump"] == {"height": pytest.approx(0.8)} and got["spin"] == {"turns": 3}
    assert got["grow"] == {"factor": 1.5} and got["shrink"] == {"factor": pytest.approx(0.5)}
    assert got["turn"] == {"to": "left"} and got["dance"] == {"style": "disco"} and got["wave"] == {"hand": "r"}
    assert got["hop"] == {"height": 0.25}


# ---------- появление, участие, «все» ----------
def test_appear_poof_and_visibility():
    raw = {"cast": {"a": "girl", "g": "ghost", "x": "cat"}, "shots": [
        {"place": {"a": {}, "g": {}}, "beats": [{"who": "g", "do": "appear"}, {"who": "g", "do": "poof"}]},
        {"beats": [{"who": "x", "do": "wave"}]},
    ]}
    plan = compile_plan(parse_spec(raw))
    appear, poof = clips(plan, "g", "appear")[0], clips(plan, "g", "poof")[0]
    assert appear.t0 < poof.t0 and appear.t1 - appear.t0 == pytest.approx(0.6)
    assert placement(plan, "g", 0).visible and placement(plan, "a", 0).visible
    assert not placement(plan, "x", 0).visible
    assert placement(plan, "x", 1).visible and not placement(plan, "g", 1).visible
    check_invariants(plan)


def test_who_all_moves_everyone_in_shot():
    plan = compile_plan(parse_spec(EXAMPLES["birthday"]))
    dancers = {c.actor for c in clips(plan, action="dance")}
    assert dancers == {"stella", "masha", "barsik"}


def test_unknown_actor_auto_created_and_planned():
    plan = plan_of([{"who": "stella", "do": "wave"}, {"who": "собака", "do": "run", "to": "stella"}])
    assert plan.cast["собака"].base == "dog"
    assert placement(plan, "собака").visible and clips(plan, "собака", "run")
    assert any("собака" in w for w in plan.warnings)


# ---------- эмоции ----------
def test_emotions_hold_until_next_and_implied_return():
    plan = plan_of([{"who": "a", "emotion": "happy"}, {"who": "a", "do": "laugh"}, {"who": "a", "do": "wave"},
                    {"who": "a", "emotion": "sad"}], cast={"a": "girl"})
    spans = [(e.emotion, round(e.t0, 3), round(e.t1, 3)) for e in plan.emotions]
    laugh = clips(plan, "a", "laugh")[0]
    assert [s[0] for s in spans] == ["happy", "laugh", "happy", "sad"]
    assert spans[1][1:] == (round(laugh.t0, 3), round(laugh.t1, 3))
    assert spans[-1][2] == pytest.approx(plan.duration)
    check_invariants(plan)


def test_emotions_carry_over_shots():
    plan = compile_plan(parse_spec({"cast": {"a": "girl"}, "shots": [
        {"beats": [{"who": "a", "emotion": "angry"}]}, {"beats": [{"who": "a", "do": "wave"}]}]}))
    assert len(plan.emotions) == 1 and plan.emotions[0].t1 == pytest.approx(plan.duration)


# ---------- эффекты, погода, титры, предметы ----------
def test_weather_and_shot_effects():
    raw = {"shots": [
        {"background": {"preset": "winter", "weather": "snow"}, "effects": [{"kind": "hearts"},
                                                                          {"kind": "flash", "at": 1},
                                                                          {"kind": "confetti", "at": 0.5,
                                                                           "seconds": 1.5, "x": 0.3}],
         "beats": [{"who": "stella", "do": "wave"}], "transition": "crossfade"},
        {"background": {"preset": "city", "weather": "rain"}, "beats": [{"who": "stella", "do": "nod"}]},
    ]}
    plan = compile_plan(parse_spec(raw))
    s0, s1 = plan.shots
    by = {(e.shot, e.kind): e for e in plan.effects}
    snow, rain = by[(0, "snow")], by[(1, "rain")]
    assert (snow.t0, snow.t1) == pytest.approx((s0.t0, s0.t1)) and (rain.t0, rain.t1) == pytest.approx((s1.t0, s1.t1))
    assert (by[(0, "hearts")].t0, by[(0, "hearts")].t1) == pytest.approx((0.0, s0.t1))  # до конца сцены
    assert by[(0, "flash")].t1 - by[(0, "flash")].t0 == pytest.approx(0.4)
    conf = by[(0, "confetti")]
    assert (conf.t0, conf.t1, conf.x) == pytest.approx((0.5, 2.0, 0.3))
    assert len({e.seed for e in plan.effects}) == len(plan.effects)  # у каждого эффекта своё зерно
    assert s0.transition == "crossfade" and s0.transition_s == T.TRANSITION_SECONDS["crossfade"]
    assert s1.transition == "cut"
    assert clips(plan, "stella", "nod")[0].t0 == pytest.approx(s1.t0 + T.TRANSITION_SECONDS["crossfade"] / 2 + 0.1)


def test_effect_beat_follows_actor():
    plan = plan_of([{"who": "a", "do": "jump", "effect": "sparkles"}, {"effect": "poof", "x": 0.9, "seconds": 1}],
                   cast={"a": "cat"}, place={"a": {"x": 0.3}})
    sparkles, poof = plan.effects
    assert sparkles.x == pytest.approx(0.3) and sparkles.t0 == pytest.approx(clips(plan, "a", "jump")[0].t0)
    assert poof.x == pytest.approx(0.9) and poof.t1 - poof.t0 == pytest.approx(1.0)


def test_titles_and_props():
    plan = compile_plan(parse_spec(EXAMPLES["birthday"]))
    title = plan.titles[0]
    assert (title.text, title.style, title.anim, title.position) == ("С ДНЁМ РОЖДЕНИЯ!", "gold3d", "drop", "top")
    assert (title.t0, title.t1) == pytest.approx((0.0, 4.0))
    kinds = [(p.shot, p.prop.kind, p.is3d) for p in plan.props]
    assert kinds == [(0, "cake", True), (0, "balloon", True), (0, "balloon", True), (1, "planet", True),
                     (1, "text3d", True)]
    plan = compile_plan(parse_spec(EXAMPLES["argue"]))
    assert [(p.prop.kind, p.is3d) for p in plan.props] == [("ball", False)]


# ---------- камера ----------
def test_camera_moves_and_beats():
    plan = plan_of([{"who": "a", "do": "wave"}, {"camera": "shake", "amount": 0.7}, {"camera": "zoom_in"},
                    {"camera": "focus", "focus": "a"}, {"camera": "reset"}, {"who": "a", "do": "nod"}],
                   cast={"a": "girl"}, camera={"move": "pan_left", "amount": 0.3})
    cams = plan.cameras
    shot = plan.shots[0]
    assert cams[0].kind == "pan_left" and (cams[0].t0, cams[0].t1) == pytest.approx((shot.t0, shot.t1))
    assert cams[0].amount == pytest.approx(0.3)
    by = {c.kind: c for c in cams[1:]}
    assert by["shake"].t1 - by["shake"].t0 == pytest.approx(0.35) and by["shake"].amount == pytest.approx(0.7)
    assert by["zoom_in"].t1 - by["zoom_in"].t0 == pytest.approx(0.6)
    assert by["focus"].focus == "a"
    assert by["reset"].t1 == pytest.approx(shot.t1)


def test_auto_camera_on_stomp_high_jump_and_shout():
    plan = plan_of([{"who": "a", "do": "stomp"}], cast={"a": "bear"})
    stomp = clips(plan, "a", "stomp")[0]
    shakes = [c for c in plan.cameras if c.kind == "shake"]
    assert len(shakes) == 1 and stomp.t0 < shakes[0].t0 < stomp.t1
    plan = plan_of([{"who": "a", "do": "jump", "amount": 0.9}, {"who": "a", "do": "jump"}], cast={"a": "cat"})
    j1 = clips(plan, "a", "jump")[0]
    shakes = [c for c in plan.cameras if c.kind == "shake"]
    assert len(shakes) == 1 and shakes[0].t0 == pytest.approx(j1.t0 + 0.85 * (j1.t1 - j1.t0))  # только высокий
    plan = plan_of([{"who": "a", "shout": "СТОЙ!"}], cast={"a": "boy"})
    assert [(c.kind, c.focus) for c in plan.cameras] == [("punch", "a")]
    # явная камера в соседнем бите важнее автоматической
    plan = plan_of([{"who": "a", "shout": "СТОЙ!"}, {"camera": "shake", "with": "prev"}], cast={"a": "boy"})
    assert [c.kind for c in plan.cameras] == ["shake"]


# ---------- раскладка общая с layout.py ----------
def test_layout_numbers_match_contract():
    assert (T.OFFSCREEN_L, T.OFFSCREEN_R) == (-0.18, 1.18)
    for fmt, (lo, hi) in {"square": (0.2, 0.8), "wide": (0.15, 0.85), "tall": (0.25, 0.75)}.items():
        xs = T.spread_x(5, fmt)
        assert min(xs) == pytest.approx(lo) and max(xs) == pytest.approx(hi)
        assert T.spread_x(1, fmt) == [pytest.approx(0.5)]
    try:
        from bot.anim import layout
    except ImportError:
        return
    assert (layout.OFFSCREEN_L, layout.OFFSCREEN_R) == (T.OFFSCREEN_L, T.OFFSCREEN_R)
    for fmt in C.FORMATS:
        for n in range(1, 5):
            assert layout.spread_x(n, fmt) == pytest.approx(T.spread_x(n, fmt))


# ---------- все примеры: гарантии ----------
@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_examples_invariants(name):
    plan = compile_plan(parse_spec(EXAMPLES[name]))
    check_invariants(plan)
    for a in plan.cast:  # цепочка позиций: x0 следующего перемещения = x1 предыдущего в той же сцене
        for shot in plan.shots:
            start = placement(plan, a, shot.index)
            x = start.x
            for c in sorted(clips(plan, a), key=lambda c: c.t0):
                if not (shot.t0 <= c.t0 < shot.t1) or c.action not in T.MOVES:
                    continue
                if c.action != "walk_in" and not T._offscreen(c.params["x0"]):
                    assert c.params["x0"] == pytest.approx(x), (a, c)
                x = c.params["x1"]
