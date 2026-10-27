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
