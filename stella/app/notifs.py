"""Входящие уведомления с телефона: оценка важности и решение, что показать."""
import datetime as dt
import time

from . import bus, config, db

URGENT_WORDS = ("срочно", "упал", "ошибка", "авария", "помоги", "urgent", "asap", "error", "down", "alert")


def importance(sender: str, text: str) -> str:
    s, t = sender.lower(), text.lower()
    if any(v in s for v in config.VIP_CONTACTS) or any(w in t for w in URGENT_WORDS):
        return "urgent"
    return "normal"


def is_night() -> bool:
    h = dt.datetime.now(config.TZ).hour
    a, b = config.NIGHT_FROM, config.NIGHT_TO
    return (a <= h < b) if a <= b else (h >= a or h < b)


def handle(app: str, sender: str, text: str, key: str = "") -> dict:
    imp = importance(sender, text)
    nid = db.x("INSERT INTO notifs(app,sender,text,key,importance,ts) VALUES(?,?,?,?,?,?)",
               (app, sender, text, key, imp, time.time()))
    if is_night() and imp != "urgent":
        return {"id": nid, "importance": imp, "shown": False}
    line = f"{sender}: {text}"
    bus.publish("hud", text=line, id=nid, app=app)
    if imp == "urgent":
        bus.publish("speak", text=f"{config.USER_NAME}, {sender} пишет: {text}")
    return {"id": nid, "importance": imp, "shown": True}


def find_recent(sender: str = "", notif_id: int = 0):
    if notif_id:
        rows = db.q("SELECT * FROM notifs WHERE id=?", (notif_id,))
    elif sender:
        # «маме», «маму», «Мама» -> по основе слова; затем по похожести имён
        s = sender.lower().strip()
        stem = s[:max(3, len(s) - 2)]
        rows = db.q("SELECT * FROM notifs WHERE lower(sender) LIKE ? ORDER BY ts DESC LIMIT 1", (f"%{stem}%",))
        if not rows:
            import difflib
            names = {r["sender"] for r in db.q("SELECT DISTINCT sender FROM notifs ORDER BY ts DESC LIMIT 60")}
            best = difflib.get_close_matches(sender, list(names), n=1, cutoff=0.5)
            if best:
                rows = db.q("SELECT * FROM notifs WHERE sender=? ORDER BY ts DESC LIMIT 1", (best[0],))
    else:
        rows = db.q("SELECT * FROM notifs ORDER BY ts DESC LIMIT 1")
    return rows[0] if rows else None
