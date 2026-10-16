"""Прототип: план (уже проверенный) -> состояние кадра в момент t. Чистая функция: без состояния между кадрами."""
import math
import random
import zlib

EMOTIONS = {
    "neutral": {"mouth": "smile", "blush": 0.35},
    "happy": {"mouth": "grin", "mouth_open": 0.25, "blush": 0.7},
    "laugh": {"mouth": "grin", "mouth_open": 0.7, "eyes": "closed_happy", "blush": 0.9},
    "love": {"eyes": "heart", "mouth": "grin", "mouth_open": 0.2, "blush": 1.0},
    "wow": {"mouth": "o", "mouth_open": 0.5, "brow_up": 1, "pupil": 0.7, "eyes": "star"},
    "sad": {"mouth": "frown", "brow": 0.8, "eye_open": 0.75, "fx": ("tears",)},
    "angry": {"mouth": "shout", "mouth_open": 0.3, "brow": -1, "lid_tilt": 0.45, "eye_open": 0.85,
              "fx": ("anger",)},
    "scared": {"mouth": "wavy", "brow": 0.9, "brow_up": 1, "pupil": 0.55, "fx": ("sweat",)},
}


def seeded(seed, *keys):
    return random.Random(zlib.crc32(("|".join(map(str, keys))).encode()) ^ seed)


def smooth(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def blinks(seed, who, dur):
    r = seeded(seed, who, "blink")
    t, out = r.uniform(0.3, 2.0), []
    while t < dur:
        out.append(t)
        t += r.uniform(1.8, 4.5)
    return out


def char_state(plan, scene, who, t):
    """Поза и лицо персонажа в момент t сцены."""
    seed = plan["seed"]
    start = scene["place"][who]
    x, y = start["x"], start["y"]
    facing = start.get("face", 1)
    pose = {"arm_l": 0.15, "arm_r": 0.15, "leg_l": 0.0, "leg_r": 0.0, "lean": 0.0, "squash": 1.0, "air": 0.0,
            "head_tilt": 0.0, "yaw": 0.0, "tail": t * 2.0, "ear": 0.0}
    # дыхание и покачивание — всегда
    ph = seeded(seed, who, "phase").uniform(0, 6.28)
    pose["squash"] = 1 + 0.025 * math.sin(t * 2.6 + ph)
    pose["arm_l"] += 0.06 * math.sin(t * 2.6 + ph)
    pose["arm_r"] += 0.06 * math.sin(t * 2.6 + ph + 0.5)
    emotion, look_at, saying = "neutral", None, None
    for ev in scene["events"]:
        if ev.get("who") != who or ev["t"] > t:
            continue
        u_t = t - ev["t"]
        dur = ev.get("dur", 1.0)
        act = ev.get("act")
        if "emotion" in ev:
            emotion = ev["emotion"]
        if "say" in ev and u_t < dur:
            saying = ev
        if act == "walk":
            u = smooth(u_t / dur)
            tx, ty = ev["to"]
            nx, ny = x + (tx - x) * u, y + (ty - y) * u
            if tx != x:
                facing = 1 if tx > x else -1
            if u_t < dur:
                stride = math.sin(u_t * 9.0)
                pose.update(leg_l=0.55 * stride, leg_r=-0.55 * stride, arm_l=0.15 - 0.5 * stride,
                            arm_r=0.15 + 0.5 * stride, lean=0.07, air=10 * abs(math.cos(u_t * 9.0)))
            x, y = nx, ny
        elif act == "jump" and u_t < dur:
            u = u_t / dur
            if u < 0.2:  # подготовка
                pose["squash"] = 1 - 0.22 * math.sin(u / 0.2 * math.pi / 2)
            elif u < 0.85:
                v = (u - 0.2) / 0.65
                pose["air"] = 180 * 4 * v * (1 - v)
                pose["squash"] = 1.12 - 0.12 * abs(2 * v - 1)
                pose["arm_l"] = pose["arm_r"] = 2.2
                pose["ear"] = -0.6 if v < 0.5 else 0.6
            else:  # приземление
                v = (u - 0.85) / 0.15
                pose["squash"] = 1 - 0.2 * math.sin(v * math.pi)
        elif act == "wave" and u_t < dur:
            pose["arm_r"] = 2.5 + 0.35 * math.sin(u_t * 14)
            pose["head_tilt"] = 0.08 * math.sin(u_t * 3)
        elif act == "dance" and u_t < dur:
            b = u_t * 2 * math.pi * 2.0
            pose["squash"] = 1 + 0.08 * math.sin(2 * b)
            pose["lean"] = 0.15 * math.sin(b)
            pose["arm_l"] = 1.6 + 0.9 * math.sin(b)
            pose["arm_r"] = 1.6 - 0.9 * math.sin(b)
            pose["air"] = 22 * abs(math.sin(b))
            pose["leg_l"], pose["leg_r"] = 0.3 * math.sin(b), -0.3 * math.sin(b)
            pose["yaw"] = 0.4 * math.sin(b / 2)
        elif act == "spin" and u_t < dur:  # псевдо-3D разворот: yaw через профиль, потом смена стороны
            u = u_t / dur
            a = u * 2 * math.pi
            pose["yaw"] = math.sin(a) * 1.0
            if math.cos(a) < 0:
                facing = -facing if u < 0.5 else facing
        if "look" in ev:
            look_at = ev["look"]
    # кто-то говорит — остальные смотрят на него
    for ev in scene["events"]:
        if "say" in ev and ev["who"] != who and ev["t"] <= t < ev["t"] + ev.get("dur", 2):
            look_at = ev["who"]
    face = dict(EMOTIONS.get(emotion, EMOTIONS["neutral"]))
    if look_at and look_at in scene["place"]:
        ox = scene_pos(plan, scene, look_at, t)[0]
        d = max(-1.0, min(1.0, (ox - x) * 4))
        pose["yaw"] += 0.35 * d * facing
        face["look"] = (d * facing, -0.1)
    for b in blinks(seed, who, scene["dur"]):
        if 0 <= t - b < 0.14:
            face["eye_open"] = 0.05
    if saying:
        k = t - saying["t"]
        face["mouth"] = "grin"
        face["mouth_open"] = 0.15 + 0.55 * abs(math.sin(k * 11)) * (0.6 + 0.4 * math.sin(k * 3.1))
    pose["face"] = face
    pose["x"], pose["y"], pose["facing"] = x, y, facing
    return pose, saying


def scene_pos(plan, scene, who, t):
    x, y = scene["place"][who]["x"], scene["place"][who]["y"]
    for ev in scene["events"]:
        if ev.get("who") == who and ev.get("act") == "walk" and ev["t"] <= t:
            u = smooth((t - ev["t"]) / ev.get("dur", 1))
            x, y = x + (ev["to"][0] - x) * u, y + (ev["to"][1] - y) * u
    return x, y


def camera(scene, t):
    keys = scene.get("camera") or [{"t": 0, "zoom": 1.0, "x": 0.5, "y": 0.5}]
    prev = keys[0]
    for k in keys[1:]:
        if t <= k["t"]:
            u = smooth((t - prev["t"]) / max(1e-6, k["t"] - prev["t"]))
            return {f: prev.get(f, d) + (k.get(f, d) - prev.get(f, d)) * u for f, d in (("zoom", 1), ("x", .5), ("y", .5))}
        prev = k
    return {f: prev.get(f, d) for f, d in (("zoom", 1), ("x", .5), ("y", .5))}


def locate(plan, i):
    """Номер кадра -> (сцена, время внутри сцены)."""
    t = i / plan["fps"]
    for sc in plan["scenes"]:
        if t < sc["dur"] or sc is plan["scenes"][-1]:
            return sc, min(t, sc["dur"])
        t -= sc["dur"]
