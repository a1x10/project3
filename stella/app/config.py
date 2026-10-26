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

WAKE_REQUIRED = os.getenv("WAKE_REQUIRED", "1") == "1"   # 0 = отвечать на любую фразу, без слова «Стелла»
STT_FALLBACK_WHISPER = os.getenv("STT_FALLBACK_WHISPER", "1") == "1"   # 0 = Whisper не используется совсем (только Scribe)
STT_SCRIBE_ON_EMPTY = os.getenv("STT_SCRIBE_ON_EMPTY", "1") == "1"   # пустое у Whisper -> второе мнение у Scribe
STT_BOOST = os.getenv("STT_BOOST", "1") == "1"       # выравнивание громкости перед распознаванием
STT_DEBUG = os.getenv("STT_DEBUG", "0") == "1"           # писать в лог, что услышала (на экране тоже)
WAKE_WEAK = os.getenv("WAKE_WEAK", "1") == "1"   # реагировать на искажения имени (стала, стол, что…) как на первое слово

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")   # быстрая, понимает русский
ELEVENLABS_STABILITY = float(os.getenv("ELEVENLABS_STABILITY", "0.5"))
ELEVENLABS_SIMILARITY = float(os.getenv("ELEVENLABS_SIMILARITY", "0.75"))
ELEVENLABS_SPEED = os.getenv("ELEVENLABS_SPEED", "")   # пусто = по умолчанию (v3 параметр speed не принимает)

# распознавание речи: whisper (локально) | elevenlabs (всё через Scribe) | hybrid (Whisper-фильтр + Scribe для команд)
STT_ENGINE = os.getenv("STT_ENGINE", "hybrid" if ELEVENLABS_API_KEY else "whisper").lower()
ELEVENLABS_STT_MODEL = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v2")
ELEVENLABS_STT_KEYTERMS = [x.strip() for x in os.getenv("ELEVENLABS_STT_KEYTERMS", "Стелла,Стела").split(",") if x.strip()]

WASHER_ENTITY = os.getenv("WASHER_ENTITY", "")                # switch/button запуска
WASHER_PROGRAM_SELECT = os.getenv("WASHER_PROGRAM_SELECT", "")  # select.* выбора режима
WASHER_PROGRAMS = json.loads(os.getenv("WASHER_PROGRAMS", "{}"))  # {"cotton":"Cotton 60","delicate":"..."}

HABIT_MIN_DAYS = int(os.getenv("HABIT_MIN_DAYS", "4"))
HABIT_WINDOW_DAYS = int(os.getenv("HABIT_WINDOW_DAYS", "14"))
HABIT_LEAD_MIN = int(os.getenv("HABIT_LEAD_MIN", "20"))

os.makedirs(DATA_DIR, exist_ok=True)
