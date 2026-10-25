"""Home Assistant: управление домом + безопасность (подтверждения)."""
import time

import httpx

from . import config

# (domain, action) -> (service domain, service)
_ACTIONS = {
    "on": "turn_on", "off": "turn_off", "toggle": "toggle",
    "lock": "lock", "unlock": "unlock",
    "volume_up": "volume_up", "volume_down": "volume_down", "mute": "volume_mute",
    "set": "turn_on",
}
_pending: dict[str, float] = {}   # "entity|action" -> expires
PENDING_TTL = 120


def enabled() -> bool:
    return bool(config.HA_URL and config.HA_TOKEN)


def _headers():
    return {"Authorization": f"Bearer {config.HA_TOKEN}"}


def resolve(name: str) -> str:
    n = name.strip().lower()
    return config.HOME_ALIASES.get(n, n)


def needs_confirm(entity: str) -> bool:
    return entity.startswith("lock.") or entity.lower() in config.CONFIRM_ENTITIES


async def states() -> list[dict]:
    if not enabled():
        return []
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{config.HA_URL}/api/states", headers=_headers())
        r.raise_for_status()
        return r.json()


async def act(device: str, action: str, data: dict | None = None, confirmed: bool = False) -> dict:
    if not enabled():
        return {"error": "Home Assistant не настроен"}
    entity = resolve(device)
    if "." not in entity:
        return {"error": f"неизвестное устройство '{device}'. Добавьте его в HOME_ALIASES"}
    if action not in _ACTIONS:
        return {"error": f"неизвестное действие, доступно: {sorted(_ACTIONS)}"}
    key = f"{entity}|{action}"
    if needs_confirm(entity):
        now = time.time()
        # подтверждение действует только если сервер сам просил его раньше
        if not (confirmed and _pending.get(key, 0) > now):
            _pending[key] = now + PENDING_TTL
            return {"status": "confirmation_required",
                    "note": "Спросите пользователя и после явного 'да' вызовите снова с confirmed=true"}
        _pending.pop(key, None)
    domain = entity.split(".")[0]
    svc_domain = "homeassistant" if _ACTIONS[action] in ("turn_on", "turn_off", "toggle") and domain in ("switch", "light", "fan", "input_boolean") else domain
    payload = {"entity_id": entity, **(data or {})}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{config.HA_URL}/api/services/{svc_domain}/{_ACTIONS[action]}",
                         headers=_headers(), json=payload)
    if r.status_code >= 400:
        return {"error": f"HA {r.status_code}: {r.text[:200]}"}
    return {"status": "done", "entity": entity, "action": action}


async def list_devices() -> list[dict]:
    out = []
    for s in await states():
        if s["entity_id"].split(".")[0] in ("light", "switch", "lock", "media_player", "climate", "cover"):
            out.append({"entity": s["entity_id"], "state": s["state"],
                        "name": s["attributes"].get("friendly_name", "")})
    return out
