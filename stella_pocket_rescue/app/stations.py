"""Живые подключения к точке доступа Orange Pi.

Берём данные прямо из сетевого стека — это честный аналог «вижу каждое
подключение»: кто физически присоединился к Wi-Fi хаба, насколько сильный
сигнал (значит — насколько близко человек), сколько времени в сети.

Источники:
  * `iw dev wlan0 station dump` — MAC, сигнал (dBm), время в сети, трафик;
  * файл аренды dnsmasq — соответствие MAC ↔ IP ↔ имя устройства.

На ноутбуке для разработки команды `iw` нет — тогда возвращаем пустой
список, и панель спасателя просто показывает подключения по данным браузера.
"""
import math
import re
import subprocess
import time

from . import config

_MAC_RE = re.compile(r"Station ([0-9a-f:]{17})", re.I)
_SIGNAL_RE = re.compile(r"signal:\s*(-?\d+)")
_CONNECTED_RE = re.compile(r"connected time:\s*(\d+)")
_INACTIVE_RE = re.compile(r"inactive time:\s*(\d+)")
_RX_RE = re.compile(r"rx bytes:\s*(\d+)")
_TX_RE = re.compile(r"tx bytes:\s*(\d+)")


def distance_m(rssi: int) -> float:
    """Грубая оценка расстояния до телефона по силе сигнала (модель затухания)."""
    exp = (config.RSSI_REF_DBM - rssi) / (10 * config.RSSI_PATH_LOSS)
    return round(10 ** exp, 1)


def proximity(rssi: int) -> str:
    if rssi >= -55:
        return "рядом"          # несколько метров, в прямой видимости
    if rssi >= -70:
        return "близко"         # эта комната / соседняя
    if rssi >= -82:
        return "далеко"         # через стены, дальний угол здания
    return "на пределе"         # у границы зоны — сигнал вот-вот пропадёт


def _read_leases() -> dict[str, dict]:
    """MAC -> {ip, hostname}. Формат dnsmasq: ts mac ip hostname clientid."""
    out: dict[str, dict] = {}
    try:
        with open(config.DHCP_LEASES) as f:
            for line in f:
                p = line.split()
                if len(p) >= 4:
                    out[p[1].lower()] = {"ip": p[2], "hostname": None if p[3] == "*" else p[3]}
    except OSError:
        pass
    return out


def _station_dump() -> str:
    try:
        return subprocess.run(
            ["iw", "dev", config.WLAN_IFACE, "station", "dump"],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _parse(dump: str) -> list[dict]:
    stations, cur = [], None
    for line in dump.splitlines():
        m = _MAC_RE.search(line)
        if m:
            cur = {"mac": m.group(1).lower(), "signal": None, "connected_s": None,
                   "inactive_ms": None, "rx": 0, "tx": 0}
            stations.append(cur)
        elif cur is not None:
            for rx, key, cast in (
                (_SIGNAL_RE, "signal", int), (_CONNECTED_RE, "connected_s", int),
                (_INACTIVE_RE, "inactive_ms", int), (_RX_RE, "rx", int), (_TX_RE, "tx", int),
            ):
                mm = rx.search(line)
                if mm:
                    cur[key] = cast(mm.group(1))
    return stations


def connected() -> list[dict]:
    """Список устройств на точке доступа, ближние — первыми."""
    leases = _read_leases()
    result = []
    for st in _parse(_station_dump()):
        lease = leases.get(st["mac"], {})
        rssi = st["signal"]
        result.append({
            "mac": st["mac"],
            "ip": lease.get("ip"),
            "hostname": lease.get("hostname"),
            "signal": rssi,
            "proximity": proximity(rssi) if rssi is not None else None,
            "distance_m": distance_m(rssi) if rssi is not None else None,
            "connected_s": st["connected_s"],
            "idle_s": round(st["inactive_ms"] / 1000) if st["inactive_ms"] is not None else None,
            "kb": round((st["rx"] + st["tx"]) / 1024),
        })
    result.sort(key=lambda s: s["signal"] if s["signal"] is not None else -999, reverse=True)
    return result


def by_ip(stations: list[dict]) -> dict[str, dict]:
    return {s["ip"]: s for s in stations if s["ip"]}


def uptime() -> dict:
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
    except OSError:
        secs = 0.0
    load = None
    try:
        load = round(__import__("os").getloadavg()[0], 2)
    except OSError:
        pass
    return {"uptime_s": int(secs), "load": load, "now": time.time()}
