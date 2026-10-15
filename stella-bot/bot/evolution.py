"""Тонкий клиент Evolution API v2 (WhatsApp через Baileys)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from .util import mask_phone

log = logging.getLogger("stella.evolution")

WEBHOOK_EVENTS = ["MESSAGES_UPSERT", "CONNECTION_UPDATE"]


class EvolutionError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Evolution:
    def __init__(self, base_url: str, api_key: str, instance: str, client: httpx.AsyncClient | None = None):
        self.instance = instance
        self.http = client or httpx.AsyncClient(
            base_url=base_url,
            headers={"apikey": api_key, "Content-Type": "application/json"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _call(
        self, method: str, path: str, *, json: Any = None, params: Any = None, timeout: float | None = None
    ) -> Any:
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self.http.request(
                    method, path, json=json, params=params, timeout=timeout or self.http.timeout
                )
            except httpx.TransportError as exc:  # сеть/контейнер перезапускается
                last_exc = exc
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 500 and attempt < 2:
                last_exc = EvolutionError(f"{method} {path}: {resp.status_code} {resp.text[:300]}", resp.status_code)
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise EvolutionError(f"{method} {path}: {resp.status_code} {resp.text[:300]}", resp.status_code)
            if not resp.content:
                return {}
            try:
                return resp.json()
            except ValueError:
                return {"raw": resp.text}
        raise EvolutionError(f"{method} {path}: {last_exc}")

    # ---------- инстанс ----------
    async def fetch_instances(self) -> list[dict[str, Any]]:
        """Все инстансы на сервере Evolution ([] если их ещё нет)."""
        try:
            data = await self._call("GET", "/instance/fetchInstances")
        except EvolutionError as exc:
            if exc.status == 404:
                return []
            raise
        if isinstance(data, dict):
            data = [data] if data else []
        return [i for i in data if isinstance(i, dict)]

    @staticmethod
    def instance_name(info: dict[str, Any]) -> str:
        return str(info.get("name") or info.get("instanceName") or (info.get("instance") or {}).get("instanceName") or "")

    async def find_own_instance(self) -> dict[str, Any] | None:
        return next((i for i in await self.fetch_instances() if self.instance_name(i) == self.instance), None)

    async def create_instance(self, number: str | None = None) -> dict[str, Any]:
        """number — номер бота: тогда Evolution сразу выдаёт код сопряжения вместо QR."""
        body: dict[str, Any] = {"number": number} if number else {}
        return await self._call(
            "POST",
            "/instance/create",
            json={
                **body,
                "instanceName": self.instance,
                "integration": "WHATSAPP-BAILEYS",
                "qrcode": True,
                "groupsIgnore": False,
                "alwaysOnline": False,  # «в сети» постоянно — подозрительно
                "readMessages": False,  # прочтение ставим сами, когда «прочитали»
                "readStatus": False,
                "syncFullHistory": False,
                "rejectCall": True,
                "msgCall": "сейчас не могу ответить на звонок, напишите, пожалуйста",
            },
        )

    async def set_webhook(self, url: str, secret: str) -> dict[str, Any]:
        headers = {"x-webhook-secret": secret} if secret else {}
        return await self._call(
            "POST",
            f"/webhook/set/{self.instance}",
            json={
                "webhook": {
                    "enabled": True,
                    "url": url,
                    "headers": headers,
                    "byEvents": False,
                    "base64": False,
                    "events": WEBHOOK_EVENTS,
                }
            },
        )

    async def connect(self, number: str | None = None) -> dict[str, Any]:
        """QR-код (base64/code) или код сопряжения, если передан номер телефона."""
        params = {"number": number} if number else None
        return await self._call("GET", f"/instance/connect/{self.instance}", params=params)

    async def delete_instance(self) -> None:
        """Выйти и удалить инстанс (ошибки игнорируются: инстанса может уже не быть)."""
        for method, path in (("DELETE", f"/instance/logout/{self.instance}"),
                             ("DELETE", f"/instance/delete/{self.instance}")):
            try:
                await self._call(method, path)
            except EvolutionError:
                pass

    async def connection_state(self) -> str:
        data = await self._call("GET", f"/instance/connectionState/{self.instance}")
        return str((data.get("instance") or {}).get("state") or data.get("state") or "unknown")

    async def group_subject(self, group_jid: str) -> str | None:
        data = await self._call("GET", f"/group/findGroupInfos/{self.instance}", params={"groupJid": group_jid})
        return data.get("subject") if isinstance(data, dict) else None

    # ---------- отправка ----------
    async def send_text(
        self,
        number: str,
        text: str,
        *,
        delay_ms: int = 0,
        quoted: dict[str, Any] | None = None,
        mentioned: list[str] | None = None,
        mentions_everyone: bool = False,
    ) -> str | None:
        """delay_ms: Evolution показывает «печатает…» столько миллисекунд, потом отправляет."""
        body: dict[str, Any] = {"number": number, "text": text, "linkPreview": False}
        if delay_ms:
            body["delay"] = int(delay_ms)
        if quoted:
            body["quoted"] = quoted
        if mentioned:
            body["mentioned"] = mentioned
        if mentions_everyone:
            body["mentionsEveryOne"] = True
        data = await self._call("POST", f"/message/sendText/{self.instance}", json=body, timeout=delay_ms / 1000 + 40)
        log.debug("sent text to %s", mask_phone(number))
        return ((data or {}).get("key") or {}).get("id")

    async def send_sticker(self, number: str, sticker_b64: str, *, delay_ms: int = 0) -> str | None:
        body: dict[str, Any] = {"number": number, "sticker": sticker_b64}
        if delay_ms:
            body["delay"] = int(delay_ms)
        data = await self._call(
            "POST", f"/message/sendSticker/{self.instance}", json=body, timeout=delay_ms / 1000 + 60
        )
        return ((data or {}).get("key") or {}).get("id")

    async def send_poll(self, number: str, question: str, options: list[str], *, multiple: bool = False,
                        delay_ms: int = 0) -> str | None:
        body: dict[str, Any] = {
            "number": number,
            "name": question,
            "selectableCount": len(options) if multiple else 1,
            "values": options,
        }
        if delay_ms:
            body["delay"] = int(delay_ms)
        data = await self._call("POST", f"/message/sendPoll/{self.instance}", json=body, timeout=delay_ms / 1000 + 40)
        return ((data or {}).get("key") or {}).get("id")

    async def delete_message(self, key: dict[str, Any]) -> None:
        """Удалить сообщение у всех (чужое — только если бот админ группы)."""
        body = {k: key[k] for k in ("id", "remoteJid", "fromMe", "participant") if key.get(k) is not None}
        await self._call("DELETE", f"/chat/deleteMessageForEveryone/{self.instance}", json=body)

    async def send_reaction(self, key: dict[str, Any], emoji: str) -> None:
        clean_key = {k: key[k] for k in ("remoteJid", "fromMe", "id", "participant") if key.get(k) is not None}
        await self._call("POST", f"/message/sendReaction/{self.instance}", json={"key": clean_key, "reaction": emoji})

    async def send_presence(self, number: str, presence: str = "composing", delay_ms: int = 3000) -> None:
        await self._call(
            "POST",
            f"/chat/sendPresence/{self.instance}",
            json={"number": number, "presence": presence, "delay": int(delay_ms)},
            timeout=delay_ms / 1000 + 20,
        )

    async def mark_read(self, keys: list[dict[str, Any]]) -> None:
        if not keys:
            return
        items = [
            {"remoteJid": k.get("remoteJid"), "fromMe": bool(k.get("fromMe")), "id": k.get("id")}
            for k in keys
            if k.get("id")
        ]
        await self._call("POST", f"/chat/markMessageAsRead/{self.instance}", json={"readMessages": items})

    async def media_base64(self, key: dict[str, Any], message: dict[str, Any] | None = None) -> bytes | None:
        """Скачать медиа (стикер) из сообщения. Если передан message — без поиска по базе Evolution."""
        import base64

        payload: dict[str, Any] = {"key": key}
        if message:
            payload["message"] = message
        data = await self._call(
            "POST",
            f"/chat/getBase64FromMediaMessage/{self.instance}",
            json={"message": payload, "convertToMp4": False},
            timeout=60,
        )
        b64 = (data or {}).get("base64")
        return base64.b64decode(b64) if b64 else None
