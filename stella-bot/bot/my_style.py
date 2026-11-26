"""«Мой стиль»: владелец сканирует QR-код своим WhatsApp — Стелла берёт из истории ТОЛЬКО его собственные сообщения,
составляет портрет манеры письма и дальше пишет в этой манере (оставаясь Стеллой).

- Подключается отдельный временный инстанс Evolution («<instance>-mystyle»), без вебхука: Стелла не читает и не
  отвечает с этого номера. Как только история подгрузилась и его сообщения взяты — инстанс выходит из WhatsApp и
  удаляется вместе со скачанной историей.
- Чужие сообщения не сохраняются; номера и почта в его сообщениях скрываются.
- Всё лежит в kv «my_style»; в панели — посмотреть, выключить, удалить.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import TYPE_CHECKING, Any

from .style_examples import clean

if TYPE_CHECKING:
    from .brain import Brain

log = logging.getLogger("stella.my_style")

KV = "my_style"
MAX_SAMPLES = 3000
HISTORY_WAIT = 600  # сколько ждать подгрузки истории после сканирования, с
STABLE_FOR = 60  # история «догрузилась», если число сообщений не растёт столько секунд
PROMPT_EXAMPLES = 25

PROFILE_SYSTEM = (
    "Ты лингвист. По сообщениям одного человека из мессенджера опиши его манеру письма так, чтобы другой мог писать "
    "неотличимо: длина сообщений, разбивка на несколько сообщений, регистр букв, пунктуация, ошибки и сокращения, "
    "любимые слова и словечки, сленг, мат (насколько и какой), смайлы и эмодзи, как здоровается и прощается, как "
    "шутит, как спорит, как реагирует на новости, тон с друзьями. Конкретно, с примерами слов, без воды, "
    "не больше 1500 символов. Не пересказывай содержание переписки и не упоминай людей, номера, адреса."
)


def _text_of(msg: dict[str, Any]) -> str:
    m = msg.get("message") or {}
    return str(m.get("conversation") or (m.get("extendedTextMessage") or {}).get("text") or "").strip()


def _records(data: Any) -> tuple[list[dict[str, Any]], int]:
    """Ответ findMessages бывает {messages: {records, pages}} или просто списком."""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)], 1
    box = (data or {}).get("messages", data) if isinstance(data, dict) else {}
    if isinstance(box, list):
        return [r for r in box if isinstance(r, dict)], 1
    recs = box.get("records") or []
    return [r for r in recs if isinstance(r, dict)], int(box.get("pages") or 1)


class MyStyle:
    def __init__(self, brain: "Brain"):
        self.brain = brain
        self.state = "idle"  # idle | waiting_scan | importing | building | done | error
        self.detail = ""
        self.task: asyncio.Task | None = None
        self._evo: Any = None

    # ---------- данные ----------
    async def load(self) -> dict[str, Any] | None:
        row = await self.brain.db.kv_get(KV)
        try:
            data = json.loads(row[0]) if row and row[0] else None
        except ValueError:
            data = None
        return data if isinstance(data, dict) and data.get("profile") else None

    async def forget(self) -> None:
        await self.brain.db.kv_set(KV, "", time.time())
        await self._drop_instance()
        self.state, self.detail = "idle", ""

    async def hint(self, rng: random.Random) -> str:
        """Подсказка в запрос модели: портрет стиля + несколько его настоящих сообщений."""
        if not getattr(self.brain.s, "my_style_enabled", True):
            return ""
        data = await self.load()
        if not data:
            return ""
        samples = list(data.get("samples") or [])
        picks = rng.sample(samples, min(PROMPT_EXAMPLES, len(samples))) if samples else []
        lines = "\n".join(f"- {s[:200]}" for s in picks)
        return ("Пиши в манере владельца — так пишет он сам (перенимай длину, словечки, пунктуацию, смайлы и юмор; "
                "ты при этом остаёшься Стеллой и о себе говоришь в женском роде; людей и темы из примеров не "
                f"упоминай):\n{data['profile']}" + (f"\nЕго настоящие сообщения:\n{lines}" if lines else ""))

    # ---------- подключение по QR ----------
    def _client(self) -> Any:
        if self._evo is None:
            from .evolution import Evolution

            s = self.brain.s
            self._evo = Evolution(s.evolution_url, s.evolution_api_key, f"{s.evolution_instance}-mystyle")
        return self._evo

    async def start(self) -> dict[str, Any]:
        """Создать временный инстанс и вернуть QR-код (base64 data URL) для сканирования."""
        if self.task is not None and not self.task.done():
            if self.state == "waiting_scan":
                return await self._qr()
            raise RuntimeError("уже изучаю переписку — подожди")
        evo = self._client()
        await evo.delete_instance()  # хвосты прошлой попытки
        await evo._call("POST", "/instance/create", json={
            "instanceName": evo.instance, "integration": "WHATSAPP-BAILEYS", "qrcode": True,
            "syncFullHistory": True, "groupsIgnore": False, "alwaysOnline": False, "readMessages": False,
            "readStatus": False, "rejectCall": False})
        self.state, self.detail = "waiting_scan", "отсканируй QR-код в WhatsApp: Настройки → Связанные устройства"
        self.task = asyncio.ensure_future(self._run())
        self.brain.tasks.add(self.task)
        self.task.add_done_callback(self.brain.tasks.discard)
        return await self._qr()

    async def _qr(self) -> dict[str, Any]:
        data = await self._client().connect()
        qr = str(data.get("base64") or "")
        if qr and not qr.startswith("data:image"):
            qr = "data:image/png;base64," + qr
        return {"qr": qr, "state": self.state, "detail": self.detail}

    def status(self) -> dict[str, Any]:
        return {"state": self.state, "detail": self.detail}

    async def _run(self) -> None:
        evo = self._client()
        try:
            deadline = time.monotonic() + 300
            while await evo.connection_state() != "open":  # ждём, пока отсканирует
                if time.monotonic() > deadline:
                    raise RuntimeError("QR-код не отсканировали за 5 минут — начни заново")
                await asyncio.sleep(3)
            self.state, self.detail = "importing", "WhatsApp подключён — подгружаю историю (до 10 минут)"
            samples = await self._collect(evo)
            await self._drop_instance()  # сразу выходим из его WhatsApp и стираем историю
            if len(samples) < 30:
                raise RuntimeError(f"нашлось только {len(samples)} твоих сообщений — мало, чтобы понять стиль")
            self.state, self.detail = "building", f"составляю портрет по {len(samples)} сообщениям"
            profile = await self._profile(samples)
            await self.brain.db.kv_set(KV, json.dumps({"profile": profile, "samples": samples[:600],
                                                       "count": len(samples), "updated_at": time.time()},
                                                      ensure_ascii=False), time.time())
            self.state, self.detail = "done", f"готово: изучено {len(samples)} твоих сообщений"
            log.warning("«мой стиль»: портрет готов (%d сообщений)", len(samples))
        except Exception as exc:
            log.warning("«мой стиль»: не получилось: %s", exc)
            self.state, self.detail = "error", str(exc)[:300]
            await self._drop_instance()

    async def _collect(self, evo: Any) -> list[str]:
        """Только его сообщения (fromMe), только текст; ждём, пока история перестанет расти."""
        deadline = time.monotonic() + HISTORY_WAIT
        last, stable_since = -1, time.monotonic()
        texts: list[str] = []
        while time.monotonic() < deadline:
            texts = await self._fetch_own(evo)
            if len(texts) != last:
                last, stable_since = len(texts), time.monotonic()
                self.detail = f"подгружаю историю: твоих сообщений {len(texts)}"
            elif time.monotonic() - stable_since > STABLE_FOR and texts:
                break
            await asyncio.sleep(10)
        return texts

    async def _fetch_own(self, evo: Any) -> list[str]:
        out: list[str] = []
        page = 1
        while len(out) < MAX_SAMPLES:
            data = await evo._call("POST", f"/chat/findMessages/{evo.instance}",
                                   json={"where": {"key": {"fromMe": True}}, "page": page, "offset": 250})
            recs, pages = _records(data)
            for r in recs:
                if (r.get("key") or {}).get("fromMe") is False:
                    continue
                t = clean(_text_of(r))
                if 2 <= len(t) <= 600 and not t.startswith(("http://", "https://")):
                    out.append(t)
            if page >= pages or not recs:
                break
            page += 1
        return list(dict.fromkeys(out))[:MAX_SAMPLES]

    async def _profile(self, samples: list[str]) -> str:
        pick = random.Random(len(samples)).sample(samples, min(400, len(samples)))
        prompt = "Сообщения человека (каждое с новой строки):\n" + "\n".join(f"- {s[:300]}" for s in pick)
        reply = await self.brain.llm.ask(system=PROFILE_SYSTEM, prompt=prompt[:40000],
                                         model=self.brain.s.llm_memory_model, max_turns=1)
        await self.brain.track_cost(reply.cost_usd)
        return reply.text.strip()[:2000]

    async def _drop_instance(self) -> None:
        try:
            await self._client().delete_instance()
        except Exception:
            log.warning("«мой стиль»: не удалось удалить временный инстанс", exc_info=True)
