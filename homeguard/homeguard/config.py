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

# VPN
VPN_DIR = Path(os.getenv("HG_VPN_DIR", ROOT / "data" / "vpn"))
VPN_IFACE = "hgvpn"
LAN_IFACE = os.getenv("HG_LAN_IFACE", "")  # по умолчанию — интерфейс маршрута по умолчанию
# Сухой прогон: команды не выполняются, а только запоминаются (для разработки без root/wg).
VPN_DRYRUN = os.getenv("HG_VPN_DRYRUN") == "1" or DEMO

# Порт REST API Bravia (у реальных ТВ всегда 80; менять нужно только для тестов)
BRAVIA_PORT = int(os.getenv("HG_BRAVIA_PORT", "80"))

# Xiaomi (miIO/MIoT)
MIIO_PORT = int(os.getenv("HG_MIIO_PORT", "54321"))
MIOT_DIR = Path(os.getenv("HG_MIOT_DIR", ROOT / "data" / "miot"))  # кэш описаний моделей

# Вход через Telegram-бота. HG_AUTH=0 отключает проверку (только для тестов/разработки).
AUTH = os.getenv("HG_AUTH", "1") != "0"
TG_TOKEN = os.getenv("HG_TG_TOKEN", "")  # можно не задавать — токен вводится при первом запуске в панели
TG_API = os.getenv("HG_TG_API", "https://api.telegram.org")
SESSION_DAYS = 90

# Антивирус: ключи можно задать здесь или в панели
GSB_KEY = os.getenv("HG_GSB_KEY", "")
VT_KEY = os.getenv("HG_VT_KEY", "")
GSB_URL = os.getenv("HG_GSB_URL", "https://safebrowsing.googleapis.com/v4/threatMatches:find")
VT_URL = os.getenv("HG_VT_URL", "https://www.virustotal.com/api/v3")
AV_MAX_FILE = 32 * 1024 * 1024
