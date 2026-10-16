"""Персонажи мультиков: внешность, кукла, лицо, значки, актёрская игра (actions) и «слой жизни» (life).

Рисуем маленькими (160 px), проверяем, что каждая база × эмоция × момент рисуется и не пустая, что каждое
действие каталога проходит через actor_frame, что поза — чистая функция, видимость, ходьба, речь и взгляды.
"""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from bot.anim import catalog as C
from bot.anim.actions import ACTIONS, actor_frame, ik, root_x
from bot.anim.chars import Look, build_look, draw_character, draw_face, head_anchor
from bot.anim.chars.body import rig
from bot.anim.chars.face import EMOTIONS, blend_emotion
from bot.anim.chars.look import BUILDS
from bot.anim.chars.marks import MARK_KINDS, draw_dust, draw_mark, draw_puff, draw_spark
from bot.anim.draw import new_surface
from bot.anim.life import blink, lip, saccade, spring_lag, word_starts
from bot.anim.model import CastSpec, OutfitPart, Pose
from bot.anim.palette import hx
from bot.anim.spec import parse_spec
from bot.anim.timeline import compile_plan

S = 160  # размер тестовой поверхности


def _alpha(surface) -> np.ndarray:
    surface.flush()
    w, h, stride = surface.get_width(), surface.get_height(), surface.get_stride()
    buf = np.frombuffer(surface.get_data(), dtype=np.uint8).reshape(h, stride)[:, : w * 4].reshape(h, w, 4)
    return buf[:, :, 3].copy()  # копия: поверхность может быть уже собрана сборщиком мусора


def _draw(look: Look, pose: Pose, height: float = 120.0, facing: int = 1, size: int = S):
    surface, ctx = new_surface(size, size)
    draw_character(ctx, look, pose, size / 2, size - 8, height, facing)
    return surface


def _plan(raw: dict):
    return compile_plan(parse_spec(raw))


def _clips(plan, actor: str, action: str):
    return [c for c in plan.clips if c.actor == actor and c.action == action]


# ---------- внешность ----------
@pytest.mark.parametrize("base", C.BASES)
def test_build_look_every_base(base):
    look = build_look(CastSpec(id=base, base=base))
    assert look.base == base
    for c in (look.skin, look.color, look.accent, look.eyes):
        assert len(c) == 3 and all(0.0 <= v <= 1.0 for v in c)
    assert look.build is BUILDS[base]
    assert len(look.accessories) <= C.MAX_ACCESSORIES


def test_build_look_uses_cast_and_varies_by_id():
    cast = CastSpec(id="masha", base="girl", skin=(0.9, 0.8, 0.7), hair="afro", hair_color=hx("#ff0000"),
                    eyes=hx("#00ff00"), top=OutfitPart("hoodie", hx("#0000ff"), "number:7"),
                    bottom=OutfitPart("skirt", hx("#ffff00")), shoes=hx("#123456"), accessories=("crown", "cape"))
    look = build_look(cast)
    assert (look.hair, look.top, look.top_print, look.bottom) == ("afro", "hoodie", "number:7", "skirt")
    assert look.hair_color == hx("#ff0000") and look.eyes == hx("#00ff00") and look.skin == (0.9, 0.8, 0.7)
    assert look.accessories == ("crown", "cape")
    # Стелла и безымянные — всегда канонический дизайн; разные id одной базы — не близнецы
    assert build_look(CastSpec(id="stella", base="stella")) == build_look(CastSpec(id="s2", base="stella"))
    girls = {build_look(CastSpec(id=f"girl_{i}", base="girl")).hair for i in range(12)}
    assert len(girls) >= 3
    cat = build_look(CastSpec(id="кот", base="cat", color=hx("#3366ff")))
    assert cat.color == hx("#3366ff") and cat.belly != cat.color


def test_build_look_seed_does_not_change_appearance():
    cast = CastSpec(id="barsik", base="cat")
    assert build_look(cast, 1) == build_look(cast, 999)


# ---------- кукла: все базы × эмоции × моменты ----------
@pytest.mark.parametrize("base", C.BASES)
def test_every_base_every_emotion_draws(base):
    look = build_look(CastSpec(id=base, base=base, accessories=("party_hat",) if base == "bear" else ()))
    for i, emo in enumerate(C.EMOTIONS):
        for t in (0.0, 0.73, 2.41):
            pose = Pose(emotion=emo, t=t, yaw=(-0.6, 0.0, 0.5)[i % 3], mouth_open=0.5 if i % 4 == 0 else 0.0,
                        blink=0.5 if i % 5 == 0 else 0.0, marks=(("hearts", 0.4),) if i % 6 == 0 else ())
            a = _alpha(_draw(look, pose, facing=1 if i % 2 else -1))
            assert a.max() >= 230, (base, emo, t)  # привидение — полупрозрачное (0.92)
            assert len(np.unique(a)) > 2, (base, emo, t)


def test_customization_everything_draws():
    for i, hair in enumerate(C.HAIR):
        look = build_look(CastSpec(id=f"h{i}", base="girl", hair=hair, accessories=()))
        assert _alpha(_draw(look, Pose(hair_swing=0.5, t=1.0))).max() == 255
    prints = (None, "star", "heart", "stripes", "number:7", "text:МАША")
    for i, top in enumerate(C.TOPS):
        for bottom in C.BOTTOMS:
            cast = CastSpec(id=f"t{i}", base="boy", top=OutfitPart(top, hx("#ff7eb6"), prints[i % len(prints)]),
                            bottom=OutfitPart(bottom, hx("#3a6df0")))
            for facing in (1, -1):
                assert _alpha(_draw(build_look(cast), Pose(yaw=0.4), facing=facing)).max() == 255
    for base in ("boy", "cat", "robot", "ghost", "monster", "alien", "bunny"):
        for acc in C.ACCESSORIES:
            look = build_look(CastSpec(id=f"{base}{acc}", base=base, accessories=(acc,)))
            assert _alpha(_draw(look, Pose(t=0.5, hair_swing=0.3))).max() >= 230, (base, acc)
    # звери в одежде
    look = build_look(CastSpec(id="c", base="cat", top=OutfitPart("hoodie", hx("#5b4bd6")),
                               bottom=OutfitPart("pants", hx("#222222"))))
    assert look.top == "hoodie" and _alpha(_draw(look, Pose())).max() == 255


def test_all_hand_shapes_and_extreme_poses_draw():
    look = build_look(CastSpec(id="stella", base="stella"))
    for hand in ("open", "fist", "point", "peace", "hold"):
        pose = Pose(arm_l=(3.1, 2.2), arm_r=(-0.5, -2.6), leg_l=(0.9, 1.4), leg_r=(-0.9, 0.0), hand_l=hand,
                    hand_r=hand, bob=-200, lean=0.4, squash=0.7, head_tilt=-0.4, yaw=1.0)
        assert _alpha(_draw(look, pose, size=260)).max() == 255
    # прозрачность, масштаб и вырожденные значения не ломают рисование
    for pose in (Pose(alpha=0.0), Pose(scale=0.0), Pose(alpha=0.5, scale=1.7), Pose(squash=5.0, yaw=9.0)):
        _draw(look, pose)
    surface, ctx = new_surface(40, 40)
    draw_character(ctx, look, Pose(), float("nan"), 10, 100, 1)
    draw_character(ctx, look, Pose(), 10, 10, 0.0, 1)
    assert _alpha(surface).max() == 0


def test_facing_mirrors():
    look = build_look(CastSpec(id="boy", base="boy"))
    right = _alpha(_draw(look, Pose(yaw=0.6), facing=1))
    left = _alpha(_draw(look, Pose(yaw=0.6), facing=-1))
    diff = np.abs(right.astype(int) - left[:, ::-1].astype(int))
    assert np.mean(diff > 60) < 0.01  # зеркально (с точностью до сглаживания краёв)
    assert np.mean(diff > 60) < np.mean(np.abs(right.astype(int) - left.astype(int)) > 60)


def test_back_limbs_are_darker_and_drawn():
    look = build_look(CastSpec(id="boy", base="boy"))
    R = rig(look, Pose(yaw=0.5))
    assert R.back == -1 and R.narrow < 1.0
    R0 = rig(look, Pose(yaw=0.0))
    assert R0.back == 0


def test_head_anchor_is_above_everything_drawn():
    for base in C.BASES:
        for acc in ((), ("wizard_hat",), ("party_hat",), ("crown",)):
            look = build_look(CastSpec(id=base, base=base, accessories=acc))
            for pose in (Pose(), Pose(bob=-60, yaw=0.5, head_tilt=0.3), Pose(scale=1.4, squash=1.2)):
                surface, ctx = new_surface(S, 260)
                draw_character(ctx, look, pose, S / 2, 250, 140, 1)
                a = _alpha(surface)
                rows = np.nonzero(a.max(axis=1) > 20)[0]
                ax, ay = head_anchor(look, pose, S / 2, 250, 140, 1)
                assert math.isfinite(ax) and math.isfinite(ay)
                assert ay <= rows.min() + 1, (base, acc, ay, rows.min())
                assert abs(ax - S / 2) < 60


def test_draw_face_standalone_in_circle():
    for base in ("stella", "cat", "robot3d", "penguin3d", "snowman3d", "alien", "dog"):
        look = build_look(CastSpec(id=base, base=base, accessories=("glasses", "mustache")))
        for emo in C.EMOTIONS:
            surface, ctx = new_surface(120, 120)
            draw_face(ctx, look, Pose(emotion=emo, t=0.4, mouth_open=0.3), 60, 60, 40, 0.3)
            a = _alpha(surface)
            assert a.max() == 255, (base, emo)
            ys, xs = np.nonzero(a > 30)
            # всё лицо — около круга радиуса r (слёзы и усы чуть ниже)
            assert xs.min() >= 60 - 40 * 1.45 and xs.max() <= 60 + 40 * 1.45, (base, emo)
            assert ys.min() >= 60 - 40 * 1.2, (base, emo)
    surface, ctx = new_surface(20, 20)
    draw_face(ctx, look, Pose(), 10, 10, 0.0, 0.0)  # нулевой радиус — ничего
    assert _alpha(surface).max() == 0


def test_blend_emotion():
    for emo in C.EMOTIONS:
        assert emo in EMOTIONS
        assert blend_emotion(emo, 1.0) == EMOTIONS[emo]
        assert blend_emotion(emo, 0.0).mouth == EMOTIONS["neutral"].mouth
    half = blend_emotion("angry", 0.5)
    assert 0.0 < half.lid < EMOTIONS["angry"].lid
    assert blend_emotion("no_such", 1.0) == EMOTIONS["neutral"]


def test_all_marks_draw():
    for kind in MARK_KINDS:
        assert kind in C.MARKS
    assert set(C.MARKS) <= set(MARK_KINDS)
    for kind in C.MARKS:
        surface, ctx = new_surface(S, S)
        for p in (0.05, 0.3, 0.7):
            draw_mark(ctx, kind, p, 80, 90, 0.5, -1, 62, 1.3)
        assert _alpha(surface).max() > 0, kind
    surface, ctx = new_surface(S, S)
    draw_puff(ctx, 0.3, 80, 80, 0.5)
    draw_spark(ctx, 0.3, 80, 80, 0.5)
    draw_dust(ctx, 0.3, 80, 150, 0.5, 1)
    assert _alpha(surface).max() > 0
    draw_mark(ctx, "unknown", 0.5, 80, 80, 0.5, 1, 62, 0.0)  # неизвестный — молча ничего


# ---------- жизнь ----------
def test_blink_schedule_and_double_blinks():
    seed = 12345
    vals = [blink(i / 240, seed) for i in range(240 * 30)]
    closed = [v > 0.99 for v in vals]
    starts = [i for i in range(1, len(closed)) if closed[i] and not closed[i - 1]]
    assert 30 / 5.5 <= len(starts) <= 30 / 2.5 * 1.25 + 2
    assert all(0.0 <= v <= 1.0 for v in vals)
    # двойные моргания встречаются (у кого-нибудь из актёров)
    found_double = False
    for s in range(40):
        st = [i for i in range(1, 2400) if blink(i / 240, s) > 0.99 and blink((i - 1) / 240, s) <= 0.99]
        if any(0.15 < (b - a) / 240 < 0.3 for a, b in zip(st, st[1:], strict=False)):
            found_double = True
            break
    assert found_double
    # обязательное моргание в начале поворота
    assert blink(10.06, seed, forced=(10.0,)) == 1.0


def test_lip_sync_vowels_and_pauses():
    o, shape = lip("ма", 0.0, (1 + 0.5) / 13)
    assert shape == "a" and o > 0.8
    assert lip("мо", 0.0, 1.5 / 13)[1] == "o"
    assert lip("ми", 0.0, 1.5 / 13)[1] == "e"
    assert lip("а б", 0.0, 1.5 / 13) == (0.0, "m")  # пробел — пауза
    assert lip("мама", 0.0, 0.5 / 13)[0] < 0.2  # согласная почти закрыта
    assert lip("мама", 0.0, -1) == (0.0, "m") and lip("мама", 0.0, 99) == (0.0, "m")
    assert word_starts("Привет, как дела?") == [0, 8, 12]


def test_saccades_are_quick_and_small():
    seed = 7
    xs = [saccade(i / 100, seed) for i in range(2000)]
    assert all(abs(x) <= 0.25 and abs(y) <= 0.12 for x, y in xs)
    jumps = [abs(xs[i][0] - xs[i - 1][0]) for i in range(1, len(xs))]
    assert max(jumps) > 0.01  # прыгает
    assert len({round(x, 3) for x, _ in xs}) > 5


def test_spring_lag_follows_and_settles():
    def still(t: float) -> float:
        return 1.0

    assert abs(spring_lag(still, 5.0)) < 1e-9

    def move(t: float) -> float:
        return min(t, 1.0)  # движется до t=1, потом стоит

    assert spring_lag(move, 0.9) > 0.0  # отстаёт во время движения
    assert abs(spring_lag(move, 3.0)) < 0.02  # успокоилась


def test_ik_reaches_target():
    b = BUILDS["stella"]
    for side in (-1, 1):
        target = (side * 20, b.hip_y - 70)
        a, bend = ik(b, side, target)
        look = build_look(CastSpec(id="stella", base="stella"))
        pose = Pose(arm_l=(a, bend), arm_r=(a, bend), yaw=0.0)
        hand = rig(look, pose).hands[side]
        assert math.hypot(hand[0] - target[0], hand[1] - target[1]) < 1.0


# ---------- актёрская игра ----------
def _single(base: str, beat: dict, place: dict | None = None, extra_cast: dict | None = None):
    cast = {"a": {"base": base}}
    cast.update(extra_cast or {})
    shot = {"beats": [beat], "place": place or {"a": {"x": 0.5}}}
    return _plan({"cast": cast, "shots": [shot], "seed": 4})


def _beat_for(action: str, style: str | None = None) -> tuple[dict, dict | None, dict | None]:
    beat: dict = {"who": "a", "do": action}
    place = None
    extra = None
    if action in ("point", "hug", "high_five"):
        extra = {"b": {"base": "boy"}}
        place = {"a": {"x": 0.3}, "b": {"x": 0.7}}
        beat["target"] = "b"
    if action in ("walk", "run", "fly"):
        beat["to"] = 0.8
    if action == "walk_in":
        beat["from"] = "left"
    if action == "dance":
        beat["style"] = style
    if action == "turn":
        beat["to"] = "left"
    return beat, place, extra


ACTION_CASES = [(a, None) for a in C.ACTIONS if a != "dance"] + [("dance", s) for s in C.DANCE_STYLES]


@pytest.mark.parametrize("action,style", ACTION_CASES)
@pytest.mark.parametrize("base", ["stella", "cat"])
def test_every_action_through_actor_frame(base, action, style):
    assert action in ACTIONS
    beat, place, extra = _beat_for(action, style)
    plan = _single(base, beat, place, extra)
    clips = _clips(plan, "a", action)
    assert clips, action
    look = build_look(plan.cast["a"])
    t0, t1 = clips[0].t0, clips[-1].t1
    n = 12
    for k in range(n + 1):
        t = t0 + (t1 - t0) * k / n
        fr = actor_frame(plan, "a", t)
        p = fr.pose
        nums = [fr.x, fr.lift, p.bob, p.lean, p.squash, p.head_tilt, p.yaw, *p.arm_l, *p.arm_r, *p.leg_l, *p.leg_r,
                *p.look, p.blink, p.emotion_w, p.mouth_open, p.hair_swing, p.tail_swing, p.ear_swing, p.wing_flap,
                p.scale, p.alpha]
        assert all(math.isfinite(v) for v in nums), (action, t)
        assert 0.65 <= p.squash <= 1.35 and -1 <= p.yaw <= 1 and 0 <= p.blink <= 1 and 0 <= p.alpha <= 1
        assert fr.facing in (1, -1) and p.emotion in C.EMOTIONS and p.mouth_shape in ("a", "o", "e", "m")
        assert all(0.0 <= mp <= 1.0 for _, mp in p.marks)
        if k % 3 == 0 and fr.visible:
            _draw(look, p, facing=fr.facing)


def test_actor_frame_is_pure_and_deterministic():
    raw = {"cast": {"stella": "stella", "kot": "cat"}, "seed": 9,
           "shots": [{"beats": [{"who": "stella", "do": "walk", "to": 0.7, "say": "Привет, котик!"},
                                {"who": "kot", "do": "dance", "style": "robot", "emotion": "excited"},
                                {"who": "all", "do": "jump"}]}]}
    plan = _plan(raw)
    times = [i / 24 for i in range(int(plan.duration * 24))]
    first = [actor_frame(plan, a, t) for t in times for a in plan.cast]
    again = [actor_frame(plan, a, t) for t in reversed(times) for a in reversed(list(plan.cast))]
    assert first == list(reversed(again))
    twin = copy.deepcopy(plan)  # другой объект — тот же результат (кеш индекса не мешает)
    assert [actor_frame(twin, a, t) for t in times for a in twin.cast] == first
    plan2 = _plan(raw)
    assert actor_frame(plan2, "kot", 1.234) == actor_frame(plan, "kot", 1.234)


def test_visibility_rules():
    # до appear — невидим, после poof — невидим
    plan = _plan({"cast": {"a": "boy"}, "shots": [{"beats": [{"who": "a", "do": "wave"},
                                                             {"who": "a", "do": "appear"},
                                                             {"who": "a", "do": "wave"},
                                                             {"who": "a", "do": "poof"}]}]})
    ap = _clips(plan, "a", "appear")[0]
    pf = _clips(plan, "a", "poof")[0]
    assert not actor_frame(plan, "a", ap.t0 - 0.05).visible
    mid = actor_frame(plan, "a", ap.t0 + (ap.t1 - ap.t0) * 0.9)
    assert mid.visible and mid.pose.scale > 0.5
    assert actor_frame(plan, "a", (ap.t1 + pf.t0) / 2).visible
    puff = actor_frame(plan, "a", pf.t0 + (pf.t1 - pf.t0) * 0.7)
    assert puff.visible and any(k == "_puff" for k, _ in puff.pose.marks)  # видно облачко
    assert not actor_frame(plan, "a", pf.t1 + 0.05).visible
    # не участвует в сцене
    plan = _plan({"cast": {"a": "boy", "b": "girl"},
                  "shots": [{"place": {"a": {}}, "beats": [{"who": "a", "do": "wave"}]},
                            {"place": {"b": {}}, "beats": [{"who": "b", "do": "wave"}]}]})
    s1 = plan.shots[1]
    assert not actor_frame(plan, "a", (s1.t0 + s1.t1) / 2).visible
    assert actor_frame(plan, "b", (s1.t0 + s1.t1) / 2).visible
    assert not actor_frame(plan, "nobody", 0.5).visible
    # ушёл за кадр
    plan = _plan({"cast": {"a": "cat"}, "shots": [{"beats": [{"who": "a", "do": "walk_out", "to": "right"},
                                                             {"who": "a", "do": "idle", "seconds": 1}]}]})
    wo = _clips(plan, "a", "walk_out")[0]
    assert actor_frame(plan, "a", wo.t0 + 0.01).visible
    gone = actor_frame(plan, "a", wo.t1 + 0.3)
    assert not gone.visible and gone.x > 1.0
    # пришёл из-за кадра: сначала невидим
    plan = _plan({"cast": {"a": "cat"}, "shots": [{"beats": [{"who": "a", "do": "walk_in", "from": "left"}]}]})
    wi = _clips(plan, "a", "walk_in")[0]
    assert not actor_frame(plan, "a", wi.t0).visible
    assert actor_frame(plan, "a", wi.t1).visible


def test_walk_interpolates_with_easing_and_ends_at_x1():
    plan = _single("stella", {"who": "a", "do": "walk", "to": 0.8}, {"a": {"x": 0.2}})
    c = _clips(plan, "a", "walk")[0]
    x0, x1 = c.params["x0"], c.params["x1"]
    assert (x0, x1) == (0.2, 0.8)
    d = c.t1 - c.t0
    xs = [actor_frame(plan, "a", c.t0 + d * k / 40).x for k in range(41)]
    base = [actor_frame(plan, "a", c.t0 + d * k / 40).pose for k in range(41)]
    assert abs(xs[0] - x0) < 0.02 and abs(xs[-1] - x1) < 0.02
    assert root_x([c], 0.2, c.t1)[0] == x1 and root_x([c], 0.2, c.t1 + 5)[0] == x1
    assert root_x([c], 0.2, c.t0)[0] == x0
    pure = [root_x([c], 0.2, c.t0 + d * k / 40)[0] for k in range(41)]
    assert all(b >= a - 1e-9 for a, b in zip(pure, pure[1:], strict=False))  # монотонно
    linear_start = x0 + (x1 - x0) * 0.05
    assert pure[2] < linear_start  # разгон — не линейно
    assert actor_frame(plan, "a", c.t0 + d / 2).facing == 1
    # ноги действительно шагают
    legs = {round(p.leg_l[0], 2) for p in base}
    assert len(legs) > 5
    after = actor_frame(plan, "a", c.t1 + 1.0)
    assert abs(after.x - x1) < 0.02


def test_speaking_and_mouth_moves_during_line():
    plan = _plan({"cast": {"a": "stella", "b": "boy"},
                  "shots": [{"beats": [{"who": "a", "say": "Привет! Как у тебя дела сегодня?"}]}]})
    line = next(ln for ln in plan.lines if ln.actor == "a")
    frames = [actor_frame(plan, "a", line.t0 + (line.t1 - line.t0) * k / 30) for k in range(30)]
    assert all(f.speaking for f in frames)
    opens = [f.pose.mouth_open for f in frames]
    assert max(opens) > 0.5 and min(opens) < 0.15 and len({round(o, 2) for o in opens}) > 6
    assert {f.pose.mouth_shape for f in frames} >= {"a", "e"}
    assert not actor_frame(plan, "a", line.t1 + 0.2).speaking
    assert actor_frame(plan, "a", line.t1 + 0.2).pose.mouth_open == 0.0
    assert not actor_frame(plan, "b", (line.t0 + line.t1) / 2).speaking
    # мысли — без движения рта
    plan = _plan({"cast": {"a": "cat"}, "shots": [{"beats": [{"who": "a", "think": "Хочу рыбки"}]}]})
    line = plan.lines[0]
    fr = actor_frame(plan, "a", (line.t0 + line.t1) / 2)
    assert not fr.speaking and fr.pose.mouth_open == 0.0


def test_listeners_look_at_speaker():
    plan = _plan({"cast": {"l": "girl", "s": "stella", "r": "cat"},
                  "shots": [{"place": {"l": {"x": 0.2}, "s": {"x": 0.5}, "r": {"x": 0.8}},
                             "beats": [{"who": "s", "say": "Слушайте все внимательно, это важно!"}]}]})
    line = plan.lines[0]
    t = (line.t0 + line.t1) / 2
    for actor, world_dir in (("l", 1), ("r", -1)):
        votes = 0
        for k in range(10):
            fr = actor_frame(plan, actor, t + k * 0.05)
            local = fr.pose.look[0] * fr.facing  # куда смотрят глаза в мире
            votes += (local * world_dir) > 0.2
        assert votes >= 9, actor
    # без реплик никто никуда специально не смотрит
    quiet = actor_frame(plan, "l", line.t1 + 0.4)
    assert abs(quiet.pose.look[0]) < 0.45


def test_emotions_marks_and_lift():
    plan = _plan({"cast": {"a": "boy"},
                  "shots": [{"beats": [{"who": "a", "emotion": "love", "mark": "idea"},
                                       {"who": "a", "do": "jump", "amount": 1.0},
                                       {"who": "a", "emotion": "sleepy"}]}]})
    em = [e for e in plan.emotions if e.actor == "a"]
    love = next(e for e in em if e.emotion == "love")
    fr = actor_frame(plan, "a", love.t0 + 0.4)
    assert fr.pose.emotion == "love" and fr.pose.emotion_w > 0.9
    kinds = {k for k, _ in fr.pose.marks}
    assert "idea" in kinds and "hearts" in kinds
    ramp = actor_frame(plan, "a", love.t0 + 0.02).pose.emotion_w
    assert 0.3 <= ramp < 0.9 or love.t0 < 0.3
    jump = _clips(plan, "a", "jump")[0]
    top = max((actor_frame(plan, "a", jump.t0 + (jump.t1 - jump.t0) * k / 20) for k in range(21)),
              key=lambda f: f.lift)
    assert top.lift > 0.5 and top.pose.bob < -150
    squashes = [actor_frame(plan, "a", jump.t0 + (jump.t1 - jump.t0) * k / 40).pose.squash for k in range(41)]
    assert min(squashes) < 0.85 and max(squashes) > 1.1  # замах и растяжение
    sleepy = next(e for e in em if e.emotion == "sleepy")
    assert any(k == "zzz" for k, _ in actor_frame(plan, "a", sleepy.t0 + 1.0).pose.marks)


def test_turn_flips_facing_and_blinks():
    plan = _plan({"cast": {"a": "girl"},
                  "shots": [{"place": {"a": {"x": 0.5, "facing": "right"}},
                             "beats": [{"who": "a", "do": "idle", "seconds": 1},
                                       {"who": "a", "do": "turn", "to": "left"},
                                       {"who": "a", "do": "idle", "seconds": 1}]}]})
    c = _clips(plan, "a", "turn")[0]
    assert actor_frame(plan, "a", c.t0 - 0.2).facing == 1
    assert actor_frame(plan, "a", c.t1 + 0.2).facing == -1
    assert max(actor_frame(plan, "a", c.t0 + k / 100).pose.blink for k in range(17)) == 1.0


def test_secondary_motion_lags_behind_walk():
    plan = _single("cat", {"who": "a", "do": "run", "to": 0.9}, {"a": {"x": 0.1}})
    c = _clips(plan, "a", "run")[0]
    mid = actor_frame(plan, "a", (c.t0 + c.t1) / 2)
    assert mid.pose.hair_swing < -0.2  # волосы/хвост отстают от бега
    stop = [actor_frame(plan, "a", c.t1 + k / 24).pose.hair_swing for k in range(1, 20)]
    assert max(stop) > 0.05  # при остановке — перелёт вперёд
    dog = _single("dog", {"who": "a", "emotion": "happy", "seconds": 2})
    tails = {round(actor_frame(dog, "a", 0.5 + k / 24).pose.tail_swing, 2) for k in range(12)}
    assert max(tails) > 0.6 and min(tails) < -0.6  # пёс виляет хвостом, когда рад


def test_actor_frame_for_3d_bases_and_shot_override():
    plan = _plan({"cast": {"p": {"base": "penguin3d"}, "s": "snowman3d"},
                  "shots": [{"beats": [{"who": "p", "do": "dance"}]}, {"beats": [{"who": "s", "do": "wave"}]}]})
    fr = actor_frame(plan, "p", 1.0)
    assert fr.visible and math.isfinite(fr.pose.bob)
    s1 = plan.shots[1]
    # старая сцена во время перехода — по явному номеру сцены
    assert actor_frame(plan, "p", s1.t0 + 0.1, shot=0).visible
    assert not actor_frame(plan, "p", s1.t0 + 0.1).visible
