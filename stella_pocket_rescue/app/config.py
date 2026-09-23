"""Настройки берутся из переменных окружения (на устройстве — /etc/stella/stella.env)."""
import os


def _float(name: str, default: str) -> float | None:
    value = os.getenv(name, default)
    return float(value) if value not in ("", None) else None


DB_PATH = os.getenv("STELLA_DB", "stella.db")

# llama.cpp llama-server с OpenAI-совместимым API
LLM_URL = os.getenv("STELLA_LLM_URL", "http://127.0.0.1:8081/v1/chat/completions")
LLM_TIMEOUT = float(os.getenv("STELLA_LLM_TIMEOUT", "90"))
LLM_MAX_TOKENS = int(os.getenv("STELLA_LLM_MAX_TOKENS", "120"))
# Сколько запросов одновременно отдаём модели и сколько держим в очереди.
# Остальным пострадавшим сразу отвечает детерминированный диспетчер.
LLM_CONCURRENCY = int(os.getenv("STELLA_LLM_CONCURRENCY", "1"))
LLM_QUEUE_LIMIT = int(os.getenv("STELLA_LLM_QUEUE_LIMIT", "3"))
LLM_ENABLED = os.getenv("STELLA_LLM_ENABLED", "1") == "1"

RESCUER_PIN = os.getenv("STELLA_RESCUER_PIN", "0000")

# Адрес портала, куда перенаправляются все чужие домены
PORTAL_HOST = os.getenv("STELLA_PORTAL_HOST", "10.42.0.1")
PORTAL_URL = f"http://{PORTAL_HOST}/"

# Координаты самого хаба (задаются при развёртывании) — центр карты
HUB_LAT = _float("STELLA_HUB_LAT", "")
HUB_LON = _float("STELLA_HUB_LON", "")

MAX_MESSAGE_LEN = 1000
MIN_SECONDS_BETWEEN_MESSAGES = float(os.getenv("STELLA_MIN_INTERVAL", "1.5"))

# --- сеть и определение близости по Wi-Fi ---
SSID = os.getenv("STELLA_SSID", "SOS-STELLA-RESCUE")
HUB_MODE = os.getenv("STELLA_HUB_MODE", "field")   # просто метка для панели
WLAN_IFACE = os.getenv("STELLA_WLAN", "wlan0")
DHCP_LEASES = os.getenv("STELLA_LEASES", "/var/lib/misc/stella.leases")
# Модель затухания сигнала: d = 10 ^ ((TxRef - RSSI) / (10 * n))
# TxRef — уровень сигнала (dBm) на расстоянии 1 м, n — коэффициент среды (в здании 2.7–4).
RSSI_REF_DBM = float(os.getenv("STELLA_RSSI_REF", "-40"))
RSSI_PATH_LOSS = float(os.getenv("STELLA_RSSI_N", "3.0"))
# Сессия считается онлайн, если опрашивала сервер за последние N секунд
ONLINE_WINDOW = float(os.getenv("STELLA_ONLINE_WINDOW", "20"))
