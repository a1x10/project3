"""Поиск устройств в локальной сети: пинг-свип /24 + чтение ARP-таблицы (ip neigh)."""
import asyncio
import ipaddress
import logging
import re
import socket
import subprocess
import time

from . import config, db, devices

log = logging.getLogger("homeguard.scan")

NEIGH_RE = re.compile(r"^(\S+) dev (\S+) lladdr ([0-9a-f:]{17}) (\S+)", re.I | re.M)


def local_network() -> tuple[str, ipaddress.IPv4Network, str | None] | None:
    """(наш IP, подсеть, IP шлюза) по маршруту по умолчанию."""
    try:
        route = subprocess.run(["ip", "-4", "route", "show", "default"], capture_output=True,
                               text=True, timeout=5).stdout
        m = re.search(r"default via (\S+) dev (\S+)", route)
        if not m:
            return None
        gw, dev = m.group(1), m.group(2)
        addr = subprocess.run(["ip", "-4", "-o", "addr", "show", "dev", dev], capture_output=True,
                              text=True, timeout=5).stdout
        a = re.search(r"inet (\S+)", addr)
        if not a:
            return None
        iface = ipaddress.ip_interface(a.group(1))
        net = iface.network
        if net.prefixlen < 24:  # не сканируем огромные сети — только свой /24
            net = ipaddress.ip_network(f"{iface.ip}/24", strict=False)
        return str(iface.ip), net, gw
    except (OSError, subprocess.SubprocessError):
        return None


def own_mac(ip: str) -> str | None:
    try:
        out = subprocess.run(["ip", "-o", "link"], capture_output=True, text=True, timeout=5).stdout
        addr = subprocess.run(["ip", "-4", "-o", "addr"], capture_output=True, text=True, timeout=5).stdout
        dev = next((l.split()[1] for l in addr.splitlines() if f"inet {ip}/" in l), None)
        for line in out.splitlines():
            if dev and line.split()[1].rstrip(":") == dev:
                m = re.search(r"link/ether ([0-9a-f:]{17})", line)
                return m.group(1) if m else None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


async def _ping(ip: str, sem: asyncio.Semaphore) -> None:
    async with sem:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", "1", ip,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.wait()


def read_neighbors() -> dict[str, str]:
    """{mac: ip} из ARP-таблицы (только живые записи)."""
    try:
        out = subprocess.run(["ip", "neigh", "show"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    res = {}
    for ip, _dev, mac, state in NEIGH_RE.findall(out):
        if state.upper() in ("REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT") and ":" not in ip:
            res[mac.lower()] = ip
    return res


def resolve_name(ip: str) -> str | None:
    try:
        name = socket.gethostbyaddr(ip)[0]
        return name.split(".")[0] if name and name != ip else None
    except (OSError, socket.herror):
        return None


async def scan_once() -> int:
    net = local_network()
    if net is None:
        log.warning("Не удалось определить локальную сеть — пропускаю скан")
        return 0
    my_ip, network, gateway = net
    sem = asyncio.Semaphore(64)
    await asyncio.gather(*(_ping(str(h), sem) for h in network.hosts()))
    loop = asyncio.get_running_loop()
    found = await loop.run_in_executor(None, read_neighbors)
    me = own_mac(my_ip)
    if me:
        found[me] = my_ip
    for mac, ip in found.items():
        hostname = await loop.run_in_executor(None, resolve_name, ip)
        vendor = devices.vendor_of(mac)
        dtype = devices.guess_type(hostname, vendor, is_gateway=(ip == gateway))
        db.upsert_device(mac, ip, hostname, vendor, dtype, is_self=(ip == my_ip))
    log.info("Скан завершён: найдено %d устройств", len(found))
    return len(found)


async def scan_loop() -> None:
    while True:
        try:
            await scan_once()
        except Exception:  # скан не должен ронять сервис
            log.exception("Ошибка скана")
        await asyncio.sleep(config.SCAN_INTERVAL)
