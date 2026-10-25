import json
import os
from zoneinfo import ZoneInfo


def _list(name: str) -> list[str]:
    return [x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip()]


API_KEY = os.getenv("STELLA_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek/deepseek-chat")
VISION_MODEL = os.getenv("VISION_MODEL", "google/gemini-2.0-flash-001")
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")   # low/medium/high для моделей-рассуждателей (gpt-oss)

USER_NAME = os.getenv("USER_NAME", "Алексей")
TZ = ZoneInfo(os.getenv("TZ", "Asia/Almaty"))
VIP_CONTACTS = _list("VIP_CONTACTS")
NIGHT_FROM = int(os.getenv("NIGHT_FROM", "0"))
NIGHT_TO = int(os.getenv("NIGHT_TO", "8"))

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_LANG = os.getenv("WHISPER_LANG", "ru")

DATA_DIR = os.getenv("DATA_DIR", "./data")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", os.path.join(DATA_DIR, "google_token.json"))
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")

HA_URL = os.getenv("HA_URL", "").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
CONFIRM_ENTITIES = set(_list("CONFIRM_ENTITIES"))
HOME_ALIASES = {k.lower(): v for k, v in json.loads(os.getenv("HOME_ALIASES", "{}")).items()}

WASHER_ENTITY = os.getenv("WASHER_ENTITY", "")                # switch/button запуска
WASHER_PROGRAM_SELECT = os.getenv("WASHER_PROGRAM_SELECT", "")  # select.* выбора режима
WASHER_PROGRAMS = json.loads(os.getenv("WASHER_PROGRAMS", "{}"))  # {"cotton":"Cotton 60","delicate":"..."}

HABIT_MIN_DAYS = int(os.getenv("HABIT_MIN_DAYS", "4"))
HABIT_WINDOW_DAYS = int(os.getenv("HABIT_WINDOW_DAYS", "14"))
HABIT_LEAD_MIN = int(os.getenv("HABIT_LEAD_MIN", "20"))

os.makedirs(DATA_DIR, exist_ok=True)
