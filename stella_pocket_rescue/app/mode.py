import json
import os
import time

STANDBY = "standby"
EMERGENCY = "emergency"
SOURCES = ("manual", "drill", "sensor")


def _path():
    return os.getenv("STELLA_MODE_FILE", "/var/lib/stella/mode.json")


def read():
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        if data.get("mode") in (STANDBY, EMERGENCY):
            return data
    except (OSError, ValueError):
        pass
    return {"mode": STANDBY, "source": None, "since": None, "note": None}


def write(mode, source=None, note=None):
    data = {"mode": mode, "source": source, "since": time.time(), "note": note}
    path = _path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o664)
    except OSError:
        pass
    return data
