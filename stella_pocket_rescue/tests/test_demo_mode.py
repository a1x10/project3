"""Тестовая версия на сервере (STELLA_DEMO=1): плашка, учебные вызовы, настройки только показываются."""
import importlib
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_access import PASSWORD, TUNNEL, FakeRun, csrf_of, login, make_hash

PIN = "482193"
BOX = "box.example.org"
SERVER = Path(__file__).resolve().parent.parent / "server" / "stella-server.sh"


@pytest.fixture()
def demo_app(monkeypatch, tmp_path):
    values = {
        "STELLA_DEMO": "1", "STELLA_DB": str(tmp_path / "demo.db"), "STELLA_RESCUER_PIN": PIN,
        "STELLA_STATE_DIR": str(tmp_path), "STELLA_MODE_FILE": str(tmp_path / "mode.json"),
        "STELLA_LLM_ENABLED": "0", "STELLA_AI_MODE": "offline", "ANTHROPIC_API_KEY": "", "STELLA_MIN_INTERVAL": "0",
        "STELLA_ADMIN_HASH": make_hash(PASSWORD), "STELLA_SESSION_SECRET": "d" * 64, "STELLA_BOX_DOMAIN": BOX,
        "STELLA_HUB_LAT": "43.2389", "STELLA_HUB_LON": "76.8897", "STELLA_ADMIN_HELPER": str(tmp_path / "none"),
        "STELLA_TUNNEL_ENV": str(tmp_path / "none.env"), "STELLA_DEMO_FILE": str(tmp_path / "stand.json"),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    for name in ("STELLA_HW_STATE", "STELLA_POWER_FILE", "STELLA_HUB_FILE"):
        monkeypatch.delenv(name, raising=False)
    from app import access, admin, config, main
    for module in (config, access, admin, main):
        importlib.reload(module)
    with TestClient(main.app, base_url=f"https://{BOX}") as client:  # with: запускает lifespan и учебные вызовы
        yield client, main


def test_demo_seeds_marked_calls_once(demo_app):
    c, main = demo_app
    items = c.get("/api/rescuer/incidents", headers={**TUNNEL, "X-Rescuer-Pin": PIN}).json()["incidents"]
    assert len(items) == 4 and {i["origin"] for i in items} == {"demo"}
    assert {i["priority"] for i in items} == {"red", "yellow", "green", "unknown"}
    assert all(i["waiting_min"] >= 2 for i in items)
    red = next(i for i in items if i["priority"] == "red")
    msgs = c.get(f"/api/rescuer/incidents/{red['id']}/messages", headers={**TUNNEL, "X-Rescuer-Pin": PIN}).json()
    roles = [m["role"] for m in msgs["messages"]]
    assert roles.count("user") == 2 and "assistant" in roles and "advice" in roles
    assert main.seed_demo() == 0  # повторно не добавляет


def test_pages_carry_the_not_a_rescue_service_bar(demo_app):
    c, _ = demo_app
    for path in ("/", "/rescuer", "/admin"):
        html = c.get(path, headers=TUNNEL).text
        assert 'id="stellaDemoBar"' in html and "звоните 112" in html, path
    assert c.get("/api/status", headers=TUNNEL).json()["demo"] is True
    r = c.get("/verify", headers=TUNNEL, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/verify?demo=1"
    assert c.get("/verify?demo=1", headers=TUNNEL).status_code == 200


def test_console_from_internet_needs_only_pin_in_demo(demo_app):
    c, _ = demo_app
    assert c.get("/api/rescuer/incidents", headers={**TUNNEL, "X-Rescuer-Pin": "000000"}).status_code == 401
    assert c.get("/api/rescuer/incidents", headers={**TUNNEL, "X-Rescuer-Pin": PIN}).status_code == 200


def test_settings_only_show_in_demo(demo_app, monkeypatch):
    c, main = demo_app
    fake = FakeRun()
    monkeypatch.setattr(main.admin.subprocess, "run", fake)
    assert login(c, TUNNEL).status_code == 200
    h = {**TUNNEL, "X-Stella-CSRF": csrf_of(c, TUNNEL)}
    r = c.post("/api/admin/action", json={"action": "reboot", "confirm": True}, headers=h)
    assert r.status_code == 200 and r.json()["demo"] is True and "Тестовая версия" in r.json()["message"]
    status = c.get("/api/admin/status", headers=TUNNEL).json()
    assert status["test_version"] is True and status["helper"] == {"demo": True}
    assert status["demo"]["on"] is False  # демо для стенда осталось отдельной настройкой
    assert "журналы" in c.get("/api/admin/logs?unit=app", headers=TUNNEL).json()["text"]
    assert not [call for call in fake.calls if call[0][0] == "sudo"]  # помощник с правами root не вызывался


def test_normal_mode_has_no_bar(monkeypatch, tmp_path):
    monkeypatch.setenv("STELLA_DEMO", "0")
    monkeypatch.setenv("STELLA_DB", str(tmp_path / "x.db"))
    from app import config, main
    importlib.reload(config)
    importlib.reload(main)
    c = TestClient(main.app)
    assert "stellaDemoBar" not in c.get("/").text
    assert c.get("/api/status").json()["demo"] is False
    assert c.get("/verify", follow_redirects=False).status_code == 200


def test_server_demo_parts():
    text = SERVER.read_text(encoding="utf-8")
    assert "proxy_set_header X-Stella-Via tunnel;" in text
    assert 'sshd*) die "к адресу $BOX сейчас подключена настоящая коробка' in text
    assert "STELLA_DEMO=1" in text and "RuntimeMaxSec=1d" in text and "ProtectSystem=strict" in text
    assert "--port $HTTP_PORT" in text and 'User=$DEMO_USER' in text
    r = subprocess.run(["bash", str(SERVER), "install", "--box-domain", BOX, "--promo-domain", "example.org",
                        "--dry-run"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr  # ключ коробки больше не обязателен
    assert "proxy_set_header X-Stella-Via tunnel;" in r.stdout
