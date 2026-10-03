"""Загрузка настроек: config.yaml + значения по умолчанию + переменные окружения."""
from __future__ import annotations

import copy
import logging
import os
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

log = logging.getLogger("stella.config")

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    "assistant": {
        "name": "Стелла",
        "wake_words": ["стелла", "стела", "стелло", "стэлла", "stella"],
        "city": "Москва",
        "latitude": 55.7558,
        "longitude": 37.6173,
        "user_name": "",
        "follow_up_seconds": 6,
        "listen_timeout": 8,
        "quiet_hours": ["23:00", "07:00"],
        "night_volume": 30,
        "sleep_after_minutes": 30,
        "bored_after_minutes": 5,
    },
    "personality": {
        "style": "весёлая, добрая, любопытная, с чувством юмора, иногда немного дерзкая",
        "can_get_angry": True,
        "can_refuse_when_angry": True,
        "anger_decay_seconds": 45,
    },
    "display": {
        "enabled": True,
        "fullscreen": True,
        "width": 800,
        "height": 480,
        "fps": 30,
        "supersample": 2,
        "eye_color": [70, 190, 255],
        "background": [0, 0, 0],
        "show_mouth": True,
        "show_brows": True,
        "hide_cursor": True,
        "backend": "pygame",
        "luma": {"driver": "st7789", "width": 320, "height": 240, "rotate": 0,
                 "spi_port": 0, "spi_device": 0, "gpio_DC": 24, "gpio_RST": 25, "gpio_LIGHT": 18},
    },
    "audio": {
        "input_device": None,
        "output_device": None,
        "sample_rate": 16000,
        "volume_control": "auto",
        "mixer_control": "Master",
        "beep": True,
        "duck_volume": 25,
    },
    "stt": {
        "engine": "vosk",
        "vosk_model": "models/vosk-model-small-ru-0.22",
        "whisper_detect": True,
        "yandex_stt": False,
    },
    "tts": {
        "engine": "auto",
        "speed": 1.0,
        "yandex_voice": "marina",
        "yandex_role": "friendly",
        "piper_model": "models/piper/ru_RU-irina-medium.onnx",
        "rhvoice_voice": "anna",
        "espeak_voice": "ru",
        "volume": 1.0,
    },
    "yandex": {
        "api_key": "",
        "iam_token": "",
        "folder_id": "",
        "gpt_model": "yandexgpt-5-lite",
        "temperature": 0.6,
        "max_tokens": 800,
        "history_turns": 12,
    },
    "yandex_music": {"token": ""},
    "music": {
        "music_dir": "~/Music",
        "audiobooks_dir": "~/Audiobooks",
        "podcasts": {},
        "radio": {},
        "audd_token": "",
    },
    "smarthome": {
        "yandex_token": "",
        "home_assistant": {"url": "", "token": ""},
        "poll_seconds": 15,
        "scenarios_file": "scenarios.yaml",
    },
    "tv": {
        "cec": True,
        "cec_device": "/dev/cec0",
        "adb_host": "",
        "iot_name": "",
    },
    "traffic": {"tomtom_key": "", "points": [], "home": None, "work": None},
    "places": {"yandex_geosearch_key": "", "yandex_geocoder_key": "", "dgis_key": "", "radius": 1500},
    "news": {
        "feeds": {
            "главное": "https://lenta.ru/rss/news",
            "технологии": "https://habr.com/ru/rss/articles/?fl=ru",
            "наука": "https://nplus1.ru/rss",
            "спорт": "https://www.sport-express.ru/services/materials/news/se/",
        },
        "count": 5,
    },
    "telegram": {"token": "", "allowed_users": [], "voice_replies": True, "notify_chat": None},
    "notify": {"ntfy_topic": "", "ntfy_server": "https://ntfy.sh"},
    "web": {"enabled": True, "host": "0.0.0.0", "port": 8765, "https": False, "password": ""},
    "peers": {},
    "multiroom": {"enabled": False, "snapcast_host": "127.0.0.1", "fifo": "/tmp/snapfifo"},
    "presence": {"phone_ip": "", "interval": 60},
    "calendar": {"caldav_url": "https://caldav.yandex.ru", "username": "", "password": ""},
    "find_phone": {"phone_number": "", "sip_account": "", "sip_password": "", "ring_seconds": 40},
    "baby_monitor": {"alert_level_db": -30, "alert_seconds": 4},
    "vision": {"enabled": False, "camera": 0, "fps": 6},
    "skills": {"webhooks": [], "plugins_dir": "plugins"},
    "data_dir": "data",
    "log_level": "INFO",
}

# переменные окружения -> путь в конфиге (чтобы не хранить ключи в файле)
ENV_OVERRIDES = {
    "YANDEX_API_KEY": "yandex.api_key",
    "YANDEX_IAM_TOKEN": "yandex.iam_token",
    "YANDEX_FOLDER_ID": "yandex.folder_id",
    "YANDEX_MUSIC_TOKEN": "yandex_music.token",
    "YANDEX_IOT_TOKEN": "smarthome.yandex_token",
    "HA_URL": "smarthome.home_assistant.url",
    "HA_TOKEN": "smarthome.home_assistant.token",
    "TELEGRAM_BOT_TOKEN": "telegram.token",
    "TOMTOM_KEY": "traffic.tomtom_key",
    "AUDD_TOKEN": "music.audd_token",
    "YANDEX_GEOSEARCH_KEY": "places.yandex_geosearch_key",
    "YANDEX_GEOCODER_KEY": "places.yandex_geocoder_key",
    "DGIS_KEY": "places.dgis_key",
    "CALDAV_USERNAME": "calendar.username",
    "CALDAV_PASSWORD": "calendar.password",
    "STELLA_WEB_PASSWORD": "web.password",
}


def _deep_merge(base: dict, extra: dict) -> dict:
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


class Config:
    """Обёртка над словарём: cfg.get("yandex.api_key"), cfg["display"]["fps"]."""

    def __init__(self, data: dict | None = None, path: Path | None = None):
        self.data = data if data is not None else copy.deepcopy(DEFAULTS)
        self.path = path

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        data = copy.deepcopy(DEFAULTS)
        p = Path(path or os.environ.get("STELLA_CONFIG") or BASE_DIR / "config.yaml")
        if p.exists():
            if yaml is None:
                raise RuntimeError("Нужен пакет pyyaml: pip install pyyaml")
            with open(p, encoding="utf-8") as f:
                _deep_merge(data, yaml.safe_load(f) or {})
            log.info("Настройки загружены из %s", p)
        else:
            log.warning("Файл настроек %s не найден — работаю с настройками по умолчанию", p)
        cfg = cls(data, p)
        for env, dotted in ENV_OVERRIDES.items():
            if os.environ.get(env):
                cfg.set(dotted, os.environ[env])
        return cfg

    def get(self, dotted: str, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node if node is not None else default

    def set(self, dotted: str, value):
        node = self.data
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def __getitem__(self, key):
        return self.data[key]

    def path_of(self, dotted: str, default: str = "") -> Path:
        """Путь из настроек: ~ раскрывается, относительный — от папки проекта."""
        p = Path(os.path.expanduser(str(self.get(dotted, default) or default)))
        return p if p.is_absolute() else BASE_DIR / p

    @property
    def data_dir(self) -> Path:
        d = self.path_of("data_dir", "data")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, path: str | os.PathLike | None = None):
        p = Path(path or self.path or BASE_DIR / "config.yaml")
        with open(p, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.data, f, allow_unicode=True, sort_keys=False)
