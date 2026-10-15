"""Подключение номера WhatsApp к Evolution API.

    docker compose exec bot python -m bot.setup                    # QR-код -> data/qr.png
    docker compose exec bot python -m bot.setup --number 77771234567  # код сопряжения (удобно на сервере)
    docker compose exec bot python -m bot.setup --status
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys

from .config import settings
from .evolution import Evolution, EvolutionError


async def main() -> int:
    ap = argparse.ArgumentParser(description="Подключить номер к Стелле")
    ap.add_argument("--number", help="номер телефона бота в международном формате, только цифры")
    ap.add_argument("--status", action="store_true", help="только показать состояние")
    args = ap.parse_args()

    evo = Evolution(settings.evolution_url, settings.evolution_api_key, settings.evolution_instance)
    try:
        instances = await evo.fetch_instances()
        names = {(i.get("name") or i.get("instanceName")) for i in instances}
        if settings.evolution_instance not in names:
            await evo.create_instance()
            print(f"создан инстанс «{settings.evolution_instance}»")
        await evo.set_webhook(settings.webhook_url, settings.webhook_secret)
        state = await evo.connection_state()
        print(f"состояние: {state}")
        if args.status or state == "open":
            if state == "open":
                print("номер уже подключён ✅")
            return 0
        number = "".join(ch for ch in (args.number or "") if ch.isdigit()) or None
        data = await evo.connect(number)
        if data.get("pairingCode"):
            print(f"\nКод сопряжения: {data['pairingCode']}")
            print("WhatsApp на телефоне бота -> Связанные устройства -> Привязка устройства -> "
                  "Привязать по номеру телефона -> ввести код")
        b64 = data.get("base64") or ""
        if b64.startswith("data:image"):
            os.makedirs(settings.data_dir, exist_ok=True)
            path = os.path.join(settings.data_dir, "qr.png")
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64.split(",", 1)[1]))
            print(f"\nQR-код сохранён в {path} (на сервере: ./data/qr.png)")
            print("WhatsApp -> Связанные устройства -> Привязка устройства -> отсканировать QR. Код живёт ~40 секунд,"
                  " если не успели — запустите команду ещё раз.")
        if not data.get("pairingCode") and not b64:
            print(f"ответ Evolution: {data}")
        return 0
    except EvolutionError as exc:
        print(f"ошибка Evolution API: {exc}", file=sys.stderr)
        return 1
    finally:
        await evo.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
