"""Привычки: раз в минуту пишем смены состояний устройств, ищем повторяющиеся по времени."""
import datetime as dt
import statistics
import time

from . import bus, config, db, home

_last: dict[str, str] = {}
WATCH = ("light.", "switch.", "lock.", "media_player.", "cover.")
_ACTION = {"off": "off", "on": "on", "locked": "lock", "unlocked": "unlock", "closed": "off", "open": "on"}


async def record():
    now = dt.datetime.now(config.TZ)
    for s in await home.states():
        e, st = s["entity_id"], s["state"]
        if not e.startswith(WATCH) or st in ("unavailable", "unknown"):
            continue
        if e in _last and _last[e] != st:
            db.x("INSERT INTO homelog(ts,day,minute,entity,state) VALUES(?,?,?,?,?)",
                 (time.time(), now.strftime("%Y-%m-%d"), now.hour * 60 + now.minute, e, st))
        _last[e] = st


def _habits() -> list[dict]:
    since = time.time() - config.HABIT_WINDOW_DAYS * 86400
    groups: dict[tuple, list] = {}
    for r in db.q("SELECT day,minute,entity,state FROM homelog WHERE ts>?", (since,)):
        groups.setdefault((r["entity"], r["state"]), []).append((r["day"], r["minute"]))
    out = []
    for (ent, st), items in groups.items():
        if st not in _ACTION:
            continue
        med = statistics.median(m for _, m in items)
        near = {d for d, m in items if abs(m - med) <= 20}   # «примерно в одно время»
        if len(near) >= config.HABIT_MIN_DAYS:
            out.append({"entity": ent, "state": st, "minute": int(med), "days": len(near)})
    return out


def check_suggestions():
    now = dt.datetime.now(config.TZ)
    cur = now.hour * 60 + now.minute
    for h in _habits():
        until = h["minute"] - cur
        key = f"habit|{h['entity']}|{h['state']}|{now:%Y-%m-%d}"
        if 0 < until <= config.HABIT_LEAD_MIN and not db.q("SELECT 1 FROM reminded WHERE key=?", (key,)):
            db.x("INSERT INTO reminded(key,ts) VALUES(?,?)", (key, time.time()))
            name = next((k for k, v in config.HOME_ALIASES.items() if v == h["entity"]), h["entity"])
            verb = {"off": "выключаете", "on": "включаете", "lock": "запираете", "unlock": "отпираете"}[_ACTION[h["state"]]]
            bus.publish("suggest", text=f"Вы обычно {verb} «{name}» около {h['minute']//60:02d}:{h['minute']%60:02d}. Сделать сейчас?",
                        entity=h["entity"], action=_ACTION[h["state"]])
