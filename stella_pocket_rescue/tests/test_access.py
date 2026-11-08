import hashlib
import importlib
import json
import socket
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PASSWORD = "abcd-efgh-jkmn-pqrs"
PIN = "123456"
BOX = "box.example.org"
PROMO = "site.example.org"
FIELD = {"X-Stella-Via": "portal", "X-Real-IP": "10.42.0.55"}
LAN = {"X-Stella-Via": "portal", "X-Real-IP": "192.168.1.20"}
PUBLIC_PORTAL = {"X-Stella-Via": "portal", "X-Real-IP": "8.8.8.8"}
TUNNEL = {"X-Stella-Via": "tunnel", "X-Real-IP": "203.0.113.9", "X-Forwarded-Proto": "https"}


def make_hash(password, iterations=10_000):
    salt = bytes(range(16))
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2:{iterations}:{salt.hex()}:{digest.hex()}"


@pytest.fixture()
def env(monkeypatch, tmp_path):
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("<h1>promo</h1>", encoding="utf-8")
    (site / "product.html").write_text("<h1>product</h1>", encoding="utf-8")
    (site / "verify.html").write_text("launcher", encoding="utf-8")
    (site / ".secret").write_text("hidden", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    helper = tmp_path / "stella-admin"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    values = {
        "STELLA_DB": str(tmp_path / "t.db"), "STELLA_RESCUER_PIN": PIN, "STELLA_MIN_INTERVAL": "0",
        "STELLA_LLM_ENABLED": "0", "STELLA_STATE_DIR": str(tmp_path / "state"),
        "STELLA_MODE_FILE": str(tmp_path / "state" / "mode.json"), "ANTHROPIC_API_KEY": "",
        "STELLA_ADMIN_HASH": make_hash(PASSWORD), "STELLA_SESSION_SECRET": "s" * 64,
        "STELLA_BOX_DOMAIN": BOX, "STELLA_PROMO_DOMAIN": PROMO, "STELLA_SITE_DIR": str(site),
        "STELLA_ADMIN_HELPER": str(helper), "STELLA_JOBS_DIR": str(jobs),
        "STELLA_DEMO_FILE": str(tmp_path / "state" / "demo.json"), "STELLA_ADMIN_HTTP_WIFI": "0",
        "STELLA_REMOTE_CHAT": "1", "STELLA_TUNNEL_ENV": str(tmp_path / "tunnel.env"),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    for name in ("STELLA_HW_STATE", "STELLA_POWER_FILE", "STELLA_HUB_FILE", "STELLA_HUB_LAT", "STELLA_HUB_LON"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def load(monkeypatch=None, **extra):
    if monkeypatch:
        for key, value in extra.items():
            monkeypatch.setenv(key, value)
    from app import access, admin, config, main
    importlib.reload(config)
    importlib.reload(access)
    importlib.reload(admin)
    importlib.reload(main)
    return main


@pytest.fixture()
def app_mod(env):
    return load()


def client(main, https=False):
    if https:
        return TestClient(main.app, base_url=f"https://{BOX}")
    return TestClient(main.app)


def login(c, headers, password=PASSWORD):
    r = c.post("/api/admin/login", json={"password": password}, headers=headers)
    return r


def csrf_of(c, headers):
    return c.get("/api/admin/session", headers=headers).json()["csrf"]


class FakeRun:
    def __init__(self, payload=None, stdout=None, returncode=0, exc=None):
        self.calls = []
        self.payload = payload if payload is not None else {"ok": True}
        self.stdout = stdout
        self.returncode = returncode
        self.exc = exc

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.exc:
            raise self.exc
        out = self.stdout if self.stdout is not None else json.dumps(self.payload) + "\n"
        return subprocess.CompletedProcess(argv, self.returncode, out, "")


# ---------------------------------------------------------------- откуда пришел запрос

@pytest.mark.parametrize("headers,expected", [
    ({}, "cli"),
    (FIELD, "field"),
    ({"X-Stella-Via": "portal-tls", "X-Real-IP": "10.42.0.77"}, "field"),
    (LAN, "lan"),
    ({"X-Stella-Via": "portal", "X-Real-IP": "169.254.3.4"}, "lan"),
    (PUBLIC_PORTAL, "remote"),
    (TUNNEL, "remote"),
    ({"X-Stella-Via": "portal-x", "X-Real-IP": "10.42.0.55"}, "remote"),
    ({"X-Stella-Via": "portal", "X-Real-IP": "not-an-ip"}, "remote"),
    ({"X-Real-IP": "10.42.0.55"}, "remote"),
])
def test_channel_matrix(app_mod, headers, expected):
    c = client(app_mod)
    assert c.get("/api/admin/session", headers=headers).json()["channel"] == expected


# ---------------------------------------------------------------- адреса и рекламный сайт

def test_box_domain_and_local_name_are_served(app_mod):
    c = client(app_mod)
    assert c.get("/", headers={**TUNNEL, "Host": BOX}, follow_redirects=False).status_code == 200
    local = socket.gethostname().lower() + ".local"
    assert c.get("/api/status", headers={**LAN, "Host": local}).status_code == 200


def test_unknown_host_from_internet_is_rejected_not_redirected(app_mod):
    c = client(app_mod)
    r = c.get("/", headers={**TUNNEL, "Host": "evil.example.com"}, follow_redirects=False)
    assert r.status_code == 421
    r = c.get("/", headers={**FIELD, "Host": "captive.apple.com"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "http://10.42.0.1/"


def test_promo_domain_serves_site_offline(app_mod):
    c = client(app_mod)
    for host in (PROMO, "www." + PROMO):
        r = c.get("/", headers={**FIELD, "Host": host})
        assert r.status_code == 200 and "promo" in r.text
    r = c.get("/product.html", headers={**FIELD, "Host": PROMO})
    assert r.status_code == 200 and "product" in r.text
    for bad in ("/verify.html", "/.secret", "/../outside.txt", "/%2e%2e/outside.txt", "/nope.html"):
        assert c.get(bad, headers={**FIELD, "Host": PROMO}).status_code == 404, bad
    assert c.post("/", headers={**FIELD, "Host": PROMO}).status_code == 405
    # API коробки под доменом сайта не открывается
    assert c.get("/api/rescuer/incidents", headers={**FIELD, "Host": PROMO, "X-Rescuer-Pin": PIN}).status_code == 404


def test_site_path_on_portal(app_mod):
    c = client(app_mod)
    r = c.get("/site", headers=FIELD, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/site/"
    assert "promo" in c.get("/site/", headers=FIELD).text
    assert c.get("/site/verify.html", headers=FIELD).status_code == 404
    assert c.get("/site/../config.py", headers=FIELD).status_code == 404


def test_admin_page_has_protective_headers(app_mod):
    r = client(app_mod).get("/admin", headers=FIELD)
    assert r.status_code == 200
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_remote_responses_are_not_indexed(app_mod):
    r = client(app_mod).get("/api/status", headers={**TUNNEL, "Host": BOX})
    assert r.headers["x-robots-tag"].startswith("noindex")
    assert "x-robots-tag" not in client(app_mod).get("/api/status", headers=FIELD).headers


# ---------------------------------------------------------------- вход администратора

def test_login_policy_by_channel(env, monkeypatch):
    main = load()
    c = client(main)
    r = login(c, FIELD)
    assert r.status_code == 403 and "подслушать" in r.json()["error"]
    assert login(c, {"X-Stella-Via": "tunnel", "X-Real-IP": "203.0.113.9"}).status_code == 403  # без HTTPS
    assert login(c, LAN).status_code == 200
    assert login(client(main, https=True), TUNNEL).status_code == 200
    main = load(monkeypatch, STELLA_ADMIN_HTTP_WIFI="1")
    assert login(client(main), FIELD).status_code == 200


def test_login_without_configured_password(env, monkeypatch):
    main = load(monkeypatch, STELLA_ADMIN_HASH="")
    r = login(client(main), LAN)
    assert r.status_code == 503 and "stella admin password new" in r.json()["error"]


def test_wrong_password_is_rate_limited_per_address(app_mod):
    c = client(app_mod)
    for _ in range(5):
        assert login(c, LAN, "wrong").status_code == 401
    assert login(c, LAN).status_code == 429
    assert login(c, {"X-Stella-Via": "portal", "X-Real-IP": "192.168.1.21"}).status_code == 200


def test_cookie_flags_follow_https(app_mod):
    r = login(client(app_mod, https=True), TUNNEL)
    cookie = r.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    r = login(client(app_mod), LAN)
    cookie = r.headers["set-cookie"].lower()
    assert "secure" not in cookie and "httponly" in cookie


def test_http_cookie_does_not_work_over_the_internet(app_mod):
    c = client(app_mod)
    assert login(c, LAN).status_code == 200
    value = c.cookies.get("stella_admin")
    assert c.get("/api/admin/session", headers=LAN).json()["logged_in"] is True
    r = client(app_mod).get("/api/admin/session", headers={**TUNNEL, "Cookie": f"stella_admin={value}"})
    assert r.json()["logged_in"] is False


def test_tampered_expired_and_rotated_cookies_are_rejected(env, monkeypatch):
    main = load()
    c = client(main)
    assert login(c, LAN).status_code == 200
    value = c.cookies.get("stella_admin")
    parts = value.split(".")
    forged = ".".join([parts[0], str(int(parts[1]) + 99999)] + parts[2:])
    for bad in (forged, value[:-1] + ("0" if value[-1] != "0" else "1"), "v1.1.h.x.y", "garbage"):
        r = client(main).get("/api/admin/session", headers={**LAN, "Cookie": f"stella_admin={bad}"})
        assert r.json()["logged_in"] is False, bad
    from app import access
    assert access.read_session(type("R", (), {"cookies": {"stella_admin": value}, "headers": LAN})(),
                               now=time.time() + 13 * 3600) is None
    main = load(monkeypatch, STELLA_ADMIN_HASH=make_hash("new-pass-word-1234"))
    r = client(main).get("/api/admin/session", headers={**LAN, "Cookie": f"stella_admin={value}"})
    assert r.json()["logged_in"] is False


def test_logout_clears_cookie(app_mod):
    c = client(app_mod)
    login(c, LAN)
    r = c.post("/api/admin/logout", headers=LAN)
    assert r.status_code == 200 and "stella_admin=" in r.headers["set-cookie"]
    assert c.get("/api/admin/session", headers=LAN).json()["logged_in"] is False


# ---------------------------------------------------------------- CSRF и действия

def test_writes_need_csrf_and_same_origin(app_mod):
    c = client(app_mod)
    login(c, LAN)
    token = csrf_of(c, LAN)
    assert c.post("/api/admin/demo", json={"on": False}, headers=LAN).status_code == 403
    assert c.post("/api/admin/demo", json={"on": False}, headers={**LAN, "X-Stella-CSRF": "x" * 40}).status_code == 403
    good = {**LAN, "X-Stella-CSRF": token}
    assert c.post("/api/admin/demo", json={"on": False},
                  headers={**good, "Origin": "http://evil.example"}).status_code == 403
    assert c.post("/api/admin/demo", json={"on": False},
                  headers={**good, "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.post("/api/admin/demo", json={"on": False},
                  headers={**good, "Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_cross_site_login_is_refused(app_mod):
    r = client(app_mod).post("/api/admin/login", json={"password": PASSWORD},
                             headers={**LAN, "Origin": "http://evil.example"})
    assert r.status_code == 403


def test_admin_api_needs_login(app_mod):
    c = client(app_mod)
    for method, path in (("get", "/api/admin/status"), ("get", "/api/admin/logs"),
                         ("get", "/api/admin/jobs/0123456789abcdef"), ("post", "/api/admin/action")):
        r = getattr(c, method)(path, headers=LAN)
        assert r.status_code == 401 and r.json()["admin"] is True, path


def test_actions_go_through_sudo_with_secrets_on_stdin(app_mod, monkeypatch):
    fake = FakeRun({"ok": True, "job": "0123456789abcdef"})
    monkeypatch.setattr(app_mod.admin.subprocess, "run", fake)
    c = client(app_mod)
    login(c, LAN)
    r = c.post("/api/admin/action", json={"action": "pin.set", "params": {"pin": "482193"}},
               headers={**LAN, "X-Stella-CSRF": csrf_of(c, LAN)})
    assert r.status_code == 200 and r.json() == {"job": "0123456789abcdef"}
    argv, kw = fake.calls[-1]
    assert argv[:3] == ["sudo", "-n", app_mod.config.ADMIN_HELPER] and argv[3] == "pin.set" and len(argv) == 4
    assert "482193" not in " ".join(argv) and json.loads(kw["input"]) == {"pin": "482193"}


def test_dangerous_and_forbidden_actions(app_mod, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(app_mod.admin.subprocess, "run", fake)
    c = client(app_mod)
    login(c, LAN)
    h = {**LAN, "X-Stella-CSRF": csrf_of(c, LAN)}
    for name in ("ai.key", "info", "logs", "remote.on", "remote.pair", "domains.set", "admin.password", "__job"):
        r = c.post("/api/admin/action", json={"action": name, "params": {"key": "sk-ant-x"}}, headers=h)
        assert r.status_code == 400, name
    assert c.post("/api/admin/action", json={"action": "reboot"}, headers=h).status_code == 409
    assert c.post("/api/admin/action", json={"action": "reboot", "confirm": True}, headers=h).status_code == 200
    assert not any(call[0][3] in ("ai.key", "info") for call in fake.calls[:-1])


@pytest.mark.parametrize("fake,code", [
    (FakeRun(stdout="not json"), 502),
    (FakeRun({"ok": False, "error": "PIN: от 4 до 12 цифр"}), 400),
    (FakeRun(exc=subprocess.TimeoutExpired("sudo", 1)), 504),
    (FakeRun(exc=FileNotFoundError("sudo")), 503),
])
def test_helper_failures_are_explained(app_mod, monkeypatch, fake, code):
    monkeypatch.setattr(app_mod.admin.subprocess, "run", fake)
    c = client(app_mod)
    login(c, LAN)
    r = c.post("/api/admin/action", json={"action": "pin.set", "params": {"pin": "1"}},
               headers={**LAN, "X-Stella-CSRF": csrf_of(c, LAN)})
    assert r.status_code == code and r.json()["error"]


def test_missing_helper(env, monkeypatch):
    main = load(monkeypatch, STELLA_ADMIN_HELPER=str(env / "absent"))
    c = client(main)
    login(c, LAN)
    r = c.post("/api/admin/action", json={"action": "restart"}, headers={**LAN, "X-Stella-CSRF": csrf_of(c, LAN)})
    assert r.status_code == 503 and "sudo stella update" in r.json()["error"]


def test_status_never_contains_api_key(env, monkeypatch):
    main = load(monkeypatch, ANTHROPIC_API_KEY="sk-ant-api03-very-secret-value-123456")
    monkeypatch.setattr(main.admin.subprocess, "run", FakeRun({"ok": True, "tunnel": {"active": "inactive"}}))
    c = client(main)
    login(c, LAN)
    r = c.get("/api/admin/status", headers=LAN)
    assert r.status_code == 200
    body = r.json()
    assert body["settings"]["key_set"] is True and "sk-ant" not in r.text
    assert body["remote"]["box_domain"] == BOX and body["helper"]["tunnel"]["active"] == "inactive"


def test_jobs_are_read_from_files(app_mod):
    jobs = app_mod.config.JOBS_DIR
    (jobs / "0123456789abcdef.state").write_text(json.dumps({"state": "ok", "rc": 0}), encoding="utf-8")
    (jobs / "0123456789abcdef.log").write_text("x" * 7000 + "END", encoding="utf-8")
    c = client(app_mod)
    login(c, LAN)
    r = c.get("/api/admin/jobs/0123456789abcdef", headers=LAN)
    assert r.json()["state"] == "ok" and r.json()["log"].endswith("END") and len(r.json()["log"]) <= 6000
    assert c.get("/api/admin/jobs/../../etc", headers=LAN).status_code == 404
    assert c.get("/api/admin/jobs/fedcba9876543210", headers=LAN).status_code == 404


def test_logs_unit_allowlist(app_mod, monkeypatch):
    fake = FakeRun({"ok": True, "text": "lines"})
    monkeypatch.setattr(app_mod.admin.subprocess, "run", fake)
    c = client(app_mod)
    login(c, LAN)
    assert c.get("/api/admin/logs?unit=sshd", headers=LAN).status_code == 400
    assert c.get("/api/admin/logs?unit=tunnel", headers=LAN).json()["text"] == "lines"
    assert json.loads(fake.calls[-1][1]["input"]) == {"unit": "tunnel"}


# ---------------------------------------------------------------- консоль спасателя из интернета

def test_remote_console_needs_admin_then_pin(app_mod):
    c = client(app_mod, https=True)
    r = c.get("/api/rescuer/incidents", headers={**TUNNEL, "X-Rescuer-Pin": PIN})
    assert r.status_code == 403 and r.json()["admin"] is True
    assert login(c, TUNNEL).status_code == 200
    assert c.get("/api/rescuer/incidents", headers={**TUNNEL, "X-Rescuer-Pin": "000000"}).status_code == 401
    assert c.get("/api/rescuer/incidents", headers={**TUNNEL, "X-Rescuer-Pin": PIN}).status_code == 200


def test_field_console_still_pin_only(app_mod):
    c = client(app_mod)
    assert c.get("/api/rescuer/incidents", headers={**FIELD, "X-Rescuer-Pin": PIN}).status_code == 200
    assert c.get("/api/rescuer/incidents", headers={"X-Rescuer-Pin": PIN}).status_code == 200  # команда stella


def test_remote_attempts_without_login_do_not_lock_out_the_field(app_mod):
    c = client(app_mod)
    for _ in range(10):
        assert c.get("/api/rescuer/incidents", headers={**TUNNEL, "X-Rescuer-Pin": "0"}).status_code == 403
    assert c.get("/api/rescuer/incidents", headers={**FIELD, "X-Rescuer-Pin": PIN}).status_code == 200


# ---------------------------------------------------------------- чат из интернета и демо

def test_chat_origin_is_recorded(app_mod):
    c = client(app_mod)
    remote = c.post("/api/session", headers={**TUNNEL, "Host": BOX}).json()["session_id"]
    field = c.post("/api/session", headers=FIELD).json()["session_id"]
    assert app_mod.db.get_incident(remote)["origin"] == "remote"
    assert app_mod.db.get_incident(field)["origin"] == "field"


def test_remote_chat_can_be_switched_off(env, monkeypatch):
    main = load(monkeypatch, STELLA_REMOTE_CHAT="0")
    c = client(main)
    assert c.post("/api/session", headers={**TUNNEL, "Host": BOX}).status_code == 403
    sid = c.post("/api/session", headers=FIELD).json()["session_id"]
    assert c.post("/api/chat", json={"session_id": sid, "text": "помогите"}, headers={**TUNNEL, "Host": BOX}).status_code == 403
    assert c.post("/api/chat", json={"session_id": sid, "text": "помогите"}, headers=FIELD).status_code == 200


def test_demo_mode_redirects_captive_portal_to_site(app_mod):
    c = client(app_mod)
    login(c, LAN)
    h = {**LAN, "X-Stella-CSRF": csrf_of(c, LAN)}
    assert c.get("/generate_204", headers=FIELD, follow_redirects=False).headers["location"] == "http://10.42.0.1/"
    r = c.post("/api/admin/demo", json={"on": True, "hours": 1}, headers=h)
    assert r.status_code == 200 and r.json()["on"] is True
    assert c.get("/generate_204", headers=FIELD, follow_redirects=False).headers["location"] == "http://10.42.0.1/site/"
    assert c.get("/", headers=FIELD).status_code == 200  # чат по-прежнему открывается
    app_mod.mode.write("emergency", "manual", None)
    assert c.get("/hotspot-detect.html", headers=FIELD, follow_redirects=False).headers["location"] == "http://10.42.0.1/"
    assert c.post("/api/admin/demo", json={"on": True}, headers=h).status_code == 409
    app_mod.mode.write("standby", None, None)
    assert c.post("/api/admin/demo", json={"on": True, "hours": 13}, headers=h).status_code == 422
    c.post("/api/admin/demo", json={"on": False}, headers=h)
    assert c.get("/generate_204", headers=FIELD, follow_redirects=False).headers["location"] == "http://10.42.0.1/"


def test_demo_file_is_clamped_and_expires(app_mod):
    path = Path(app_mod.config.DEMO_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"until": time.time() + 10 * 86400}), encoding="utf-8")
    state = app_mod.admin.demo_state()
    assert state["on"] and state["until"] <= time.time() + 12 * 3600 + 1
    path.write_text(json.dumps({"until": time.time() - 1}), encoding="utf-8")
    assert app_mod.admin.demo_state()["on"] is False
    path.write_text("{broken", encoding="utf-8")
    assert app_mod.admin.demo_state()["on"] is False


def test_limiter_memory_is_bounded():
    from app import access
    lim = access.Limiter(3, 60, max_keys=10)
    for i in range(100):
        lim.fail(f"k{i}")
    assert len(lim._hits) == 10
    for _ in range(3):
        lim.fail("x")
    assert lim.blocked("x") and not lim.blocked("y")
    assert not lim.blocked("x", now=time.time() + 61)


def test_helper_info_is_cached_between_status_polls(app_mod, monkeypatch):
    fake = FakeRun({"ok": True, "tunnel": {"active": "active"}})
    monkeypatch.setattr(app_mod.admin.subprocess, "run", fake)
    app_mod.admin._helper_info.update(ts=0.0, data=None)
    c = client(app_mod)
    login(c, LAN)
    for _ in range(3):
        assert c.get("/api/admin/status", headers=LAN).status_code == 200
    info_calls = [call for call in fake.calls if call[0][-1] == "info"]
    assert len(info_calls) == 1
    c.post("/api/admin/action", json={"action": "restart"}, headers={**LAN, "X-Stella-CSRF": csrf_of(c, LAN)})
    c.get("/api/admin/status", headers=LAN)
    assert len([call for call in fake.calls if call[0][-1] == "info"]) == 2
