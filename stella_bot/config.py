import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Config:
    bot_token: str
    eleven_api_key: str
    beta_key: str
    data_dir: Path
    shop_url: str
    creator: str


def load_config() -> Config:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и заполните его.")
    data_dir = Path(os.getenv("DATA_DIR", ROOT / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        bot_token=token,
        eleven_api_key=os.getenv("ELEVENLABS_API_KEY", "").strip(),
        beta_key=os.getenv("BETA_KEY", "085213").strip(),
        data_dir=data_dir,
        shop_url=os.getenv("SHOP_URL", "").strip(),
        creator=os.getenv("CREATOR_USERNAME", "").strip().lstrip("@"),
    )
