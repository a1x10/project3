"""Демо-данные, чтобы посмотреть панель без реальной сети (HG_DEMO=1)."""
import random
import time

from . import db

DEVICES = [
    ("aa:bb:cc:00:00:01", "192.168.3.10", "Комп", None, "computer", True, 0),
    ("aa:bb:cc:00:00:02", "192.168.3.21", "Xiaomi-15T", "Xiaomi", "phone", False, 4000),
    ("aa:bb:cc:00:00:03", "192.168.3.22", "MacBook-Air-Evelina", "Apple", "computer", False, 9000),
    ("aa:bb:cc:00:00:04", "192.168.3.23", "yandexmicro-LR00000000000032550", "Yandex", "speaker", False, 30),
    ("aa:bb:cc:00:00:05", "192.168.3.1", "Internet Gateway Device", None, "router", False, 10),
    ("aa:bb:cc:00:00:06", "192.168.3.24", "DESKTOP-0FOTDLT", None, "computer", False, 86400),
    ("aa:bb:cc:00:00:07", "192.168.3.30", "BRAVIA-KD-55X80", "Sony", "tv", False, 20),
    ("aa:bb:cc:00:00:08", "192.168.3.40", "192-168-3-40", None, "unknown", False, 15),
    ("aa:bb:cc:00:00:09", "192.168.3.41", "xiaomi-washer-v5", "Xiaomi", "appliance", False, 60),
]
DOMAINS = ["youtube.com", "googlevideo.com", "vk.com", "yandex.ru", "ya.ru", "github.com", "telegram.org",
           "wikipedia.org", "play.google.com", "api.xiaomi.com", "ntp.org", "netflix.com"]
BAD = [("doubleclick.net", "ads"), ("google-analytics.com", "trackers"), ("hotjar.com", "trackers"),
       ("taboola.com", "ads"), ("blocked-malware.test", "malware"), ("blocked-phishing.test", "phishing")]


def seed() -> None:
    if db.query("SELECT 1 FROM devices LIMIT 1"):
        return
    now = time.time()
    for mac, ip, host, vendor, dtype, me, ago in DEVICES:
        db.upsert_device(mac, ip, host, vendor, dtype, is_self=me, seen=now - ago)
    rnd = random.Random(1)
    conn = db.connect()
    rows = []
    for i in range(400):
        ip = rnd.choice(DEVICES)[1]
        ts = now - rnd.randint(0, 6 * 3600)
        if rnd.random() < 0.18:
            d, reason = rnd.choice(BAD)
            rows.append((ts, ip, d, "A", "blocked", reason))
        else:
            rows.append((ts, ip, rnd.choice(DOMAINS), "A", "allowed", None))
    with db._lock:
        conn.executemany("INSERT INTO queries (ts, client_ip, domain, qtype, action, reason) VALUES (?,?,?,?,?,?)", rows)
        conn.commit()
