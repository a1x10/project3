import asyncio
import importlib
import json
import os
import re
import socket
import sqlite3
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
PIN = {"X-Rescuer-Pin": "123456"}
CHECK_IDS = ["wifi", "dhcp", "dns", "web", "internet", "db", "triage", "ai_cloud", "ai_local", "ai_reserve",
             "sensor", "lamp", "fan", "temp", "memory", "disk", "power", "hw_daemon", "integrity", "mode"]
CHECK_KEYS = {"id", "group", "title", "status", "detail", "value", "ms"}
STATUSES = {"ok", "warn", "fail", "skip"}
ISOLATED = ("STELLA_HW_STATE", "STELLA_POWER_FILE", "STELLA_HUB_FILE", "STELLA_HUB_LAT", "STELLA_HUB_LON",
            "STELLA_APP_ROOT", "STELLA_PORTAL_HOST", "STELLA_WLAN", "STELLA_AI_MODE")

OLD_SCHEMA = """
CREATE TABLE incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT UNIQUE NOT NULL, created REAL NOT NULL,
    updated REAL NOT NULL, priority TEXT NOT NULL DEFAULT 'unknown', score INTEGER NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]', people INTEGER, lat REAL, lon REAL, accuracy REAL, location_text TEXT,
    panic INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'new', note TEXT, client_ip TEXT, mac TEXT,
    device TEXT, device_info TEXT NOT NULL DEFAULT '{}', battery REAL, charging INTEGER, last_seen REAL
);
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
    text TEXT NOT NULL, ts REAL NOT NULL
);
CREATE INDEX messages_session ON messages(session_id, id);
CREATE TABLE broadcasts (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, ts REAL NOT NULL);
"""


@pytest.fixture()
def env(monkeypatch, tmp_path):
    state = tmp_path / "state"
    monkeypatch.setenv("STELLA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("STELLA_RESCUER_PIN", "123456")
    monkeypatch.setenv("STELLA_MIN_INTERVAL", "0")
    monkeypatch.setenv("STELLA_LLM_ENABLED", "0")
    monkeypatch.setenv("STELLA_STATE_DIR", str(state))
    monkeypatch.setenv("STELLA_MODE_FILE", str(state / "mode.json"))
    monkeypatch.setenv("STELLA_MANIFEST", str(tmp_path / "manifest.json"))
    monkeypatch.setenv("STELLA_LEASES", str(tmp_path / "leases"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    for name in ISOLATED:
        monkeypatch.delenv(name, raising=False)
    from app import config
    importlib.reload(config)
    return tmp_path


@pytest.fixture()
def client(env):
    from app import main
    importlib.reload(main)
    return TestClient(main.app), main


def _config():
    from app import config
    return importlib.reload(config)


def _diag():
    from app import diagnostics
    return diagnostics


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def _boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def _hw(ts=None, temp=51.0, fan_on=True, **extra):
    data = {"ts": time.time() if ts is None else ts, "pid": os.getpid(), "mode": "standby",
            "sensor": {"present": True, "bus": "4", "addr": 104, "last_g": 1.01},
            "leds": ["status"], "fan": {"gpio": "35", "on": fan_on}, "lamp": {"gpio": "33", "state": False},
            "temps": {"soc": temp - 1, "max": temp, "zones": {"soc-thermal": temp}}, "llm_active": False}
    if _boot_id():
        data["boot_id"] = _boot_id()
    data.update(extra)
    return data


def _power(profile="safe", **extra):
    data = {"profile": profile, "setting": "auto", "unclean_boots": 0, "recent_unclean": [],
            "last_unclean": None, "reason": None, "updated": time.time(), "boot_id": "x"}
    data.update(extra)
    return data


def _report(database=None) -> dict:
    return asyncio.run(_diag().run(database))


def _by_id(report: dict) -> dict:
    return {c["id"]: c for c in report["checks"]}


def test_hello_is_public_and_leaks_no_secrets(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-very-secret-key")
    _config()
    c, _ = client
    r = c.get("/api/verify/hello", headers={"Host": "10.42.0.1"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"node", "name", "version", "ssid", "portal", "uptime_s", "time", "mode"}
    assert body["name"] == "Stella Pocket" and body["version"] == _config().VERSION
    assert body["ssid"] == "SOS-STELLA-RESCUE" and body["portal"] == "http://10.42.0.1/"
    assert body["mode"] == "standby"
    assert re.fullmatch(r"STL-[0-9A-F]{4}-[0-9A-F]{4}", body["node"])
    assert "sk-ant" not in r.text and "123456" not in r.text
    machine_id = Path("/etc/machine-id").read_text().strip() if Path("/etc/machine-id").exists() else None
    if machine_id:
        assert machine_id not in r.text.lower()
    assert r.headers["access-control-allow-origin"] == "*"
    assert r.headers["cache-control"] == "no-store"
    pre = c.options("/api/verify/hello", headers={"Host": "10.42.0.1", "Origin": "null",
                                                  "Access-Control-Request-Method": "GET"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-private-network"] == "true"


def test_node_id_is_stable():
    diag = _diag()
    assert diag.node_id() == diag.node_id()
    assert re.fullmatch(r"STL-[0-9A-F]{4}-[0-9A-F]{4}", diag.node_id())


def test_verify_page_served(client):
    c, _ = client
    r = c.get("/verify", headers={"Host": "10.42.0.1"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")


def test_health_and_status_report_ai(client):
    c, main = client
    health = c.get("/api/health").json()
    assert health["ok"] is True and isinstance(health["llm"], bool) and health["ai"] in main.ai.ENGINES
    assert c.get("/api/status").json()["ai"] in main.ai.ENGINES


def test_report_requires_pin(client):
    c, _ = client
    r = c.get("/api/verify/report")
    assert r.status_code == 401 and "error" in r.json()
    assert c.get("/api/verify/report", headers={"X-Rescuer-Pin": "999999"}).status_code == 401


def test_report_contract(client):
    c, main = client
    started = time.monotonic()
    r = c.get("/api/verify/report", headers=PIN)
    elapsed = time.monotonic() - started
    assert r.status_code == 200
    body = r.json()
    assert elapsed < 7
    assert {"node", "version", "time", "duration_ms", "summary", "checks", "identity", "integrity",
            "hub", "ai", "hw", "power"} <= set(body)
    assert [ch["id"] for ch in body["checks"]] == CHECK_IDS
    for ch in body["checks"]:
        assert set(ch) == CHECK_KEYS
        assert ch["status"] in STATUSES
        assert isinstance(ch["detail"], str) and ch["detail"]
        assert isinstance(ch["title"], str) and isinstance(ch["group"], str)
        assert isinstance(ch["ms"], int) and ch["ms"] >= 0
    summary = body["summary"]
    assert summary["total"] == len(CHECK_IDS)
    assert sum(summary[s] for s in STATUSES) == summary["total"]
    for s in STATUSES:
        assert summary[s] == sum(1 for ch in body["checks"] if ch["status"] == s)
    expected = "fail" if summary["fail"] else "warn" if summary["warn"] else "ok"
    assert summary["verdict"] == expected
    assert set(body["identity"]) == {"node", "model", "os", "kernel", "python", "hostname", "uptime_s"}
    assert body["identity"]["node"] == body["node"]
    assert body["integrity"]["status"] == "unknown"
    assert body["hub"]["source"] == "none"
    assert body["ai"]["active"] in main.ai.ENGINES
    json.dumps(body, allow_nan=False)
    checks = _by_id(body)
    assert checks["triage"]["status"] == "ok"
    assert checks["ai_reserve"]["status"] == "ok"
    assert checks["integrity"]["status"] == "skip"
    assert checks["db"]["status"] == "ok"
    assert checks["mode"]["status"] == "ok"


def test_report_on_real_hardware_state(env):
    diag = _diag()
    _write(env / "state" / "hw.json", _hw())
    _write(env / "state" / "power.json", _power())
    report = _report()
    checks = _by_id(report)
    for cid in ("sensor", "lamp", "fan", "temp", "power", "hw_daemon"):
        assert checks[cid]["status"] == "ok", checks[cid]
    assert "i2c-4" in checks["sensor"]["detail"] and "0x68" in checks["sensor"]["detail"]
    assert checks["temp"]["value"]["max"] == 51.0
    assert "Щадящий" in checks["power"]["detail"]
    assert report["hw"]["pid"] == os.getpid() and report["power"]["profile"] == "safe"
    assert diag.CHECK_IDS == tuple(CHECK_IDS)


def test_stale_hardware_daemon_warns(env):
    _write(env / "state" / "hw.json", _hw(ts=time.time() - 120))
    checks = _by_id(_report())
    for cid in ("sensor", "lamp", "fan", "hw_daemon"):
        assert checks[cid]["status"] == "warn"
        assert "служба железа не отвечает" in checks[cid]["detail"]


def test_temperature_thresholds(env):
    _write(env / "state" / "hw.json", _hw(temp=80.0, fan_on=False))
    checks = _by_id(_report())
    assert checks["temp"]["status"] == "warn" and checks["fan"]["status"] == "warn"
    _write(env / "state" / "hw.json", _hw(temp=92.0))
    assert _by_id(_report())["temp"]["status"] == "fail"


def test_power_off_and_unclean_reboots(env):
    reason = "Питание не выдерживает локальный ИИ: плата перезагружалась 2 раз"
    _write(env / "state" / "power.json", _power("off", reason=reason, unclean_boots=2))
    check = _by_id(_report())["power"]
    assert check["status"] == "warn" and reason in check["detail"] and "2" in check["detail"]
    _write(env / "state" / "power.json", _power("normal", unclean_boots=1, recent_unclean=[time.time() - 60]))
    assert _by_id(_report())["power"]["status"] == "warn"


def test_broken_state_files_never_crash(env):
    _write(env / "state" / "hw.json", '{"ts": NaN, "temps": {"max": Infinity}, "sensor": [1, 2]')
    _write(env / "state" / "power.json", "[1, 2, 3]")
    _write(env / "state" / "mode.json", "[]")
    _write(env / "state" / "hub.json", "{broken")
    report = _report()
    json.dumps(report, allow_nan=False)
    assert [ch["id"] for ch in report["checks"]] == CHECK_IDS
    assert report["hw"] is None and report["power"] is None and report["hub"]["source"] == "none"
    _write(env / "state" / "hw.json", {"ts": float("nan"), "sensor": "oops", "temps": {"max": "hot"}})
    report = _report()
    json.dumps(report, allow_nan=False)
    assert _by_id(report)["hw_daemon"]["status"] == "warn"


def test_report_survives_broken_ai(env, monkeypatch):
    diag = _diag()

    def boom():
        raise RuntimeError("snapshot exploded")

    monkeypatch.setattr(diag.ai, "snapshot", boom)
    report = _report()
    assert [ch["id"] for ch in report["checks"]] == CHECK_IDS
    assert report["ai"]["active"] == "reserve"
    assert _by_id(report)["ai_reserve"]["status"] == "ok"


def test_hanging_and_crashing_checks_are_contained(env):
    diag = _diag()

    async def hang(ctx):
        await asyncio.sleep(30)

    async def crash(ctx):
        raise ZeroDivisionError

    async def go():
        ctx = diag._Context(None)
        started = time.monotonic()
        slow = await diag._run_check(("x", "g", "t", hang, 0.2), ctx)
        bad = await diag._run_check(("y", "g", "t", crash, 1.0), ctx)
        return slow, bad, time.monotonic() - started

    slow, bad, elapsed = asyncio.run(go())
    assert slow["status"] == "warn" and "не уложилась" in slow["detail"]
    assert bad["status"] == "warn" and "ZeroDivisionError" in bad["detail"]
    assert elapsed < 2


def _fake_systemctl(tmp_path: Path, body: str) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    exe = folder / "systemctl"
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(0o755)
    return folder


@pytest.mark.skipif(sys.platform == "win32", reason="нужен /bin/sh")
def test_services_via_systemctl(env, monkeypatch):
    diag = _diag()
    folder = _fake_systemctl(env, 'case "$2" in hostapd) echo active;; dnsmasq) echo inactive; exit 3;;'
                                  ' nginx) echo failed; exit 3;; *) echo unknown; exit 4;; esac\n')
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(diag.config, "WLAN_IFACE", "lo")
    assert asyncio.run(diag.unit_state("hostapd")) == "active"
    assert asyncio.run(diag.unit_state("dnsmasq")) == "inactive"
    checks = _by_id(_report())
    assert checks["wifi"]["status"] == "ok" and "SOS-STELLA-RESCUE" in checks["wifi"]["detail"]
    assert checks["dhcp"]["status"] == "fail" and "dnsmasq" in checks["dhcp"]["detail"]
    assert checks["web"]["status"] == "fail" and "nginx" in checks["web"]["detail"]


@pytest.mark.skipif(sys.platform == "win32", reason="нужен /bin/sh")
def test_systemctl_timeout_is_bounded(env, monkeypatch):
    diag = _diag()
    folder = _fake_systemctl(env, "sleep 5\n")
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(diag, "UNIT_TIMEOUT", 0.3)
    started = time.monotonic()
    assert asyncio.run(diag.unit_state("hostapd")) == "timeout"
    assert time.monotonic() - started < 2


def test_missing_systemctl_is_skip(env, monkeypatch):
    diag = _diag()
    monkeypatch.setattr(diag.shutil, "which", lambda name: None)
    assert asyncio.run(diag.unit_state("hostapd")) is None
    checks = _by_id(_report())
    for cid in ("wifi", "dhcp"):
        assert checks[cid]["status"] == "skip"


def test_dhcp_counts_active_leases(env, monkeypatch):
    diag = _diag()
    now = int(time.time())
    _write(env / "leases", f"{now + 600} aa:bb:cc:dd:ee:01 10.42.0.11 phone *\n"
                           f"{now - 600} aa:bb:cc:dd:ee:02 10.42.0.12 * *\n"
                           f"0 aa:bb:cc:dd:ee:03 10.42.0.13 static *\ngarbage\n")
    monkeypatch.setattr(diag.shutil, "which", lambda name: None)
    check = _by_id(_report())["dhcp"]
    assert check["status"] == "ok" and check["value"]["leases"] == 2


class FakeDns:
    def __init__(self, answer=None, rcode=0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(3)
        self.port = self.sock.getsockname()[1]
        self.answer, self.rcode, self.names = answer, rcode, []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        try:
            data, peer = self.sock.recvfrom(512)
        except OSError:
            return
        qid = struct.unpack(">H", data[:2])[0]
        end = data.index(b"\x00", 12) + 5
        question = data[12:end]
        labels, pos = [], 12
        while data[pos]:
            labels.append(data[pos + 1:pos + 1 + data[pos]].decode())
            pos += data[pos] + 1
        self.names.append(".".join(labels))
        count = 1 if self.answer else 0
        reply = struct.pack(">HHHHHH", qid ^ 0xFFFF, 0x8180, 1, 0, 0, 0)
        self.sock.sendto(reply + question, peer)
        reply = struct.pack(">HHHHHH", qid, 0x8180 | self.rcode, 1, count, 0, 0) + question
        if self.answer:
            reply += struct.pack(">HHHIH", 0xC00C, 1, 1, 60, 4) + socket.inet_aton(self.answer)
        self.sock.sendto(reply, peer)

    def close(self):
        self.sock.close()
        self.thread.join(timeout=1)


def _dns_check(env, monkeypatch, server) -> dict:
    diag = _diag()
    monkeypatch.setattr(diag.config, "PORTAL_HOST", "127.0.0.1")
    monkeypatch.setattr(diag, "DNS_PORT", server.port if server else _closed_udp_port())
    return _by_id(_report())["dns"]


def _closed_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_dns_captive_check_real_query(env, monkeypatch):
    server = FakeDns(answer="127.0.0.1")
    try:
        check = _dns_check(env, monkeypatch, server)
    finally:
        server.close()
    assert check["status"] == "ok", check
    assert server.names == ["check.stella.rescue"]
    assert check["value"]["answers"] == ["127.0.0.1"]


def test_dns_wrong_answer_and_nxdomain_fail(env, monkeypatch):
    server = FakeDns(answer="8.8.8.8")
    try:
        check = _dns_check(env, monkeypatch, server)
    finally:
        server.close()
    assert check["status"] == "fail" and "8.8.8.8" in check["detail"]
    server = FakeDns(rcode=3)
    try:
        check = _dns_check(env, monkeypatch, server)
    finally:
        server.close()
    assert check["status"] == "fail" and "не найдено" in check["detail"]


def test_dns_closed_port_fails_fast(env, monkeypatch):
    started = time.monotonic()
    check = _dns_check(env, monkeypatch, None)
    assert check["status"] == "fail"
    assert time.monotonic() - started < 3


def test_dns_skipped_off_device(env, monkeypatch):
    diag = _diag()
    monkeypatch.setattr(diag, "on_device", lambda: False)
    monkeypatch.setattr(diag.config, "PORTAL_HOST", "10.253.253.253")
    assert _by_id(_report())["dns"]["status"] == "skip"


def test_dns_packet_roundtrip():
    diag = _diag()
    packet = diag.dns_query_packet("check.stella.rescue", 0x1234)
    assert packet[:2] == b"\x12\x34" and b"\x05check\x06stella\x06rescue\x00" in packet
    answer = (struct.pack(">HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0) + packet[12:]
              + struct.pack(">HHHIH", 0xC00C, 1, 1, 60, 4) + socket.inet_aton("10.42.0.1"))
    assert diag.dns_parse_answer(answer, 0x1234) == (0, ["10.42.0.1"])
    with pytest.raises(LookupError):
        diag.dns_parse_answer(answer, 0x9999)
    with pytest.raises((ValueError, IndexError, struct.error)):
        diag.dns_parse_answer(answer[:20], 0x1234)


def test_location_set_validate_delete(client, env):
    c, _ = client
    body = {"lat": 43.2389, "lon": 76.8897, "label": "Штаб у школы №5"}
    assert c.post("/api/verify/location", json=body).status_code == 401
    r = c.post("/api/verify/location", json=body, headers=PIN)
    assert r.status_code == 200
    hub = r.json()["hub"]
    assert (hub["lat"], hub["lon"], hub["label"], hub["source"]) == (43.2389, 76.8897, "Штаб у школы №5", "file")
    saved = json.loads((env / "state" / "hub.json").read_text(encoding="utf-8"))
    assert saved["lat"] == 43.2389 and not list((env / "state").glob("*.tmp"))
    inc_hub = c.get("/api/rescuer/incidents", headers=PIN).json()["hub"]
    assert inc_hub["lat"] == 43.2389 and inc_hub["source"] == "file" and inc_hub["mode"] == "field"
    for bad in ({"lat": 91, "lon": 0}, {"lat": 0, "lon": -181}, {"lat": 0}, {"lat": "x", "lon": 1},
                {"lat": 1, "lon": 1, "label": "x" * 81}):
        r = c.post("/api/verify/location", json=bad, headers=PIN)
        assert r.status_code in (400, 422), bad
        assert r.json()["error"].startswith("Неверные данные")
    assert c.post("/api/verify/location", content=b'{"lat": NaN, "lon": 1}', headers={
        **PIN, "Content-Type": "application/json"}).status_code in (400, 422)
    assert c.delete("/api/verify/location").status_code == 401
    r = c.delete("/api/verify/location", headers=PIN)
    assert r.status_code == 200 and r.json()["hub"]["source"] == "none"
    assert not (env / "state" / "hub.json").exists()
    assert c.delete("/api/verify/location", headers=PIN).status_code == 200
    assert c.get("/api/rescuer/incidents", headers=PIN).json()["hub"]["lat"] is None


def test_hub_location_priority(env, monkeypatch):
    monkeypatch.setenv("STELLA_HUB_LAT", "43.25")
    monkeypatch.setenv("STELLA_HUB_LON", "76.95")
    _config()
    diag = _diag()
    assert diag.hub_location()["source"] == "env"
    _write(env / "state" / "hub.json", {"lat": 200, "lon": 10})
    assert diag.hub_location()["source"] == "env"
    _write(env / "state" / "hub.json", {"lat": True, "lon": 10})
    assert diag.hub_location()["source"] == "env"
    diag.save_hub(10.5, -20.25, "  Пункт\x07 сбора  ")
    hub = diag.hub_location()
    assert (hub["lat"], hub["lon"], hub["label"], hub["source"]) == (10.5, -20.25, "Пункт сбора", "file")
    diag.clear_hub()
    assert diag.hub_location()["lat"] == 43.25


def test_ai_test_endpoint(client, monkeypatch):
    c, main = client
    seen = []

    async def fake_self_test(text):
        seen.append(text)
        return {"input": text, "text": "Где вы?", "engine": "reserve", "ms": 3, "priority": "red",
                "attempts": [{"engine": "reserve", "ok": True, "error": None, "ms": 0}]}

    monkeypatch.setattr(main.ai, "self_test", fake_self_test)
    assert c.post("/api/verify/ai-test", json={"text": "тест"}).status_code == 401
    r = c.post("/api/verify/ai-test", json={"text": "  у нас пожар  "}, headers=PIN)
    assert r.status_code == 200 and r.json()["engine"] == "reserve"
    c.post("/api/verify/ai-test", headers=PIN)
    c.post("/api/verify/ai-test", json={}, headers=PIN)
    c.post("/api/verify/ai-test", json={"text": "   "}, headers=PIN)
    assert seen == ["у нас пожар", main.AI_TEST_SAMPLE, main.AI_TEST_SAMPLE, main.AI_TEST_SAMPLE]
    assert c.post("/api/verify/ai-test", json={"text": "x" * 301}, headers=PIN).status_code == 422
    main._busy.add("ai-test")
    try:
        assert c.post("/api/verify/ai-test", headers=PIN).status_code == 429
    finally:
        main._busy.discard("ai-test")


def test_ai_test_failure_is_reported(client, monkeypatch):
    c, main = client

    async def broken(text):
        raise RuntimeError("engine on fire")

    monkeypatch.setattr(main.ai, "self_test", broken)
    r = c.post("/api/verify/ai-test", headers=PIN)
    assert r.status_code == 502 and "error" in r.json()
    assert "ai-test" not in main._busy


def test_ai_test_uses_real_router(client):
    c, main = client
    r = c.post("/api/verify/ai-test", json={"text": "человек без сознания"}, headers=PIN)
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] in main.ai.ENGINES and body["text"] and body["priority"] == "red"


def test_rescuer_ai_and_probe(client, env, monkeypatch):
    c, main = client
    assert c.get("/api/rescuer/ai").status_code == 401
    assert c.post("/api/rescuer/ai/probe").status_code == 401
    body = c.get("/api/rescuer/ai", headers=PIN).json()
    assert set(body) == {"ai", "power", "hw"}
    assert body["ai"]["active"] in main.ai.ENGINES and body["power"] is None and body["hw"] is None
    _write(env / "state" / "power.json", _power("off", reason="Питание слабое"))
    _write(env / "state" / "hw.json", _hw())
    body = c.get("/api/rescuer/ai", headers=PIN).json()
    assert body["power"]["profile"] == "off" and body["hw"]["fan"]["gpio"] == "35"
    calls = []

    async def fake_probe():
        calls.append(1)
        return {**main.ai.snapshot(), "probed": True}

    monkeypatch.setattr(main.ai, "probe_now", fake_probe)
    r = c.post("/api/rescuer/ai/probe", headers=PIN)
    assert r.status_code == 200 and r.json()["ai"]["probed"] is True and calls == [1]

    async def broken_probe():
        raise OSError("network down")

    monkeypatch.setattr(main.ai, "probe_now", broken_probe)
    r = c.post("/api/rescuer/ai/probe", headers=PIN)
    assert r.status_code == 200 and "error" in r.json() and "active" in r.json()["ai"]


def test_new_pin_endpoints_share_lockout(client):
    c, _ = client
    for _ in range(5):
        c.get("/api/verify/report", headers={"X-Rescuer-Pin": "000000"})
    assert c.get("/api/rescuer/ai", headers=PIN).status_code == 429
    assert c.post("/api/verify/location", json={"lat": 1, "lon": 1}, headers=PIN).status_code == 429


def test_assistant_messages_carry_engine(client, monkeypatch):
    c, main = client

    async def fake_reply(history, triage):
        return "Спасатели в курсе. Где вы находитесь?", "cloud"

    monkeypatch.setattr(main.ai, "reply", fake_reply)
    sid = c.post("/api/session").json()["session_id"]
    c.post("/api/chat", json={"session_id": sid, "text": "сильное кровотечение у брата"})
    msgs = c.get("/api/messages", params={"session_id": sid}).json()["messages"]
    by_role = {m["role"]: m for m in msgs}
    assert by_role["assistant"]["engine"] == "cloud"
    assert by_role["assistant"]["text"].startswith("Спасатели в курсе")
    assert by_role["user"]["engine"] is None and by_role["advice"]["engine"] is None
    inc = c.get("/api/rescuer/incidents", headers=PIN).json()["incidents"][0]
    full = c.get(f"/api/rescuer/incidents/{inc['id']}/messages", headers=PIN).json()["messages"]
    assert [m["engine"] for m in full if m["role"] == "assistant"] == ["cloud"]


def test_broken_ai_reply_falls_back_to_reserve(client, monkeypatch):
    c, main = client

    async def broken(history, triage):
        raise RuntimeError("router crashed")

    async def weird(history, triage):
        return "Держитесь, помощь рядом. Где вы?", "martian"

    sid = c.post("/api/session").json()["session_id"]
    monkeypatch.setattr(main.ai, "reply", broken)
    c.post("/api/chat", json={"session_id": sid, "text": "помогите"})
    monkeypatch.setattr(main.ai, "reply", weird)
    c.post("/api/chat", json={"session_id": sid, "text": "мы на 3 этаже"})
    assistant = [m for m in c.get("/api/messages", params={"session_id": sid}).json()["messages"]
                 if m["role"] == "assistant"]
    assert [m["engine"] for m in assistant] == ["reserve", "reserve"]
    assert "Где вы" in assistant[0]["text"]


def test_real_router_reply_is_reserve_without_engines(client):
    c, main = client
    sid = c.post("/api/session").json()["session_id"]
    started = time.monotonic()
    c.post("/api/chat", json={"session_id": sid, "text": "Помогите"})
    assert time.monotonic() - started < 5
    last = c.get("/api/messages", params={"session_id": sid}).json()["messages"][-1]
    assert last["role"] == "assistant" and last["engine"] == "reserve"


def _old_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute("INSERT INTO incidents(session_id, created, updated) VALUES ('a' , 1, 1)")
    conn.execute("INSERT INTO messages(session_id, role, text, ts) VALUES ('a', 'user', 'старое', 1)")
    conn.execute("INSERT INTO messages(session_id, role, text, ts) VALUES ('a', 'assistant', 'ответ', 2)")
    conn.commit()
    conn.close()


def test_old_schema_database_migrates(tmp_path):
    from app.db import Database
    path = tmp_path / "old.db"
    _old_db(path)
    db = Database(str(path))
    cols = [r[1] for r in db._conn.execute("PRAGMA table_info(messages)").fetchall()]
    assert cols.count("engine") == 1
    assert [m["engine"] for m in db.messages("a")] == [None, None]
    db.add_message("a", "assistant", "новый", engine="local")
    assert db.last_message("a", "assistant")["engine"] == "local"
    db._conn.close()
    again = Database(str(path))
    cols = [r[1] for r in again._conn.execute("PRAGMA table_info(messages)").fetchall()]
    assert cols.count("engine") == 1 and len(again.messages("a")) == 3
    fresh = Database(str(tmp_path / "fresh.db"))
    assert "engine" in [r[1] for r in fresh._conn.execute("PRAGMA table_info(messages)").fetchall()]
    assert fresh.health()["quick_check"] == "ok"


def test_app_runs_on_old_database(env, monkeypatch):
    path = env / "legacy.db"
    _old_db(path)
    monkeypatch.setenv("STELLA_DB", str(path))
    _config()
    from app import main
    importlib.reload(main)
    c = TestClient(main.app)
    sid = c.post("/api/session").json()["session_id"]
    c.post("/api/chat", json={"session_id": sid, "text": "Помогите, дом 5"})
    last = c.get("/api/messages", params={"session_id": sid}).json()["messages"][-1]
    assert last["role"] == "assistant" and last["engine"] in main.ai.ENGINES
    check = _by_id(c.get("/api/verify/report", headers=PIN).json())["db"]
    assert check["status"] == "ok" and check["value"]["incidents"] == 2


def test_corrupt_database_is_quarantined(tmp_path):
    from app.db import Database
    path = tmp_path / "broken.db"
    path.write_bytes(b"this is definitely not sqlite " * 200)
    db = Database(str(path))
    db.add_message("s", "user", "жив")
    assert db.messages("s")[0]["text"] == "жив"
    assert list(tmp_path.glob("broken.db.corrupt-*"))


def test_unwritable_database_falls_back_to_memory(env, monkeypatch):
    blocker = env / "blocker"
    blocker.write_text("file, not a folder")
    monkeypatch.setenv("STELLA_DB", str(blocker / "stella.db"))
    _config()
    from app import main
    importlib.reload(main)
    c = TestClient(main.app)
    sid = c.post("/api/session").json()["session_id"]
    assert c.post("/api/chat", json={"session_id": sid, "text": "помогите"}).status_code == 200
    check = _by_id(c.get("/api/verify/report", headers=PIN).json())["db"]
    assert check["status"] == "fail" and "памяти" in check["detail"]


def _tree(root: Path) -> None:
    for rel, text in (("app/main.py", "print('hi')\n"), ("app/static/verify.html", "<html></html>"),
                      ("deploy/install.sh", "#!/bin/sh\n"), ("app/__pycache__/main.cpython-311.pyc", "x"),
                      ("app/cache.tmp", "x"), ("app/stella.db", "x"), ("docs/readme.md", "x")):
        _write(root / rel, text)


def test_integrity_build_and_verify(tmp_path):
    from app import config, integrity
    root = tmp_path / "stella"
    _tree(root)
    manifest = integrity.build(root)
    assert set(manifest["files"]) == {"app/main.py", "app/static/verify.html", "deploy/install.sh"}
    assert manifest["version"] == config.VERSION and manifest["created"] > 0
    ok = integrity.verify(root, manifest)
    assert ok["status"] == "ok" and ok["files"] == 3 and ok["digest"] == ok["expected"]
    assert ok["changed"] == [] and ok["missing"] == []
    (root / "app/main.py").write_text("print('hacked')\n")
    (root / "deploy/install.sh").unlink()
    (root / "app/extra.py").write_text("x = 1\n")
    bad = integrity.verify(root, manifest)
    assert bad["status"] == "changed"
    assert bad["changed"] == ["app/main.py"] and bad["missing"] == ["deploy/install.sh"]
    assert bad["added"] == ["app/extra.py"] and bad["digest"] != ok["digest"]
    unknown = integrity.verify(root, None)
    assert unknown["status"] == "unknown" and unknown["files"] == 3
    assert integrity.verify(root, {"files": "nope"})["status"] == "unknown"


def test_integrity_rejects_escaping_paths(tmp_path):
    from app import integrity
    root = tmp_path / "stella"
    _tree(root)
    (tmp_path / "secret.txt").write_text("top secret")
    manifest = integrity.build(root)
    manifest["files"]["../secret.txt"] = "0" * 64
    manifest["files"]["/etc/passwd"] = "0" * 64
    result = integrity.verify(root, manifest)
    assert result["status"] == "changed"
    assert set(result["changed"]) == {"../secret.txt", "/etc/passwd"} and result["missing"] == []


def test_integrity_cli(tmp_path):
    root = tmp_path / "stella"
    _tree(root)
    run = subprocess.run([sys.executable, "-m", "app.integrity", "build", str(root)], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    manifest = json.loads(run.stdout)
    assert set(manifest["files"]) == {"app/main.py", "app/static/verify.html", "deploy/install.sh"}
    (root / "manifest.json").write_text(run.stdout)
    check = subprocess.run([sys.executable, "-m", "app.integrity", "verify", str(root)], cwd=ROOT,
                           capture_output=True, text=True, timeout=60)
    assert check.returncode == 0 and json.loads(check.stdout)["status"] == "ok"
    (root / "app/main.py").write_text("tampered\n")
    check = subprocess.run([sys.executable, "-m", "app.integrity", "verify", str(root)], cwd=ROOT,
                           capture_output=True, text=True, timeout=60)
    assert check.returncode == 1 and json.loads(check.stdout)["changed"] == ["app/main.py"]
    usage = subprocess.run([sys.executable, "-m", "app.integrity"], cwd=ROOT, capture_output=True, text=True,
                           timeout=60)
    assert usage.returncode == 2


def test_integrity_in_report(env, monkeypatch):
    from app import integrity
    root = env / "stella"
    _tree(root)
    (env / "manifest.json").write_text(json.dumps(integrity.build(root)))
    monkeypatch.setenv("STELLA_APP_ROOT", str(root))
    _config()
    report = _report()
    assert report["integrity"]["status"] == "ok" and _by_id(report)["integrity"]["status"] == "ok"
    (root / "app/main.py").write_text("tampered\n")
    report = _report()
    assert report["integrity"]["changed"] == ["app/main.py"]
    assert _by_id(report)["integrity"]["status"] == "warn"
    (root / "deploy/install.sh").unlink()
    assert _by_id(_report())["integrity"]["status"] == "fail"
    (env / "manifest.json").write_text("{not json")
    assert _by_id(_report())["integrity"]["status"] == "warn"
