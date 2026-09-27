import os
from pathlib import Path


def _float(name: str, default: str) -> float | None:
    value = os.getenv(name, default)
    try:
        return float(value) if value not in ("", None) else None
    except ValueError:
        return None


def _num(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return min(max(value, low), high)


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = os.getenv(name, default).strip().lower()
    return value if value in allowed else default


VERSION = "2.0.0"
APP_ROOT = Path(os.getenv("STELLA_APP_ROOT", str(Path(__file__).resolve().parent.parent)))

DB_PATH = os.getenv("STELLA_DB", "stella.db")
STATE_DIR = Path(os.getenv("STELLA_STATE_DIR", "/var/lib/stella"))
HW_STATE_FILE = Path(os.getenv("STELLA_HW_STATE", str(STATE_DIR / "hw.json")))
POWER_FILE = Path(os.getenv("STELLA_POWER_FILE", str(STATE_DIR / "power.json")))
HUB_FILE = Path(os.getenv("STELLA_HUB_FILE", str(STATE_DIR / "hub.json")))
MANIFEST_FILE = Path(os.getenv("STELLA_MANIFEST", str(APP_ROOT / "manifest.json")))

LLM_URL = os.getenv("STELLA_LLM_URL", "http://127.0.0.1:8081/v1/chat/completions")
LLM_TIMEOUT = _num("STELLA_LLM_TIMEOUT", 90, 5, 600)
LLM_MAX_TOKENS = int(_num("STELLA_LLM_MAX_TOKENS", 120, 16, 1024))
LLM_CONCURRENCY = int(_num("STELLA_LLM_CONCURRENCY", 1, 1, 4))
LLM_QUEUE_LIMIT = int(_num("STELLA_LLM_QUEUE_LIMIT", 3, 0, 50))
LLM_ENABLED = os.getenv("STELLA_LLM_ENABLED", "1") == "1"

AI_MODE = _choice("STELLA_AI_MODE", "auto", ("auto", "cloud", "local", "offline"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
CLOUD_MODEL = os.getenv("STELLA_CLOUD_MODEL", "claude-opus-5").strip() or "claude-opus-5"
CLOUD_EFFORT = _choice("STELLA_CLOUD_EFFORT", "low", ("low", "medium", "high"))
CLOUD_TIMEOUT = _num("STELLA_CLOUD_TIMEOUT", 25, 3, 120)
CLOUD_MAX_TOKENS = int(_num("STELLA_CLOUD_MAX_TOKENS", 2048, 256, 16000))
CLOUD_HOST = os.getenv("STELLA_CLOUD_HOST", "api.anthropic.com").strip() or "api.anthropic.com"
CLOUD_CONCURRENCY = int(_num("STELLA_CLOUD_CONCURRENCY", 4, 1, 16))
REPLY_DEADLINE = _num("STELLA_REPLY_DEADLINE", 75, 10, 600)
PROBE_INTERVAL = _num("STELLA_PROBE_INTERVAL", 20, 5, 600)

RESCUER_PIN = os.getenv("STELLA_RESCUER_PIN", "0000")
PORTAL_HOST = os.getenv("STELLA_PORTAL_HOST", "10.42.0.1")
PORTAL_URL = f"http://{PORTAL_HOST}/"

HUB_LAT = _float("STELLA_HUB_LAT", "")
HUB_LON = _float("STELLA_HUB_LON", "")

MAX_MESSAGE_LEN = 1000
MIN_SECONDS_BETWEEN_MESSAGES = float(os.getenv("STELLA_MIN_INTERVAL", "1.5"))

SSID = os.getenv("STELLA_SSID", "SOS-STELLA-RESCUE")
HUB_MODE = os.getenv("STELLA_HUB_MODE", "field")
WLAN_IFACE = os.getenv("STELLA_WLAN", "wlan0")
DHCP_LEASES = os.getenv("STELLA_LEASES", "/var/lib/misc/stella.leases")
RSSI_REF_DBM = float(os.getenv("STELLA_RSSI_REF", "-40"))
RSSI_PATH_LOSS = float(os.getenv("STELLA_RSSI_N", "3.0"))
ONLINE_WINDOW = float(os.getenv("STELLA_ONLINE_WINDOW", "20"))
