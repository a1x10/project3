import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DB_PATH = Path(os.getenv("HG_DB", ROOT / "data" / "homeguard.db"))
BLOCKLIST_DIR = Path(os.getenv("HG_BLOCKLISTS", ROOT / "data" / "blocklists"))
WEB_DIR = ROOT / "web"

# 53 требует root; для разработки по умолчанию 5353.
DNS_HOST = os.getenv("HG_DNS_HOST", "0.0.0.0")
DNS_PORT = int(os.getenv("HG_DNS_PORT", "5353"))
UPSTREAM_DNS = os.getenv("HG_UPSTREAM", "1.1.1.1")

WEB_HOST = os.getenv("HG_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("HG_WEB_PORT", "8080"))

# IP, на который DNS отправляет заблокированные домены (адрес этой машины в LAN).
# На нём должна открываться страница блокировки (порт 80 → WEB_PORT).
BLOCK_IP = os.getenv("HG_BLOCK_IP", "127.0.0.1")

SCAN_INTERVAL = int(os.getenv("HG_SCAN_INTERVAL", "30"))
ONLINE_WINDOW = int(os.getenv("HG_ONLINE_WINDOW", "150"))  # сек. с последней активности
DEMO = os.getenv("HG_DEMO") == "1"
