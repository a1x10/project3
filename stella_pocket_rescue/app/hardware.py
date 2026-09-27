import glob
import json
import logging
import math
import os
import signal
import socket
import stat
import struct
import sys
import threading
import time

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import pwd
except ImportError:
    pwd = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import mode

LOG = logging.getLogger("stella.hw")


def _env_text(name):
    return os.getenv(name, "").strip()


def _env_float(name, default):
    try:
        value = float(_env_text(name) or default)
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def _env_addr(name, default):
    try:
        value = int(_env_text(name) or hex(default), 16)
    except ValueError:
        return default
    return value if 0x03 <= value <= 0x77 else default


def _env_root(name, default):
    return os.getenv(name, default).strip().rstrip("/") or default


TICK = 0.02
SYS = _env_root("STELLA_SYSFS", "/sys")
PROC = _env_root("STELLA_PROCFS", "/proc")
FAN_GPIO = _env_text("STELLA_FAN_GPIO")
LED_GPIO = _env_text("STELLA_LED_GPIO")
FAN_TEMP_ON = _env_float("STELLA_FAN_TEMP_ON", 60.0)
FAN_TEMP_HYST = max(0.0, _env_float("STELLA_FAN_TEMP_HYST", 3.0))
I2C_BUS = _env_text("STELLA_SENSOR_I2C_BUS")
I2C_ADDR = _env_addr("STELLA_SENSOR_ADDR", 0x68)
QUAKE_G = _env_float("STELLA_QUAKE_G", 0.12)
QUAKE_SECONDS = _env_float("STELLA_QUAKE_SECONDS", 0.8)
SENSOR_LOST = 50
SENSOR_RETRY = 10.0

HEARTBEAT = 5.0
LLM_SCAN = 1.0
WINDOW = 1800.0
ESCALATE_AFTER = 2
KEEP = 10
JSON_LIMIT = 65536
SETTINGS = ("auto", "normal", "safe", "off")
PROFILES = ("normal", "safe", "off")
LLM_NAMES = tuple(n.strip() for n in os.getenv("STELLA_LLM_COMM", "llama-server").split(",") if n.strip())
REASONS = {
    "auto": "Авто: щадящий режим — локальный ИИ на одном ядре, частота ограничена",
    "normal": "Задано вручную (STELLA_POWER=normal): обычный режим питания",
    "safe": "Задано вручную (STELLA_POWER=safe): щадящий режим питания",
    "off": "Задано вручную (STELLA_POWER=off): локальный ИИ выключен",
}
WATCH_REASON = ("Авто: была аварийная перезагрузка во время работы локального ИИ — "
                "если повторится в течение 30 минут, локальный ИИ будет выключен")
OFF_REASON = "Питание не выдерживает локальный ИИ: плата перезагружалась %d %s за 30 минут. Вернуть: stella power reset"
OFF_REASON_PLAIN = "Питание не выдерживает локальный ИИ — он выключен сторожем. Вернуть: stella power reset"
LABELS = {"llm": "поиск llama-server", "guard": "метка guard.json", "power": "файл power.json",
          "hw": "файл hw.json", "tick": "цикл железа", "mode": "запись режима ЧС"}


def log(*a):
    LOG.info(" ".join(str(x) for x in a))


def _write(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except OSError:
        return False


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, ValueError):
        return None


def _sys(*parts):
    return os.path.join(SYS, *parts)


def _proc(*parts):
    return os.path.join(PROC, *[str(p) for p in parts])


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _close_fd(fd):
    try:
        os.close(fd)
    except OSError:
        pass


def _safely(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def _count(value):
    value = _number(value)
    return int(min(value, 10 ** 9)) if value is not None and value >= 0 else 0


def _stamps(value):
    if not isinstance(value, list):
        return []
    return [t for t in (_number(v) for v in value) if t is not None][-KEEP:]


def _times(n):
    return "раза" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "раз"


class Throttle:
    def __init__(self, every=60.0):
        self.every = every
        self.seen = {}

    def __call__(self, key, message):
        now = time.monotonic()
        last = self.seen.get(key)
        if last and last[0] == message and now - last[1] < self.every:
            return False
        self.seen[key] = (message, now)
        LOG.warning(message)
        return True

    def ok(self, key):
        if self.seen.pop(key, None):
            LOG.info("%s — снова в порядке", LABELS.get(key, key))


def _gpio_out(number):
    if not number.isdigit():
        return None
    base = _sys("class", "gpio", "gpio" + number)
    if not os.path.exists(base):
        _write(_sys("class", "gpio", "export"), number)
        time.sleep(0.2)
    return base + "/value" if _write(base + "/direction", "out") else None


def _celsius(raw):
    try:
        value = int(raw) / 1000.0
    except (TypeError, ValueError, OverflowError):
        return None
    return round(value, 1) if -40 <= value <= 150 else None


def _zone_order(path):
    tail = os.path.basename(path)[len("thermal_zone"):]
    return (0, int(tail), "") if tail.isdigit() else (1, 0, tail)


def thermal_zones():
    zones = {}
    for folder in sorted(glob.glob(_sys("class", "thermal", "thermal_zone*")), key=_zone_order):
        value = _celsius(_read(os.path.join(folder, "temp")))
        if value is None:
            continue
        name = _read(os.path.join(folder, "type")) or os.path.basename(folder)
        key, n = name, 2
        while key in zones:
            key, n = "%s-%d" % (name, n), n + 1
        zones[key] = value
    return zones


def temps():
    zones = thermal_zones()
    values = list(zones.values())
    soc = [v for k, v in zones.items() if "soc" in k.lower() or "cpu" in k.lower()]
    return {"soc": soc[0] if soc else (values[0] if values else None),
            "max": max(values) if values else None, "zones": zones}


class Leds:
    def __init__(self):
        self.leds = sorted(p for p in glob.glob(_sys("class", "leds", "*")) if os.path.exists(p + "/brightness"))
        self.saved = {}
        for p in self.leds:
            trig = _read(p + "/trigger") or ""
            cur = [t.strip("[]") for t in trig.split() if t.startswith("[")]
            self.saved[p] = cur[0] if cur else "none"
        self.has_timer = any("timer" in (_read(p + "/trigger") or "") for p in self.leds)
        self.manual = False
        self.phase = False
        log("светодиоды:", ", ".join(self.names()) or "не найдены")

    def names(self):
        return [os.path.basename(p) for p in self.leds]

    def standby(self):
        self.manual = False
        for p in self.leds:
            trig = _read(p + "/trigger") or ""
            _write(p + "/trigger", "heartbeat" if "heartbeat" in trig else self.saved.get(p, "none"))

    def emergency(self):
        if self.has_timer:
            self.manual = False
            for p in self.leds:
                _write(p + "/trigger", "timer")
                _write(p + "/delay_on", 120)
                _write(p + "/delay_off", 120)
        else:
            self.manual = True
            for p in self.leds:
                _write(p + "/trigger", "none")

    def tick(self, now):
        if not self.manual:
            return
        on = int(now * 4) % 2 == 0
        if on != self.phase:
            self.phase = on
            for p in self.leds:
                _write(p + "/brightness", _read(p + "/max_brightness") or 1 if on else 0)


class Fan:
    def __init__(self):
        self.path = None
        self.state = None
        if not FAN_GPIO:
            log("вентилятор: STELLA_FAN_GPIO не задан — если кулер на пинах 5V, он крутится всегда")
            return
        self.path = _gpio_out(FAN_GPIO)
        if self.path:
            log("вентилятор на GPIO", FAN_GPIO)
        else:
            log("вентилятор: не удалось настроить GPIO", FAN_GPIO)

    def set(self, on):
        if self.path and on != self.state:
            self.state = on
            _write(self.path, 1 if on else 0)

    def auto(self):
        vals = list(thermal_zones().values())
        hot = max(vals) if vals else None
        if hot is not None and hot >= FAN_TEMP_ON:
            self.set(True)
        elif hot is None or hot < FAN_TEMP_ON - FAN_TEMP_HYST or self.state is None:
            self.set(False)

    def snapshot(self):
        return {"gpio": FAN_GPIO or None, "on": bool(self.state) if self.path else None}


class SosLamp:
    def __init__(self):
        self.path = None
        self.state = None
        self.emergency = False
        if not LED_GPIO:
            log("лампочка SOS: STELLA_LED_GPIO не задан")
            return
        self.path = _gpio_out(LED_GPIO)
        if self.path:
            log("лампочка SOS на GPIO", LED_GPIO)
        else:
            log("лампочка SOS: не удалось настроить GPIO", LED_GPIO)

    def tick(self, now):
        if not self.path:
            return
        if self.emergency:
            on = int(now * 6) % 2 == 0
        else:
            on = now % 3 < 0.15
        if on != self.state:
            self.state = on
            _write(self.path, 1 if on else 0)

    def snapshot(self):
        return {"gpio": LED_GPIO or None, "state": bool(self.state) if self.path else None}


class QuakeSensor:
    I2C_SLAVE = 0x0703

    def __init__(self):
        self.fd = None
        self.base = 1.0
        self.shaking_since = None
        self.peak = 0.0
        self.last_g = None
        self.fails = 0
        self.retry_at = None
        if not I2C_BUS:
            log("датчик: не подключён (STELLA_SENSOR_I2C_BUS не задан) — режим ЧС включается кнопкой в консоли")
            return
        if self.open():
            log("датчик MPU-6050 на /dev/i2c-%s, адрес 0x%02x" % (I2C_BUS, I2C_ADDR))
        self.retry_at = time.monotonic() + SENSOR_RETRY

    def open(self, quiet=False):
        if fcntl is None:
            if not quiet:
                log("датчик: на этой системе нет I2C (модуль fcntl недоступен)")
            return False
        fd = None
        try:
            fd = os.open("/dev/i2c-" + I2C_BUS, os.O_RDWR)
            fcntl.ioctl(fd, self.I2C_SLAVE, I2C_ADDR)
            os.write(fd, bytes([0x6B, 0x00]))
            os.write(fd, bytes([0x1C, 0x00]))
        except OSError as e:
            if fd is not None:
                _close_fd(fd)
            if not quiet:
                log("датчик: ошибка I2C:", e)
            return False
        self.fd = fd
        self.fails = 0
        return True

    def close(self):
        if self.fd is not None:
            _close_fd(self.fd)
        self.fd = None

    def read_g(self):
        os.write(self.fd, bytes([0x3B]))
        ax, ay, az = struct.unpack(">hhh", os.read(self.fd, 6))
        return math.sqrt(ax * ax + ay * ay + az * az) / 16384.0

    def retry(self, now):
        if not I2C_BUS or self.retry_at is None or now < self.retry_at:
            return
        self.retry_at = now + SENSOR_RETRY
        if self.open(quiet=True):
            log("датчик: снова на связи")

    def failed(self, now):
        self.fails += 1
        if self.fails >= SENSOR_LOST:
            log("датчик: перестал отвечать — пробую переподключиться каждые %d с" % SENSOR_RETRY)
            self.close()
            self.retry_at = now + SENSOR_RETRY

    def poll(self, now):
        if self.fd is None:
            self.retry(now)
            return None
        try:
            g = self.read_g()
        except (OSError, struct.error):
            self.failed(now)
            return None
        self.fails = 0
        self.last_g = g
        self.base += (g - self.base) * 0.002
        dev = abs(g - self.base)
        if dev > QUAKE_G:
            self.peak = max(self.peak, dev)
            if self.shaking_since is None:
                self.shaking_since = now
            elif now - self.shaking_since >= QUAKE_SECONDS:
                note = "датчик: тряска %.2f g в течение %.1f с" % (self.peak, now - self.shaking_since)
                self.shaking_since, self.peak = None, 0.0
                return note
        elif self.shaking_since and now - self.shaking_since > QUAKE_SECONDS * 2:
            self.shaking_since, self.peak = None, 0.0
        return None

    def snapshot(self):
        g = self.last_g
        return {"present": self.fd is not None, "bus": I2C_BUS or None, "addr": I2C_ADDR,
                "last_g": round(g, 3) if g is not None and math.isfinite(g) else None}


def _mode_name(fallback=None):
    try:
        value = mode.read()["mode"]
    except Exception:
        value = None
    return value if value in (mode.STANDBY, mode.EMERGENCY) else (fallback or mode.STANDBY)


class Board:
    def __init__(self):
        self.leds, self.fan, self.sensor, self.lamp = Leds(), Fan(), QuakeSensor(), SosLamp()
        self.current = None
        self.last_mode_check = 0
        self.errors = Throttle()

    def mode_name(self):
        return self.current or _mode_name()

    def tick(self, now):
        note = self.sensor.poll(now)
        if note and _mode_name(self.current) != mode.EMERGENCY:
            log("ЗЕМЛЕТРЯСЕНИЕ:", note)
            self.alarm(note)
        if now - self.last_mode_check >= 0.5:
            self.last_mode_check = now
            self.apply(_mode_name(self.current))
            if self.current != mode.EMERGENCY:
                self.fan.auto()
        self.leds.tick(now)
        self.lamp.tick(now)

    def alarm(self, note):
        try:
            mode.write(mode.EMERGENCY, "sensor", note)
        except Exception as e:
            self.errors("mode", "не удалось включить режим ЧС: %s" % e)
        else:
            self.errors.ok("mode")

    def apply(self, m):
        if m == self.current:
            return
        self.current = m
        log("режим:", m)
        self.lamp.emergency = m == mode.EMERGENCY
        if m == mode.EMERGENCY:
            self.leds.emergency()
            self.fan.set(True)
        else:
            self.leds.standby()


def state_dir():
    return _env_text("STELLA_STATE_DIR") or "/var/lib/stella"


def _state_file(env, name):
    return _env_text(env) or os.path.join(state_dir(), name)


def power_file():
    return _state_file("STELLA_POWER_FILE", "power.json")


def hw_file():
    return _state_file("STELLA_HW_STATE", "hw.json")


def guard_file():
    return _state_file("STELLA_GUARD_FILE", "guard.json")


def power_setting(raw=None):
    value = os.getenv("STELLA_POWER", "auto") if raw is None else raw
    value = str(value).strip().lower()
    return value if value in SETTINGS else "auto"


def boot_id():
    value = _read(_proc("sys", "kernel", "random", "boot_id"))
    return value if value and len(value) <= 64 else None


def uptime():
    raw = _read(_proc("uptime")) or ""
    try:
        return round(float(raw.split()[0]), 1)
    except (IndexError, ValueError):
        return None


def read_json(path):
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            raw = f.read(JSON_LIMIT + 1)
        if len(raw) > JSON_LIMIT:
            return None
        data = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def json_safe(value, depth=0):
    if depth > 8:
        return None
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): json_safe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v, depth + 1) for v in value]
    return str(value)


def _open_tmp(folder, name):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    for _ in range(3):
        tmp = os.path.join(folder, ".%s.%s.tmp" % (name, os.urandom(6).hex()))
        try:
            return os.open(tmp, flags, 0o644), tmp
        except FileExistsError:
            continue
    raise FileExistsError("не удалось создать временный файл рядом с " + name)


def _write_all(fd, payload):
    view = memoryview(payload)
    while view:
        view = view[os.write(fd, view):]


def _sync_dir(folder):
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        _close_fd(fd)


def _share_dir(folder):
    if pwd is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    try:
        owner = pwd.getpwnam(_env_text("STELLA_USER") or "stella")
        os.chown(folder, owner.pw_uid, owner.pw_gid)
        os.chmod(folder, 0o775)
    except (KeyError, OSError):
        pass


def _ensure_dir(folder):
    if os.path.isdir(folder):
        return
    os.makedirs(folder, exist_ok=True)
    _share_dir(folder)


def write_json(path, data, sync=False):
    path = os.path.abspath(str(path))
    folder, name = os.path.split(path)
    _ensure_dir(folder)
    payload = (json.dumps(json_safe(data), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    fd, tmp = _open_tmp(folder, name)
    try:
        try:
            _write_all(fd, payload)
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o644)
            if sync:
                os.fsync(fd)
        finally:
            _close_fd(fd)
        os.replace(tmp, path)
    except BaseException:
        _unlink(tmp)
        raise
    if sync:
        _sync_dir(folder)


def clean_leftovers(paths):
    for path in paths:
        folder, name = os.path.split(os.path.abspath(str(path)))
        for tmp in glob.glob(os.path.join(glob.escape(folder), "." + glob.escape(name) + ".*.tmp")):
            _unlink(tmp)


def inspect_marker(marker, current):
    if not isinstance(marker, dict) or not current:
        return None
    previous = marker.get("boot_id")
    if not isinstance(previous, str) or not previous or previous == current:
        return None
    if marker.get("clean") is True:
        return {"unclean": False, "llm": False, "chained": False, "boot_id": previous}
    llm = marker.get("llm_active") is True
    lived = _number(marker.get("uptime"))
    chained = (llm and marker.get("after_crash") is True and lived is not None
               and 0 <= lived <= WINDOW - HEARTBEAT)
    return {"unclean": True, "llm": llm, "chained": chained, "boot_id": previous}


def orphan_verdict(path, now, up):
    try:
        changed = os.path.getmtime(path)
    except OSError:
        return None
    if up is None or changed >= now - up:
        return None
    return {"unclean": True, "llm": False, "chained": False, "boot_id": None}


def _profile(setting, prev, counted, near):
    if setting in PROFILES:
        return setting, REASONS[setting]
    if prev.get("setting") == "auto" and prev.get("profile") == "off":
        reason = prev.get("reason")
        return "off", reason[:300] if isinstance(reason, str) and reason.strip() else OFF_REASON_PLAIN
    if counted and near >= ESCALATE_AFTER:
        return "off", OFF_REASON % (near, _times(near))
    return "safe", WATCH_REASON if near else REASONS["auto"]


def next_power(previous, verdict, setting, current, now):
    prev = previous if isinstance(previous, dict) else {}
    setting = power_setting(setting)
    if current and prev.get("boot_id") == current:
        verdict = None
    stamps = _stamps(prev.get("recent_unclean"))
    unclean = _count(prev.get("unclean_boots"))
    last = _number(prev.get("last_unclean"))
    counted = bool(verdict and verdict.get("unclean") and verdict.get("llm"))
    if verdict and verdict.get("unclean"):
        unclean += 1
        last = now
    if counted:
        stamps = (stamps + [now])[-KEEP:]
    near = len([t for t in stamps if abs(now - t) <= WINDOW])
    if counted and verdict.get("chained"):
        near = max(near, ESCALATE_AFTER)
    profile, reason = _profile(setting, prev, counted, near)
    return {"profile": profile, "setting": setting, "unclean_boots": unclean, "recent_unclean": stamps,
            "last_unclean": last, "reason": reason, "updated": now, "boot_id": current}


class Guard:
    def __init__(self, guard_path, power_path, boot=None, setting="auto"):
        self.guard_path = str(guard_path)
        self.power_path = str(power_path)
        self.boot_id = boot
        self.setting = power_setting(setting)
        self.power = next_power(None, None, self.setting, boot, time.time())
        self.verdict = None
        self.clean = False
        self.llm_active = False
        self.after_crash = False
        self.started = None
        self.beat = None
        self.ready = False
        self.saved = False
        self.lock = threading.RLock()

    def marker(self):
        return {"boot_id": self.boot_id, "clean": self.clean, "started": self.started, "heartbeat": self.beat,
                "llm_active": self.llm_active, "after_crash": self.after_crash, "uptime": uptime(),
                "pid": os.getpid()}

    def start(self, now=None):
        now = time.time() if now is None else now
        self.started = self.beat = now
        marker = read_json(self.guard_path)
        verdict = inspect_marker(marker, self.boot_id)
        if marker is None and os.path.exists(self.guard_path):
            LOG.warning("сторож питания: метка %s повреждена", self.guard_path)
            verdict = orphan_verdict(self.guard_path, now, uptime())
        same = bool(self.boot_id) and isinstance(marker, dict) and marker.get("boot_id") == self.boot_id
        self.after_crash = bool((same and marker.get("after_crash") is True)
                                or (verdict and verdict["unclean"] and verdict["llm"]))
        previous = read_json(self.power_path)
        prev = previous or {}
        if verdict is not None and self.boot_id and prev.get("boot_id") == self.boot_id:
            LOG.info("сторож питания: прошлая загрузка уже учтена")
            verdict = None
        self.verdict = verdict
        self.power = next_power(previous, verdict, self.setting, self.boot_id, now)
        self.report(marker, same, prev)
        self.save_power()
        self.ready = True
        try:
            self.store(sync=True)
        except Exception as e:
            LOG.error("сторож питания: не удалось записать метку %s: %s", self.guard_path, e)
        return self.power

    def report(self, marker, same, prev):
        verdict, power = self.verdict, self.power
        if not self.boot_id:
            LOG.warning("сторож питания: boot_id недоступен — аварийные перезагрузки не отслеживаются")
        elif verdict is None:
            if same:
                LOG.info("сторож питания: служба перезапущена в той же загрузке")
            elif marker is None:
                LOG.info("сторож питания: первый запуск — метки прошлой загрузки нет")
        elif not verdict["unclean"]:
            LOG.info("сторож питания: прошлая загрузка завершилась штатно")
        elif verdict["llm"]:
            LOG.warning("ВНИМАНИЕ: плата перезагрузилась аварийно во время работы локального ИИ — "
                        "похоже на просадку питания (brown-out)")
        else:
            LOG.warning("сторож питания: прошлая загрузка оборвалась без штатного выключения "
                        "(локальный ИИ не работал — вероятно, выдернули питание)")
        was_off = prev.get("setting") == "auto" and prev.get("profile") == "off"
        if power["setting"] == "auto" and power["profile"] == "off" and not was_off:
            LOG.warning("сторож питания: ЛОКАЛЬНЫЙ ИИ ВЫКЛЮЧЕН — %s", power["reason"])
        LOG.info("сторож питания: профиль %s (настройка %s), аварийных перезагрузок %d",
                 power["profile"], power["setting"], power["unclean_boots"])

    def save_power(self):
        try:
            write_json(self.power_path, self.power, sync=True)
        except Exception as e:
            LOG.error("сторож питания: не удалось записать %s: %s", self.power_path, e)
            self.saved = False
        else:
            self.saved = True
        return self.saved

    def store(self, sync=False, timeout=-1):
        if not self.lock.acquire(True, timeout):
            return False
        try:
            while True:
                data = self.marker()
                write_json(self.guard_path, data, sync=sync)
                if data["clean"] == self.clean:
                    return True
                sync = True
        finally:
            self.lock.release()

    def heartbeat(self, now=None, llm_active=None, sync=False):
        if llm_active is not None:
            sync = sync or bool(llm_active) != self.llm_active
            self.llm_active = bool(llm_active)
        if not self.ready:
            return False
        self.beat = time.time() if now is None else now
        return self.store(sync)

    def close(self, now=None):
        self.clean = True
        if not self.ready:
            return False
        self.beat = time.time() if now is None else now
        try:
            return self.store(sync=True, timeout=2.0)
        except Exception as e:
            LOG.error("сторож питания: не удалось отметить штатную остановку: %s", e)
            return False

    def watch_power(self, now=None):
        now = time.time() if now is None else now
        data = read_json(self.power_path)
        if self.saved and data is not None and data.get("profile") in PROFILES:
            data = json_safe(data)
            if data != self.power:
                LOG.info("сторож питания: power.json изменён извне — профиль %s", data["profile"])
                self.power = data
            return self.power
        if self.saved and (data is not None or os.path.exists(self.power_path)):
            LOG.warning("сторож питания: power.json повреждён — записываю заново")
        elif self.saved:
            LOG.warning("сторож питания: power.json удалён — сброс, профиль по настройке %s", self.setting)
            self.power = next_power(None, None, self.setting, self.boot_id, now)
            self.after_crash = False
        self.saved = False
        write_json(self.power_path, self.power, sync=True)
        self.saved = True
        return self.power


class LlmWatch:
    def __init__(self, names=None):
        self.names = tuple(names or LLM_NAMES or ("llama-server",))
        self.pid = None

    def active(self):
        if self.pid and _read(_proc(self.pid, "comm")) in self.names:
            return True
        self.pid = self.find()
        return self.pid is not None

    def find(self):
        try:
            entries = os.listdir(PROC)
        except OSError:
            return None
        for entry in entries:
            if entry.isdigit() and _read(_proc(entry, "comm")) in self.names:
                return entry
        return None


def hw_snapshot(board=None, guard=None, llm_active=False, now=None):
    parts = board if board is not None else object()
    return {
        "ts": time.time() if now is None else now,
        "pid": os.getpid(),
        "boot_id": guard.boot_id if guard is not None else boot_id(),
        "mode": _safely(lambda: parts.mode_name(), None) or _mode_name(),
        "sensor": _safely(lambda: parts.sensor.snapshot(),
                          {"present": False, "bus": I2C_BUS or None, "addr": I2C_ADDR, "last_g": None}),
        "leds": _safely(lambda: parts.leds.names(), []),
        "fan": _safely(lambda: parts.fan.snapshot(), {"gpio": FAN_GPIO or None, "on": None}),
        "lamp": _safely(lambda: parts.lamp.snapshot(), {"gpio": LED_GPIO or None, "state": None}),
        "temps": _safely(temps, {"soc": None, "max": None, "zones": {}}),
        "llm_active": bool(llm_active),
        "power": guard.power if guard is not None else None,
    }


class Publisher:
    def __init__(self, guard, board, hw_path, stopping=None):
        self.guard = guard
        self.board = board
        self.hw_path = str(hw_path)
        self.stopping = stopping or (lambda: False)
        self.llm = LlmWatch()
        self.llm_active = False
        self.next_scan = 0.0
        self.next_beat = 0.0
        self.halt = threading.Event()
        self.thread = None
        self.errors = Throttle()

    def start(self):
        self.thread = threading.Thread(target=self.run, name="stella-guard")
        self.thread.daemon = True
        self.thread.start()

    def alive(self):
        return self.thread is not None and self.thread.is_alive()

    def stop(self, timeout=3.0):
        self.halt.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout)

    def run(self):
        while not self.halt.is_set() and not self.stopping():
            try:
                self.step(time.monotonic(), time.time())
            except Exception as e:
                self.errors("step", "сторож: сбой цикла — %r" % (e,))
            self.halt.wait(0.25)

    def step(self, mono, wall):
        if mono >= self.next_scan:
            self.next_scan = mono + LLM_SCAN
            self.guarded("llm", self.scan, wall)
        if mono >= self.next_beat:
            self.next_beat = mono + HEARTBEAT
            self.guarded("power", self.guard.watch_power, wall)
            self.guarded("guard", self.guard.heartbeat, wall, self.llm_active)
            self.guarded("hw", self.publish, wall)

    def scan(self, wall):
        active = self.llm.active()
        if active == self.llm_active:
            return
        self.llm_active = active
        log("локальный ИИ (llama-server)", "запущен" if active else "остановлен")
        self.guard.heartbeat(wall, active, sync=True)

    def publish(self, wall):
        write_json(self.hw_path, hw_snapshot(self.board, self.guard, self.llm_active, wall))

    def guarded(self, key, fn, *args):
        try:
            fn(*args)
        except Exception as e:
            self.errors(key, "%s: ошибка — %s" % (LABELS.get(key, key), e))
        else:
            self.errors.ok(key)


class Stop:
    def __init__(self):
        self.stopping = False
        self.signal = None


def _signal_name(signum):
    try:
        return signal.Signals(signum).name
    except (ValueError, AttributeError):
        return str(signum)


def stop_handler(guard, state):
    def handle(signum, frame=None):
        first = not state.stopping
        state.stopping = True
        state.signal = signum
        guard.close()
        if first:
            log("получен %s — штатная остановка" % _signal_name(signum))
    return handle


def install_signals(handler):
    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError, RuntimeError, TypeError) as e:
            LOG.warning("не удалось поставить обработчик %s: %s", name, e)


def notify(message):
    address = os.getenv("NOTIFY_SOCKET", "")
    family = getattr(socket, "AF_UNIX", None)
    if not address or family is None:
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        sock = socket.socket(family, socket.SOCK_DGRAM)
    except OSError:
        return False
    try:
        sock.settimeout(1.0)
        sock.sendto(message.encode("utf-8"), address)
        return True
    except OSError:
        return False
    finally:
        sock.close()


def watchdog_interval():
    try:
        usec = int(os.getenv("WATCHDOG_USEC", ""))
    except ValueError:
        return None
    owner = os.getenv("WATCHDOG_PID", "").strip()
    if usec <= 0 or (owner and owner != str(os.getpid())):
        return None
    return max(0.5, usec / 2e6)


def run(board, publisher, state):
    errors = Throttle()
    watch_at = time.monotonic() + HEARTBEAT
    dog = watchdog_interval()
    dog_at = 0.0
    while not state.stopping:
        now = time.monotonic()
        if board is not None:
            try:
                board.tick(now)
            except Exception as e:
                errors("tick", "ошибка в цикле железа: %r" % (e,))
        if now >= watch_at:
            watch_at = now + HEARTBEAT
            if not publisher.alive() and not state.stopping:
                log("сторож: поток публикации остановился — перезапускаю")
                publisher.start()
        if dog and now >= dog_at:
            dog_at = now + dog
            notify("WATCHDOG=1")
        time.sleep(TICK)


def main():
    logging.basicConfig(level=logging.INFO, format="[stella-hw] %(message)s", stream=sys.stdout)
    state = Stop()
    raw = os.getenv("STELLA_POWER", "auto")
    if raw.strip().lower() not in SETTINGS:
        LOG.warning("STELLA_POWER=%r не распознан — использую auto", raw)
    paths = (guard_file(), power_file(), hw_file())
    guard = Guard(paths[0], paths[1], boot_id(), power_setting(raw))
    install_signals(stop_handler(guard, state))
    clean_leftovers(paths)
    power = guard.start()
    notify("READY=1\nSTATUS=Сторож питания: профиль %s (%s)" % (power["profile"], power["setting"]))
    board = None
    if not state.stopping:
        try:
            board = Board()
        except Exception as e:
            LOG.error("железо не инициализировано: %r — работает только сторож питания", e)
    publisher = Publisher(guard, board, paths[2], lambda: state.stopping)
    if not state.stopping:
        publisher.start()
        run(board, publisher, state)
    notify("STOPPING=1")
    publisher.stop()
    guard.close()
    install_signals(signal.SIG_IGN)
    log("остановлен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
