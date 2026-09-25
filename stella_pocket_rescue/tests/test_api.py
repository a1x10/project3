import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STELLA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("STELLA_RESCUER_PIN", "123456")
    monkeypatch.setenv("STELLA_MIN_INTERVAL", "0")
    monkeypatch.setenv("STELLA_LLM_ENABLED", "0")   # проверяем резервный диспетчер
    from app import config, main
    importlib.reload(config)
    importlib.reload(main)
    return TestClient(main.app), main


def new_session(c):
    return c.post("/api/session").json()["session_id"]


def test_captive_portal_redirects_foreign_hosts(client):
    c, _ = client
    for host in ("connectivitycheck.gstatic.com", "captive.apple.com", "www.msftconnecttest.com"):
        r = c.get("/generate_204", headers={"Host": host}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == "http://10.42.0.1/"


def test_portal_page_served(client):
    c, _ = client
    r = c.get("/", headers={"Host": "10.42.0.1"})
    assert r.status_code == 200 and "экстренной" in r.text


def test_chat_flow_and_triage(client):
    c, _ = client
    sid = new_session(c)
    assert c.post("/api/chat", json={"session_id": sid, "text": "Помогите"}).status_code == 200
    msgs = c.get("/api/messages", params={"session_id": sid}).json()["messages"]
    assert msgs[-1]["role"] == "assistant" and "Где вы" in msgs[-1]["text"]

    c.post("/api/chat", json={"session_id": sid, "text": "ул. Ленина 5, подъезд 2. Брата придавило, сильное кровотечение"})
    roles = [m["role"] for m in c.get("/api/messages", params={"session_id": sid}).json()["messages"]]
    assert "advice" in roles

    pin = {"X-Rescuer-Pin": "123456"}
    data = c.get("/api/rescuer/incidents", headers=pin).json()
    inc = data["incidents"][0]
    assert inc["priority"] == "red" and data["counts"]["red"] == 1

    c.patch(f"/api/rescuer/incidents/{inc['id']}", json={"status": "assigned"}, headers=pin)
    c.post(f"/api/rescuer/incidents/{inc['id']}/reply", json={"text": "Мы в пути"}, headers=pin)
    msgs = c.get("/api/messages", params={"session_id": sid}).json()["messages"]
    assert msgs[-1] == {**msgs[-1], "role": "rescuer", "text": "Мы в пути"}


def test_red_sorted_before_green(client):
    c, _ = client
    for text in ("Мы в порядке, не ранены", "человек без сознания, дом 3"):
        c.post("/api/chat", json={"session_id": new_session(c), "text": text})
    items = c.get("/api/rescuer/incidents", headers={"X-Rescuer-Pin": "123456"}).json()["incidents"]
    assert [i["priority"] for i in items] == ["red", "green"]


def test_geolocation_stored(client):
    c, _ = client
    sid = new_session(c)
    c.post("/api/chat", json={"session_id": sid, "text": "я здесь", "lat": 43.1, "lon": 76.9, "accuracy": 12})
    inc = c.get("/api/rescuer/incidents", headers={"X-Rescuer-Pin": "123456"}).json()["incidents"][0]
    assert (inc["lat"], inc["lon"]) == (43.1, 76.9)


def test_pin_required_and_bruteforce_locked(client):
    c, _ = client
    assert c.get("/api/rescuer/incidents").status_code == 401
    for _ in range(5):
        c.get("/api/rescuer/incidents", headers={"X-Rescuer-Pin": "000000"})
    r = c.get("/api/rescuer/incidents", headers={"X-Rescuer-Pin": "123456"})
    assert r.status_code == 429


def test_broadcast_visible_to_victims(client):
    c, _ = client
    c.post("/api/rescuer/broadcast", json={"text": "Пункт сбора — стадион"}, headers={"X-Rescuer-Pin": "123456"})
    sid = new_session(c)
    b = c.get("/api/messages", params={"session_id": sid}).json()["broadcasts"]
    assert b[0]["text"] == "Пункт сбора — стадион"


def test_bad_session_rejected(client):
    c, _ = client
    assert c.post("/api/chat", json={"session_id": "../x", "text": "hi"}).status_code == 400


def test_session_stores_device_info(client):
    c, _ = client
    sid = c.post("/api/session", json={"device": {
        "ua": "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36",
        "platform": "Linux armv8l", "lang": "ru-RU", "screen": "1080x2400",
        "cores": 8, "memory_gb": 6, "battery": 0.42, "charging": False,
        "net_type": "4g", "downlink": 5.5,
    }}).json()["session_id"]
    inc = c.get("/api/rescuer/incidents", headers={"X-Rescuer-Pin": "123456"}).json()["incidents"][0]
    assert inc["device"] == "Samsung SM-G991B"
    assert inc["battery"] == 0.42 and inc["charging"] is False
    assert inc["device_info"]["cores"] == 8 and inc["device_info"]["tz"] is None


def test_heartbeat_updates_battery_and_location(client):
    c, _ = client
    sid = c.post("/api/session", json={"device": {"ua": "iPhone"}}).json()["session_id"]
    c.post(f"/api/heartbeat?session_id={sid}", json={"battery": 0.15, "charging": False,
                                                     "lat": 43.24, "lon": 76.89, "accuracy": 8})
    inc = c.get("/api/rescuer/incidents", headers={"X-Rescuer-Pin": "123456"}).json()["incidents"][0]
    assert inc["device"] == "iPhone"
    assert inc["battery"] == 0.15 and (inc["lat"], inc["lon"]) == (43.24, 76.89)
    assert inc["online"] is True


def test_connection_appears_before_any_message(client):
    c, _ = client
    c.post("/api/session", json={"device": {"ua": "Pixel 7"}})
    data = c.get("/api/rescuer/incidents", headers={"X-Rescuer-Pin": "123456"}).json()
    assert data["incidents"][0]["device"] == "Pixel 7"      # видно подключение до чата
    assert data["incidents"][0]["priority"] == "unknown"
    assert "server" in data and "connections" not in data


def test_connections_endpoint_requires_pin(client):
    c, _ = client
    assert c.get("/api/rescuer/connections").status_code == 401
    body = c.get("/api/rescuer/connections", headers={"X-Rescuer-Pin": "123456"}).json()
    assert "connections" in body and body["hub"]["ssid"] == "SOS-STELLA-RESCUE"


def test_llm_reply_used_when_available(client, monkeypatch):
    c, main = client

    async def fake_generate(history, triage):
        assert history[-1]["text"] == "где помощь?"
        return "Спасатели уже знают о вас. Где вы находитесь?"

    monkeypatch.setattr(main.llm, "generate", fake_generate)
    sid = new_session(c)
    c.post("/api/chat", json={"session_id": sid, "text": "где помощь?"})
    msgs = c.get("/api/messages", params={"session_id": sid}).json()["messages"]
    assert msgs[-1]["text"].startswith("Спасатели уже знают")


def test_console_reachable_by_board_ip(client):
    # спасатель открывает консоль по кабелю: http://192.168.1.50/rescuer
    c, _ = client
    r = c.get("/rescuer", headers={"Host": "192.168.1.50"}, follow_redirects=False)
    assert r.status_code == 200


def test_emergency_mode_switch(client, monkeypatch, tmp_path):
    monkeypatch.setenv("STELLA_MODE_FILE", str(tmp_path / "mode.json"))
    c, _ = client
    assert c.get("/api/status").json()["mode"] == "standby"
    pin = {"X-Rescuer-Pin": "123456"}
    assert c.post("/api/rescuer/mode", json={"mode": "emergency", "source": "drill"}).status_code == 401
    r = c.post("/api/rescuer/mode", json={"mode": "emergency", "source": "drill"}, headers=pin)
    assert r.json()["mode"] == "emergency"
    assert c.get("/api/status").json()["source"] == "drill"
    sid = c.post("/api/session").json()["session_id"]
    b = c.get("/api/messages", params={"session_id": sid}).json()["broadcasts"]
    assert "УЧЕБНАЯ ТРЕВОГА" in b[-1]["text"]
    c.post("/api/rescuer/mode", json={"mode": "standby"}, headers=pin)
    assert c.get("/api/status").json()["mode"] == "standby"
