import asyncio
import contextlib
import glob
import hashlib
import ipaddress
import json
import logging
import math
import os
import platform
import secrets
import shutil
import signal
import socket
import struct
import time
from pathlib import Path

from . import ai, config, integrity, mode, stations
from . import db as dbmod
from .triage import RED, assess, fallback_reply

log = logging.getLogger("stella.diagnostics")

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
STATUSES = (OK, WARN, FAIL, SKIP)
HW_STALE_S = 30
TEMP_WARN, TEMP_FAIL = 75.0, 90.0
UNIT_TIMEOUT = 2.0
DNS_NAME = "check.stella.rescue"
DNS_PORT = 53
DNS_TIMEOUT = 1.5
INTERNET_TIMEOUT = 2.0
AI_WAIT = 3.5
MAX_JSON_BYTES = 1 << 20
DEVICE_MARKERS = ("/etc/stella/stella.env", "/opt/stella/app", "/proc/device-tree/model")
CRITICAL_SAMPLE = "Соседа придавило плитой, он без сознания, сильное кровотечение"
MILD_SAMPLE = "Мы в порядке, не ранены, стоим во дворе"

PRIORITY_RU = {"red": "КРАСНЫЙ", "yellow": "ЖЁЛТЫЙ", "green": "ЗЕЛЁНЫЙ", "unknown": "НЕЯСНО"}
ENGINE_RU = {"cloud": "облачный ИИ", "local": "локальный ИИ", "reserve": "резервные ответы"}
POWER_RU = {"normal": "обычный", "safe": "щадящий", "off": "ИИ выключен", "unknown": "нет данных"}
SOURCE_RU = {"manual": "вручную", "drill": "учения", "sensor": "датчик"}
UNIT_RU = {"inactive": "остановлен", "failed": "упал", "activating": "запускается",
           "deactivating": "останавливается", "reloading": "перечитывает настройки",
           "unknown": "не установлен", "timeout": "не ответил за 2 с"}
DNS_RCODES = {1: "ошибка формата", 2: "сбой сервера", 3: "имя не найдено", 4: "не поддерживается",
              5: "отказ"}


def _read_text(path, limit: int = 4096) -> str | None:
    try:
        with open(path, "rb") as f:
            return f.read(limit).decode("utf-8", "replace").replace("\x00", "").strip()
    except (OSError, TypeError, ValueError):
        return None


def read_json(path) -> dict | None:
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_JSON_BYTES + 1)
    except (OSError, TypeError, ValueError):
        return None
    if len(raw) > MAX_JSON_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=lambda _: None)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def json_safe(value, depth: int = 0):
    if depth > 32:
        return None
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): json_safe(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v, depth + 1) for v in value]
    return str(value)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except OverflowError:
        return None
    return value if math.isfinite(value) else None


def _part(data, key: str) -> dict:
    value = data.get(key) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else {}


def _plural(n: int, one: str, few: str, many: str) -> str:
    tail = n % 100
    if 11 <= tail <= 14:
        word = many
    elif n % 10 == 1:
        word = one
    elif 2 <= n % 10 <= 4:
        word = few
    else:
        word = many
    return f"{n} {word}"


def _ago(seconds) -> str:
    seconds = _number(seconds)
    if seconds is None:
        return "давно"
    seconds = abs(seconds)
    if seconds < 90:
        return f"{int(seconds)} с назад"
    if seconds < 5400:
        return f"{int(seconds // 60)} мин назад"
    if seconds < 172800:
        return f"{int(seconds // 3600)} ч назад"
    return f"{int(seconds // 86400)} дн назад"


def _ms(value) -> str:
    value = _number(value)
    if value is None:
        return ""
    return f"{value / 1000:.1f} с" if value >= 1000 else f"{int(value)} мс"


def _bytes(value: float) -> str:
    gib = value / 1024 ** 3
    return f"{gib:.1f} ГБ" if gib >= 1 else f"{int(value / 1024 ** 2)} МБ"


def on_device() -> bool:
    return any(os.path.exists(p) for p in DEVICE_MARKERS)


def node_id() -> str:
    seed = (_read_text("/etc/machine-id") or _read_text("/var/lib/dbus/machine-id")
            or socket.gethostname() or "stella")
    digest = hashlib.sha256(f"stella-pocket:{seed}".encode("utf-8")).hexdigest().upper()
    return f"STL-{digest[:4]}-{digest[4:8]}"


def uptime_s() -> int | None:
    raw = _read_text("/proc/uptime", 64)
    try:
        return int(float(raw.split()[0]))
    except (AttributeError, IndexError, ValueError):
        return None


def _boot_id() -> str | None:
    return _read_text("/proc/sys/kernel/random/boot_id", 64)


def _os_name() -> str:
    for line in (_read_text("/etc/os-release", 8192) or "").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "PRETTY_NAME" and value.strip():
            return value.strip().strip("\"'")
    return platform.platform(terse=True) or "неизвестно"


def identity() -> dict:
    model = _read_text("/proc/device-tree/model", 256)
    fallback = f"{platform.system()} {platform.machine()}".strip()
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = None
    return {"node": node_id(), "model": model or fallback or "неизвестно", "os": _os_name(),
            "kernel": platform.release() or None, "python": platform.python_version(),
            "hostname": hostname, "uptime_s": uptime_s()}


def _coord(value, limit: float) -> float | None:
    if isinstance(value, str):
        try:
            value = float(value.replace(",", "."))
        except ValueError:
            return None
    value = _number(value)
    return value if value is not None and -limit <= value <= limit else None


def _clean_label(label) -> str | None:
    if not isinstance(label, str):
        return None
    text = "".join(ch for ch in label if ch.isprintable()).strip()
    return text[:80] or None


def hub_location() -> dict:
    data = read_json(config.HUB_FILE)
    if data:
        lat, lon = _coord(data.get("lat"), 90), _coord(data.get("lon"), 180)
        if lat is not None and lon is not None:
            return {"lat": lat, "lon": lon, "label": _clean_label(data.get("label")), "source": "file",
                    "updated": _number(data.get("updated"))}
    lat, lon = _coord(config.HUB_LAT, 90), _coord(config.HUB_LON, 180)
    if lat is not None and lon is not None:
        return {"lat": lat, "lon": lon, "label": None, "source": "env", "updated": None}
    return {"lat": None, "lon": None, "label": None, "source": "none", "updated": None}


def save_hub(lat: float, lon: float, label: str | None = None) -> dict:
    lat, lon = _coord(lat, 90), _coord(lon, 180)
    if lat is None or lon is None:
        raise ValueError("Координаты вне допустимого диапазона")
    path = Path(config.HUB_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"lat": lat, "lon": lon, "label": _clean_label(label), "updated": time.time()}
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()
    with contextlib.suppress(OSError):
        os.chmod(path, 0o644)
    return hub_location()


def clear_hub() -> dict:
    with contextlib.suppress(FileNotFoundError):
        Path(config.HUB_FILE).unlink()
    return hub_location()


def ai_snapshot() -> dict:
    try:
        snap = ai.snapshot()
    except Exception as exc:
        log.warning("ai.snapshot() упал: %s", exc)
        snap = None
    if isinstance(snap, dict):
        return snap
    return {"mode": config.AI_MODE, "active": "reserve", "cloud": {}, "local": {},
            "reserve": {"state": "ok"}, "last_reply": None, "updated": time.time(),
            "error": "Состояние ИИ недоступно"}


def mode_state() -> dict:
    try:
        state = mode.read()
    except Exception as exc:
        log.warning("mode.read() упал: %s", exc)
        state = None
    if isinstance(state, dict) and state.get("mode") in (mode.STANDBY, mode.EMERGENCY):
        return state
    return {"mode": mode.STANDBY, "source": None, "since": None, "note": None}


def _kill(proc) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (AttributeError, OSError):
        with contextlib.suppress(OSError):
            proc.kill()


async def unit_state(unit: str) -> str | None:
    exe = shutil.which("systemctl")
    if not exe:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            exe, "is-active", unit, start_new_session=True,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception as exc:
        log.info("systemctl недоступен: %s", exc)
        return None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), UNIT_TIMEOUT)
    except asyncio.TimeoutError:
        _kill(proc)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.communicate(), 1)
        return "timeout"
    except BaseException:
        _kill(proc)
        raise
    words = out.decode("utf-8", "replace").split()
    return words[0] if words else None


def _unit_problem(unit: str, state: str, consequence: str, value) -> tuple:
    label = UNIT_RU.get(state, state)
    if state in ("timeout", "activating", "reloading"):
        return WARN, f"{unit} {label}", value
    return FAIL, f"{unit} {label} — {consequence}", value


async def tcp_probe(host: str, port: int, timeout: float) -> tuple[bool, int | None]:
    started = time.perf_counter()
    writer = None
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        return True, int((time.perf_counter() - started) * 1000)
    except (OSError, asyncio.TimeoutError, UnicodeError, ValueError):
        return False, None
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), 0.5)


async def reach_internet(host: str, port: int, timeout: float) -> tuple[bool, int | None, str | None]:
    loop = asyncio.get_running_loop()
    started = time.perf_counter()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout)
    except (OSError, asyncio.TimeoutError, UnicodeError, ValueError):
        return False, None, f"Имя {host} не находится — DNS без интернета"
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses or set(addresses) <= {config.PORTAL_HOST}:
        return False, None, f"{host} указывает на портал коробки — внешней сети нет"
    left = max(0.2, timeout - (time.perf_counter() - started))
    ok, _ = await tcp_probe(addresses[0], port, left)
    if not ok:
        return False, None, f"{host}:{port} не отвечает"
    return True, int((time.perf_counter() - started) * 1000), None


def _is_local_ip(host: str) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind((host, 0))
        return True
    except OSError:
        return False


def dns_query_packet(name: str, qid: int) -> bytes:
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    labels = b"".join(bytes([len(p)]) + p for p in (s.encode("ascii") for s in name.strip(".").split(".")))
    return header + labels + b"\x00" + struct.pack(">HH", 1, 1)


def _skip_name(data: bytes, pos: int) -> int:
    for _ in range(128):
        length = data[pos]
        if length & 0xC0 == 0xC0:
            return pos + 2
        if length == 0:
            return pos + 1
        pos += length + 1
    raise ValueError("слишком длинное имя")


def dns_parse_answer(data: bytes, qid: int) -> tuple[int, list[str]]:
    if len(data) < 12:
        raise ValueError("слишком короткий ответ")
    rid, flags, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", data[:12])
    if rid != qid or not flags & 0x8000:
        raise LookupError("чужой пакет")
    pos = 12
    for _ in range(qdcount):
        pos = _skip_name(data, pos) + 4
    found = []
    for _ in range(ancount):
        pos = _skip_name(data, pos)
        rtype, rclass, _, rdlength = struct.unpack(">HHIH", data[pos:pos + 10])
        pos += 10
        rdata = data[pos:pos + rdlength]
        pos += rdlength
        if rtype == 1 and rclass == 1 and len(rdata) == 4:
            found.append(socket.inet_ntoa(rdata))
    return flags & 0x000F, found


async def dns_lookup(server: str, name: str, timeout: float, port: int = 53) -> tuple[int, list[str]]:
    loop = asyncio.get_running_loop()
    qid = secrets.randbelow(0x10000)
    deadline = loop.time() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setblocking(False)
        sock.connect((server, port))
        await loop.sock_sendall(sock, dns_query_packet(name, qid))
        while True:
            left = deadline - loop.time()
            if left <= 0:
                raise asyncio.TimeoutError
            data = await asyncio.wait_for(loop.sock_recv(sock, 1500), left)
            try:
                return dns_parse_answer(data, qid)
            except LookupError:
                continue


class _Context:
    def __init__(self, database):
        self.db = database
        self.now = time.time()
        self.device = on_device()
        self.ai = ai_snapshot()
        self.mode = mode_state()
        self.hw = read_json(config.HW_STATE_FILE)
        ts = _number(self.hw.get("ts")) if self.hw else None
        self.hw_age = self.now - ts if ts is not None else None
        boot, hw_boot = _boot_id(), (self.hw or {}).get("boot_id")
        self.hw_same_boot = not (boot and isinstance(hw_boot, str) and hw_boot and hw_boot != boot)
        self.hw_fresh = (self.hw_age is not None and abs(self.hw_age) <= HW_STALE_S and self.hw_same_boot)
        self.power = read_json(config.POWER_FILE)
        if self.power is None and self.hw_fresh and isinstance(self.hw.get("power"), dict):
            self.power = self.hw["power"]
        self.integrity_task: asyncio.Future | None = None
        self.ai_task: asyncio.Future | None = None


def _hw_gate(ctx: _Context) -> tuple | None:
    if ctx.hw is None:
        return SKIP, "Нет данных от службы железа", None
    if not ctx.hw_fresh:
        why = "данные с прошлой загрузки" if not ctx.hw_same_boot else f"нет сигнала {_ago(ctx.hw_age)}"
        return WARN, f"{why.capitalize()} — служба железа не отвечает", None
    return None


def _clients() -> list | None:
    if not shutil.which("iw"):
        return None
    try:
        return stations.connected()
    except Exception as exc:
        log.info("iw station dump: %s", exc)
        return None


def _link(iface: str) -> str | None:
    if not iface or "/" in iface or iface.startswith("."):
        return None
    return _read_text(f"/sys/class/net/{iface}/operstate", 32)


async def _wifi(ctx: _Context) -> tuple:
    state, clients = await asyncio.gather(unit_state("hostapd"), asyncio.to_thread(_clients))
    link = _link(config.WLAN_IFACE)
    count = len(clients) if isinstance(clients, list) else None
    value = {"ssid": config.SSID, "iface": config.WLAN_IFACE, "link": link, "service": state, "clients": count}
    who = (f"подключено {_plural(count, 'устройство', 'устройства', 'устройств')}" if count is not None
           else "список клиентов недоступен")
    if state is None:
        if count:
            return OK, f"«{config.SSID}» в эфире · {who}", value
        return SKIP, "Нет systemd — точка доступа проверяется только на коробке", value
    if state != "active":
        return _unit_problem("hostapd", state, f"сеть «{config.SSID}» не раздаётся", value)
    if link is None:
        return WARN, f"hostapd запущен, но интерфейса {config.WLAN_IFACE} нет", value
    if link == "down":
        return WARN, f"hostapd запущен, но {config.WLAN_IFACE} выключен", value
    return OK, f"«{config.SSID}» в эфире · {who}", value


def _leases(now: float) -> int | None:
    try:
        with open(config.DHCP_LEASES, encoding="utf-8", errors="replace") as f:
            lines = f.read(1 << 20).splitlines()
    except (OSError, TypeError, ValueError):
        return None
    active = 0
    for line in lines:
        parts = line.split()
        if len(parts) >= 4 and parts[0].isdigit() and (int(parts[0]) == 0 or int(parts[0]) > now):
            active += 1
    return active


async def _dhcp(ctx: _Context) -> tuple:
    state, leases = await asyncio.gather(unit_state("dnsmasq"), asyncio.to_thread(_leases, ctx.now))
    value = {"service": state, "leases": leases}
    got = (f"выдано {_plural(leases, 'адрес', 'адреса', 'адресов')}" if leases is not None
           else "аренд пока нет")
    if state is None:
        if leases:
            return OK, f"Раздача адресов идёт · {got}", value
        return SKIP, "Нет systemd — DHCP проверяется только на коробке", value
    if state != "active":
        return _unit_problem("dnsmasq", state, "телефоны не получат адрес", value)
    return OK, f"dnsmasq работает · {got}", value


async def _dns(ctx: _Context) -> tuple:
    host = config.PORTAL_HOST
    value = {"server": host, "name": DNS_NAME, "answers": [], "ms": None}
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        return SKIP, f"Адрес портала «{host}» не IPv4 — проверка невозможна", value
    if not _is_local_ip(host):
        if ctx.device:
            return FAIL, f"Адрес {host} не поднят — точка доступа не настроена", value
        return SKIP, f"Адрес {host} не принадлежит этой машине — проверка только на коробке", value
    started = time.perf_counter()
    try:
        rcode, answers = await dns_lookup(host, DNS_NAME, DNS_TIMEOUT, DNS_PORT)
    except asyncio.TimeoutError:
        return FAIL, f"DNS на {host} не ответил за {DNS_TIMEOUT:g} с", value
    except ConnectionRefusedError:
        return FAIL, f"DNS на {host}:{DNS_PORT} не запущен — порт закрыт", value
    except (OSError, ValueError, IndexError, struct.error) as exc:
        return FAIL, f"DNS ответил с ошибкой: {exc}", value
    value.update(answers=answers, ms=int((time.perf_counter() - started) * 1000))
    if rcode:
        return FAIL, f"DNS вернул «{DNS_RCODES.get(rcode, rcode)}» — портал не всплывёт", value
    if host in answers:
        return OK, f"{DNS_NAME} → {host} за {max(value['ms'], 1)} мс — любой сайт ведёт на портал", value
    if answers:
        return FAIL, f"DNS указывает на {answers[0]} вместо {host} — портал не всплывёт", value
    return FAIL, "DNS ответил без адреса — портал не всплывёт", value


async def _web(ctx: _Context) -> tuple:
    state, (port_open, ms) = await asyncio.gather(unit_state("nginx"), tcp_probe("127.0.0.1", 80, 1.0))
    value = {"service": state, "port80": port_open, "ms": ms, "app": True}
    if state is None:
        if port_open:
            return OK, "Порт 80 отвечает · приложение работает", value
        return SKIP, "Нет systemd и порта 80 — nginx проверяется только на коробке", value
    if state != "active":
        return _unit_problem("nginx", state, f"портал http://{config.PORTAL_HOST}/ недоступен", value)
    if not port_open:
        return WARN, "nginx запущен, но порт 80 не отвечает", value
    return OK, f"nginx на порту 80 · приложение отвечает · {max(ms or 0, 1)} мс", value


async def _internet(ctx: _Context) -> tuple:
    cloud = _part(ctx.ai, "cloud")
    online, via, ms, why = cloud.get("online"), "фоновая проверка ИИ", None, None
    if online is not True:
        online, ms, why = await reach_internet(config.CLOUD_HOST, 443, INTERNET_TIMEOUT)
        via = f"TCP {config.CLOUD_HOST}:443"
    value = {"online": online, "host": config.CLOUD_HOST, "via": via, "ms": ms, "reason": why}
    if online:
        tail = f" · {_ms(ms)}" if _ms(ms) else ""
        return OK, f"Есть связь с {config.CLOUD_HOST}{tail}", value
    if cloud.get("configured") and ctx.ai.get("mode") in ("auto", "cloud"):
        return WARN, "Интернета нет — облачный ИИ недоступен, отвечают локальный и резервный", value
    return SKIP, "Интернета нет — он и не нужен: коробка работает автономно", value


def _db_stats(database) -> dict | None:
    if database is not None and hasattr(database, "health"):
        stats = database.health()
        stats["memory"] = bool(stats.get("memory")) and config.DB_PATH != ":memory:"
        return stats
    return dbmod.inspect(config.DB_PATH)


async def _db(ctx: _Context) -> tuple:
    stats = await asyncio.to_thread(_db_stats, ctx.db)
    if stats is None:
        return SKIP, "База ещё не создана", None
    if stats.get("quick_check") != "ok":
        return FAIL, f"База повреждена: {str(stats.get('quick_check'))[:120]}", stats
    if stats.get("memory"):
        return FAIL, "База только в памяти — диск недоступен, вызовы пропадут при перезапуске", stats
    calls = _plural(int(stats.get("incidents") or 0), "вызов", "вызова", "вызовов")
    msgs = _plural(int(stats.get("messages") or 0), "сообщение", "сообщения", "сообщений")
    return OK, f"Целостность в порядке · {calls}, {msgs}", stats


async def _triage(ctx: _Context) -> tuple:
    started = time.perf_counter()
    critical, mild = assess([CRITICAL_SAMPLE]), assess([MILD_SAMPLE])
    ms = round((time.perf_counter() - started) * 1000, 2)
    value = {"critical": {"text": CRITICAL_SAMPLE, "priority": critical.priority, "tags": critical.tags},
             "mild": {"text": MILD_SAMPLE, "priority": mild.priority, "tags": mild.tags}, "ms": ms}
    if critical.priority != RED:
        return FAIL, f"Тяжёлый случай получил {PRIORITY_RU.get(critical.priority)} вместо КРАСНОГО", value
    if mild.priority == RED:
        return FAIL, "Лёгкий случай ошибочно помечен КРАСНЫМ", value
    return OK, (f"«без сознания, придавило» → КРАСНЫЙ, «все целы» → {PRIORITY_RU.get(mild.priority)}"
                f" · {max(ms, 0.1):.1f} мс"), value


def _needs_probe(snap: dict) -> bool:
    return any(_part(snap, key).get("state") == "unknown" for key in ("cloud", "local"))


async def _probe_ai() -> None:
    await ai.probe_now()


async def _ai_view(ctx: _Context) -> dict:
    task = ctx.ai_task
    if task is None:
        return ctx.ai
    if not task.done():
        with contextlib.suppress(Exception):
            await asyncio.wait_for(asyncio.shield(task), AI_WAIT)
    ctx.ai = ai_snapshot()
    return ctx.ai


def _left(until, now: float) -> str:
    until = _number(until)
    if until is None or until <= now:
        return ""
    return f" · повтор через {int(until - now) + 1} с"


async def _ai_cloud(ctx: _Context) -> tuple:
    snap = await _ai_view(ctx)
    cloud = _part(snap, "cloud")
    ai_mode, state, reason = snap.get("mode"), cloud.get("state"), cloud.get("reason")
    value = {k: cloud.get(k) for k in ("state", "model", "online", "latency_ms", "calls", "failures")}
    model = cloud.get("model") or config.CLOUD_MODEL
    if ai_mode in ("local", "offline"):
        return SKIP, f"Не используется в режиме «{ai_mode}»", value
    if not cloud.get("configured"):
        return SKIP, reason or "Ключ API не задан — облачный ИИ не используется", value
    if cloud.get("sdk") is False:
        return WARN, reason or "Не установлена библиотека anthropic", value
    if state == "ok":
        lat = _ms(cloud.get("latency_ms"))
        return OK, f"{model} на связи" + (f" · ответ за {lat}" if lat else ""), value
    if state == "error":
        return FAIL, reason or "Облачный ИИ отклоняет запросы", value
    if state == "cooldown":
        return WARN, (reason or "Пауза после ошибки") + _left(cloud.get("cooldown_until"), ctx.now), value
    if state == "offline":
        return WARN, reason or "Нет интернета — облако недоступно", value
    if state == "disabled":
        return WARN, reason or "Облачный ИИ отключён", value
    if cloud.get("online"):
        return OK, f"{model} готов: ключ задан, сеть есть", value
    return WARN, reason or "Облачный ИИ ещё не проверялся", value


async def _ai_local(ctx: _Context) -> tuple:
    snap = await _ai_view(ctx)
    local = _part(snap, "local")
    ai_mode, state, reason = snap.get("mode"), local.get("state"), local.get("reason")
    power = local.get("power") or "unknown"
    value = {k: local.get(k) for k in ("state", "model", "latency_ms", "calls", "failures", "power")}
    if ai_mode in ("cloud", "offline"):
        return SKIP, f"Не используется в режиме «{ai_mode}»", value
    if not local.get("enabled") or state == "disabled":
        if power == "off":
            return WARN, reason or "Локальный ИИ выключен сторожем питания", value
        return SKIP, reason or "Локальный ИИ отключён в настройках", value
    if state == "ok":
        lat = _ms(local.get("latency_ms"))
        return OK, ("llama-server отвечает" + (f" · {lat}" if lat else "")
                    + f" · питание: {POWER_RU.get(power, power)}"), value
    if state == "loading":
        return WARN, reason or "Модель загружается в память — это до пары минут", value
    if state == "cooldown":
        return WARN, (reason or "Пауза после сбоя") + _left(local.get("cooldown_until"), ctx.now), value
    if state == "down":
        return WARN, reason or "llama-server не запущен — отвечают облако или резерв", value
    return WARN, reason or "Локальный ИИ ещё не проверялся", value


async def _ai_reserve(ctx: _Context) -> tuple:
    snap = await _ai_view(ctx)
    reserve = _part(snap, "reserve")
    active = snap.get("active") or "reserve"
    sample = fallback_reply(assess([CRITICAL_SAMPLE]))
    value = {"state": reserve.get("state", "ok"), "active": active, "sample": sample}
    if not sample:
        return FAIL, "Резервные ответы не формируются", value
    if reserve.get("state") not in (None, "ok"):
        return WARN, f"Резерв в состоянии «{reserve.get('state')}»", value
    return OK, f"Работают всегда, без сети и модели · первым сейчас отвечает: {ENGINE_RU.get(active, active)}", value


def _hex(addr) -> str:
    if isinstance(addr, int) and not isinstance(addr, bool):
        return f"0x{addr:02x}"
    return str(addr) if addr not in (None, "") else "?"


async def _sensor(ctx: _Context) -> tuple:
    gate = _hw_gate(ctx)
    if gate:
        return gate
    sensor = _part(ctx.hw, "sensor")
    bus, addr, g = sensor.get("bus"), sensor.get("addr"), _number(sensor.get("last_g"))
    value = {"present": bool(sensor.get("present")), "bus": bus, "addr": addr, "last_g": g}
    where = f"i2c-{bus}, адрес {_hex(addr)}"
    if sensor.get("present"):
        return OK, f"MPU-6050 на {where}" + (f" · {g:.2f} g" if g is not None else ""), value
    if bus not in (None, ""):
        return WARN, f"MPU-6050 не отвечает на {where} — ЧС включается из консоли", value
    return SKIP, "Датчик не подключён — режим ЧС включается из консоли спасателя", value


async def _lamp(ctx: _Context) -> tuple:
    gate = _hw_gate(ctx)
    if gate:
        return gate
    lamp = _part(ctx.hw, "lamp")
    gpio, state = lamp.get("gpio"), lamp.get("state")
    value = {"gpio": gpio, "state": state}
    if gpio in (None, ""):
        return SKIP, "Лампа SOS не настроена (STELLA_LED_GPIO)", value
    if state is None:
        return WARN, f"GPIO {gpio} не удалось настроить", value
    if ctx.mode.get("mode") == mode.EMERGENCY:
        return OK, f"GPIO {gpio} · частое мигание — режим ЧС", value
    return OK, f"GPIO {gpio} · короткая вспышка раз в 3 с — дежурство", value


def _hw_temp(hw) -> float | None:
    return _celsius(_part(hw, "temps").get("max"))


async def _fan(ctx: _Context) -> tuple:
    gate = _hw_gate(ctx)
    if gate:
        return gate
    fan = _part(ctx.hw, "fan")
    gpio, on = fan.get("gpio"), fan.get("on")
    value = {"gpio": gpio, "on": on}
    if gpio in (None, ""):
        return SKIP, "Кулер без управления (питание 5 В) — крутится постоянно", value
    if on is None:
        return WARN, f"GPIO {gpio} не удалось настроить", value
    temp = _hw_temp(ctx.hw)
    if not on and temp is not None and temp >= TEMP_WARN:
        return WARN, f"Горячо ({temp:.0f} °C), а вентилятор стоит", value
    return OK, f"GPIO {gpio} · " + ("крутится" if on else "выключен — температура в норме"), value


def _celsius(raw) -> float | None:
    if isinstance(raw, str):
        try:
            raw = float(raw)
        except ValueError:
            return None
    value = _number(raw)
    if value is None:
        return None
    if abs(value) > 1000:
        value /= 1000
    return round(value, 1) if -40 <= value <= 150 else None


def _sysfs_temps() -> dict[str, float]:
    zones: dict[str, float] = {}
    for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        value = _celsius(_read_text(zone + "/temp", 32))
        if value is None:
            continue
        name = _read_text(zone + "/type", 64) or os.path.basename(zone)
        key, n = name, 2
        while key in zones:
            key, n = f"{name}-{n}", n + 1
        zones[key] = value
    return zones


def _temps(ctx: _Context) -> dict | None:
    if ctx.hw_fresh:
        temps = _part(ctx.hw, "temps")
        zones = {str(k): c for k, c in ((k, _celsius(v)) for k, v in _part(temps, "zones").items())
                 if c is not None}
        peak = _celsius(temps.get("max"))
        if peak is None and zones:
            peak = max(zones.values())
        if peak is not None:
            return {"max": peak, "soc": _celsius(temps.get("soc")), "zones": zones, "source": "stella-hw"}
    zones = _sysfs_temps()
    if not zones:
        return None
    return {"max": max(zones.values()), "soc": None, "zones": zones, "source": "sysfs"}


async def _temp(ctx: _Context) -> tuple:
    data = await asyncio.to_thread(_temps, ctx)
    if data is None:
        return SKIP, "Датчики температуры недоступны на этой машине", None
    peak = data["max"]
    if peak >= TEMP_FAIL:
        return FAIL, f"{peak:.0f} °C — перегрев! Проверьте вентилятор и не накрывайте корпус", data
    if peak >= TEMP_WARN:
        return WARN, f"{peak:.0f} °C — горячо, нужен обдув", data
    return OK, f"{peak:.0f} °C — норма", data


def _meminfo() -> dict | None:
    info = {}
    for line in (_read_text("/proc/meminfo", 65536) or "").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            info[key.strip()] = int(parts[0]) * 1024
    total = info.get("MemTotal")
    if not total:
        return None
    avail = info.get("MemAvailable")
    if avail is None:
        avail = info.get("MemFree", 0) + info.get("Buffers", 0) + info.get("Cached", 0)
    avail = min(avail, total)
    return {"total_mb": total >> 20, "available_mb": avail >> 20, "used_pct": round(100 - avail * 100 / total),
            "swap_total_mb": info.get("SwapTotal", 0) >> 20, "swap_free_mb": info.get("SwapFree", 0) >> 20}


async def _memory(ctx: _Context) -> tuple:
    mem = _meminfo()
    if mem is None:
        return SKIP, "Нет /proc/meminfo — это не Linux", None
    free_pct = 100 - mem["used_pct"]
    detail = f"Свободно {mem['available_mb']} МБ из {mem['total_mb']} МБ"
    if mem["available_mb"] < 64 or free_pct < 5:
        return FAIL, f"{detail} — память на исходе", mem
    if mem["available_mb"] < 200 or free_pct < 15:
        return WARN, f"{detail} — памяти мало", mem
    return OK, detail, mem


def _existing(path: Path) -> Path:
    for candidate in (path, *path.parents):
        with contextlib.suppress(OSError):
            if candidate.is_dir():
                return candidate
    return Path(os.path.abspath(os.sep))


async def _disk(ctx: _Context) -> tuple:
    where = _existing(Path(config.STATE_DIR or os.sep).absolute())
    usage = await asyncio.to_thread(shutil.disk_usage, where)
    free_pct = usage.free * 100 / usage.total if usage.total else 0
    value = {"path": str(where), "total": usage.total, "free": usage.free, "free_pct": round(free_pct, 1)}
    detail = f"Свободно {_bytes(usage.free)} из {_bytes(usage.total)}"
    if usage.free < 100 * 1024 ** 2 or free_pct < 3:
        return FAIL, f"{detail} — диск почти заполнен", value
    if usage.free < 500 * 1024 ** 2 or free_pct < 10:
        return WARN, f"{detail} — места мало", value
    return OK, detail, value


async def _power(ctx: _Context) -> tuple:
    power = ctx.power
    if power is None:
        if ctx.device:
            return WARN, "Сторож питания ещё не записал состояние (stella-hw)", None
        return SKIP, "Нет данных сторожа питания — это не коробка", None
    profile, setting = power.get("profile"), power.get("setting")
    unclean = int(_number(power.get("unclean_boots")) or 0)
    stamps = power.get("recent_unclean") if isinstance(power.get("recent_unclean"), list) else []
    recent = [t for t in map(_number, stamps) if t is not None and 0 <= ctx.now - t < 1800]
    value = {"profile": profile, "setting": setting, "unclean_boots": unclean,
             "last_unclean": _number(power.get("last_unclean")), "reason": power.get("reason")}
    how = "авто" if setting == "auto" else "вручную"
    tail = (f" · аварийных перезагрузок: {unclean}" if unclean else " · аварийных перезагрузок не было")
    if profile == "off":
        return WARN, (power.get("reason") or "Локальный ИИ выключен сторожем питания") + tail, value
    if profile == "safe":
        text = "Щадящий режим: ИИ на одном ядре, частота ограничена"
    elif profile == "normal":
        text = "Обычный режим питания"
    else:
        return WARN, f"Неизвестный профиль питания «{profile}»", value
    if recent:
        return WARN, f"{text} · аварийная перезагрузка {_ago(ctx.now - max(recent))}", value
    return OK, f"{text} ({how}){tail}", value


async def _hw_daemon(ctx: _Context) -> tuple:
    if ctx.hw is None:
        if ctx.device:
            return WARN, "Нет данных — служба железа stella-hw не запущена", None
        return SKIP, "Служба железа работает только на коробке", None
    value = {"pid": ctx.hw.get("pid"), "age_s": round(ctx.hw_age, 1) if ctx.hw_age is not None else None,
             "same_boot": ctx.hw_same_boot, "llm_active": ctx.hw.get("llm_active")}
    gate = _hw_gate(ctx)
    if gate:
        return gate[0], gate[1], value
    pid = ctx.hw.get("pid")
    who = f" · PID {pid}" if isinstance(pid, int) else ""
    return OK, f"stella-hw работает{who} · сигнал {_ago(ctx.hw_age)}", value


def _integrity_block() -> dict:
    manifest_file = Path(config.MANIFEST_FILE)
    manifest = integrity.load(manifest_file)
    block = integrity.verify(Path(config.APP_ROOT), manifest)
    try:
        exists = manifest_file.is_file()
    except OSError:
        exists = False
    block["manifest"] = "ok" if manifest else ("corrupt" if exists else "missing")
    return block


def _integrity_unknown(reason: str) -> dict:
    return {"status": "unknown", "files": 0, "changed": [], "missing": [], "added": [], "unreadable": [],
            "digest": "", "expected": None, "version": None, "created": None, "manifest": reason}


def _shorten(paths: list[str], limit: int = 3) -> str:
    shown = ", ".join(p.split("/", 1)[-1] for p in paths[:limit])
    return shown + (f" и ещё {len(paths) - limit}" if len(paths) > limit else "")


async def _integrity(ctx: _Context) -> tuple:
    block = await asyncio.shield(ctx.integrity_task)
    changed, missing, added = block.get("changed") or [], block.get("missing") or [], block.get("added") or []
    digest = block.get("digest") or ""
    value = {"files": block.get("files"), "changed": len(changed), "missing": len(missing),
             "added": len(added), "digest": digest[:16], "manifest": block.get("manifest")}
    if block.get("status") == "unknown":
        if block.get("manifest") == "corrupt":
            return WARN, "Манифест повреждён — сверять файлы не с чем", value
        return SKIP, "Манифест не найден — контроль целостности не настроен", value
    if missing:
        return FAIL, f"Не хватает файлов: {len(missing)} ({_shorten(missing)})", value
    if changed or added:
        diff = changed + added
        return WARN, f"Изменено файлов: {len(diff)} ({_shorten(diff)})", value
    files = int(block.get("files") or 0)
    return OK, f"{_plural(files, 'файл', 'файла', 'файлов')} совпадают с эталоном · {digest[:12]}", value


async def _mode(ctx: _Context) -> tuple:
    state = ctx.mode
    value = {k: state.get(k) for k in ("mode", "source", "since", "note")}
    if state.get("mode") == mode.EMERGENCY:
        since = _number(state.get("since"))
        when = f" · включён {_ago(ctx.now - since)}" if since else ""
        return OK, f"РЕЖИМ ЧС ({SOURCE_RU.get(state.get('source'), 'вручную')}){when}", value
    return OK, "Дежурный режим — коробка ждёт ЧС", value


CHECKS = (
    ("wifi", "Сеть", "Точка доступа Wi‑Fi", _wifi, 4.0),
    ("dhcp", "Сеть", "Раздача адресов (DHCP)", _dhcp, 3.0),
    ("dns", "Сеть", "Перехват DNS для портала", _dns, 3.0),
    ("web", "Сеть", "Веб-сервер портала", _web, 3.0),
    ("internet", "Сеть", "Выход в интернет", _internet, 3.5),
    ("db", "Данные", "База вызовов", _db, 4.0),
    ("triage", "Данные", "Сортировка пострадавших", _triage, 2.0),
    ("ai_cloud", "ИИ", "Облачный ИИ (Claude)", _ai_cloud, 4.5),
    ("ai_local", "ИИ", "Локальный ИИ (llama.cpp)", _ai_local, 4.5),
    ("ai_reserve", "ИИ", "Резервные ответы", _ai_reserve, 4.5),
    ("sensor", "Железо", "Датчик землетрясений", _sensor, 1.0),
    ("lamp", "Железо", "Лампа SOS", _lamp, 1.0),
    ("fan", "Железо", "Вентилятор", _fan, 1.0),
    ("temp", "Железо", "Температура процессора", _temp, 2.0),
    ("memory", "Система", "Оперативная память", _memory, 1.0),
    ("disk", "Система", "Место на накопителе", _disk, 2.0),
    ("power", "Система", "Сторож питания", _power, 1.0),
    ("hw_daemon", "Система", "Служба железа", _hw_daemon, 1.0),
    ("integrity", "Система", "Целостность прошивки", _integrity, 4.5),
    ("mode", "Система", "Режим работы", _mode, 1.0),
)
CHECK_IDS = tuple(spec[0] for spec in CHECKS)


async def _timed(func, ctx: _Context, clock: list) -> tuple:
    clock[0] = time.perf_counter()
    try:
        return await func(ctx)
    finally:
        clock[1] = time.perf_counter()


async def _run_check(spec: tuple, ctx: _Context) -> dict:
    cid, group, title, func, timeout = spec
    clock = [time.perf_counter(), None]
    try:
        status, detail, value = await asyncio.wait_for(_timed(func, ctx, clock), timeout)
    except asyncio.TimeoutError:
        status, detail, value = WARN, f"Проверка не уложилась в {timeout:g} с", None
    except Exception as exc:
        log.warning("проверка %s упала: %r", cid, exc)
        status, detail, value = WARN, f"Проверка не выполнена: {exc.__class__.__name__}", None
    if status not in STATUSES:
        status = WARN
    return {"id": cid, "group": group, "title": title, "status": status, "detail": str(detail)[:300],
            "value": json_safe(value), "ms": int(((clock[1] or time.perf_counter()) - clock[0]) * 1000)}


def _summary(checks: list[dict]) -> dict:
    counts = {s: sum(1 for c in checks if c["status"] == s) for s in STATUSES}
    verdict = FAIL if counts[FAIL] else WARN if counts[WARN] else OK
    return {**counts, "total": len(checks), "verdict": verdict}


def _integrity_result(task: asyncio.Future | None) -> dict:
    if task is None or not task.done():
        return _integrity_unknown("timeout")
    if task.cancelled() or task.exception() is not None:
        return _integrity_unknown("error")
    return task.result()


def _consume(task: asyncio.Future) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.warning("фоновая проверка упала: %r", task.exception())


def _background(coro) -> asyncio.Future:
    task = asyncio.ensure_future(coro)
    task.add_done_callback(_consume)
    return task


async def run(database=None) -> dict:
    started = time.perf_counter()
    try:
        ctx = _Context(database)
        ctx.integrity_task = _background(asyncio.to_thread(_integrity_block))
        if _needs_probe(ctx.ai):
            ctx.ai_task = _background(_probe_ai())
        checks = list(await asyncio.gather(*(_run_check(spec, ctx) for spec in CHECKS)))
        block = _integrity_result(ctx.integrity_task)
        extra = {"ai": ai_snapshot(), "hw": ctx.hw, "power": ctx.power}
    except Exception as exc:
        log.error("диагностика упала: %r", exc)
        checks = [{"id": cid, "group": group, "title": title, "status": WARN,
                   "detail": "Диагностика прервалась", "value": None, "ms": 0}
                  for cid, group, title, _, _ in CHECKS]
        block, extra = _integrity_unknown("error"), {"ai": ai_snapshot(), "hw": None, "power": None}
    report = {"node": node_id(), "version": config.VERSION, "time": time.time(),
              "duration_ms": int((time.perf_counter() - started) * 1000), "summary": _summary(checks),
              "checks": checks, "identity": _safe_identity(), "integrity": block, "hub": hub_location(),
              **extra}
    return json_safe(report)


def _safe_identity() -> dict:
    try:
        return identity()
    except Exception as exc:
        log.warning("identity: %r", exc)
        return {"node": node_id(), "model": None, "os": None, "kernel": None, "python": platform.python_version(),
                "hostname": None, "uptime_s": None}
