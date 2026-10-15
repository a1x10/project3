"""Подключение номера WhatsApp к Evolution API.

    docker compose exec bot python -m bot.setup --number 77771234567  # код сопряжения (удобно на сервере)
    docker compose exec bot python -m bot.setup                       # QR-код -> data/qr.png
    docker compose exec bot python -m bot.setup --status
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
from typing import Any, Awaitable, Callable

from .config import settings
from .evolution import Evolution, EvolutionError

PAIR_HELP = ("WhatsApp на телефоне Стеллы -> Настройки -> Связанные устройства -> Привязка устройства -> "
             "«Привязать по номеру телефона» -> ввести код")


def _pairing_code(data: dict[str, Any]) -> str | None:
    code = data.get("pairingCode") or (data.get("qrcode") or {}).get("pairingCode")
    if not code:
        return None
    code = str(code).replace("-", "").strip()
    return f"{code[:4]}-{code[4:]}" if len(code) == 8 else code


async def pair_by_number(evo: Evolution, number: str, webhook_url: str, webhook_secret: str, *,
                         out: Callable[[str], None] = print, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                         timeout: float = 240, poll: float = 3) -> bool:
    """Пересоздать инстанс с номером и показывать код сопряжения, пока телефон не подключится.

    Evolution выдаёт код только если номер указан при создании инстанса: если он уже «подключается» по QR,
    номер игнорируется. Инстанс ещё не подключён, так что терять нечего.
    """
    out("готовлю вход по коду…")
    await evo.delete_instance()
    await sleep(2)
    await evo.create_instance(number=number)
    await evo.set_webhook(webhook_url, webhook_secret)
    last = None
    waited = 0.0
    while waited < timeout:
        try:
            if await evo.connection_state() == "open":
                out("\nномер подключён ✅ Стелла в сети, добавляй её в группу")
                return True
            code = _pairing_code(await evo.connect())
        except EvolutionError as exc:
            out(f"(Evolution: {exc})")
            code = None
        if code and code != last:
            if last is None:
                out(PAIR_HELP)
            else:
                out("код обновился, вводи новый:")
            out(f"\n   КОД:  {code}\n")
            last = code
        await sleep(poll)
        waited += poll
    out("время вышло — запусти команду ещё раз" if last else
        "Evolution не выдала код. Посмотри: docker compose logs evolution | tail -50")
    return False


async def main() -> int:
    ap = argparse.ArgumentParser(description="Подключить номер к Стелле")
    ap.add_argument("--number", help="номер телефона Стеллы в международном формате (+7 707 ... или 7707...)")
    ap.add_argument("--status", action="store_true", help="только показать состояние")
    args = ap.parse_args()

    evo = Evolution(settings.evolution_url, settings.evolution_api_key, settings.evolution_instance)
    try:
        if await evo.find_own_instance() is None:
            await evo.create_instance()
            print(f"создан инстанс «{settings.evolution_instance}»")
        await evo.set_webhook(settings.webhook_url, settings.webhook_secret)
        state = await evo.connection_state()
        print(f"состояние: {state}")
        if state == "open":
            print("номер уже подключён ✅")
            return 0
        if args.status:
            return 0
        number = "".join(ch for ch in (args.number or "") if ch.isdigit())
        if number:
            ok = await pair_by_number(evo, number, settings.webhook_url, settings.webhook_secret)
            return 0 if ok else 1
        data = await evo.connect()
        b64 = data.get("base64") or (data.get("qrcode") or {}).get("base64") or ""
        if b64.startswith("data:image"):
            os.makedirs(settings.data_dir, exist_ok=True)
            path = os.path.join(settings.data_dir, "qr.png")
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64.split(",", 1)[1]))
            print(f"\nQR-код сохранён в {path} (на сервере: ./data/qr.png). Живёт ~40 секунд.")
            print("Удобнее по коду: python -m bot.setup --number НОМЕР_СТЕЛЛЫ")
        else:
            print(f"ответ Evolution: {data}")
        return 0
    except EvolutionError as exc:
        print(f"ошибка Evolution API: {exc}", file=sys.stderr)
        return 1
    finally:
        await evo.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
