"""Радионяня: Стелла в детской передаёт звук на телефон (страница /baby) или на другую Стеллу,
и присылает уведомление, если ребёнок долго плачет."""
from __future__ import annotations

import queue
import re
import threading
import time

from ..audio import dsp
from ..core.events import bus
from ..integrations.peers import AudioLink, Peers
from .base import Reply, Skill, intent
from .system import local_ip


class BabyMonitor(Skill):
    name = "babymonitor"

    def __init__(self, a):
        super().__init__(a)
        self.active = False
        self._thread = None
        self.link: AudioLink | None = None
        self.peers = Peers(a)

    def _watch(self):
        """Следим за громкостью: громко дольше N секунд — тревога (не чаще раза в 2 минуты)."""
        q = self.a.mic.subscribe()
        thr = float(self.cfg.get("baby_monitor.alert_level_db", -30))
        need = float(self.cfg.get("baby_monitor.alert_seconds", 4))
        loud_since, last_alert = None, 0.0
        try:
            while self.active:
                try:
                    frame = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                db = dsp.rms_db(frame)
                now = time.time()
                if db > thr:
                    loud_since = loud_since or now
                    if now - loud_since >= need and now - last_alert > 120:
                        last_alert = now
                        self.log.info("Радионяня: громко (%.0f дБ)", db)
                        self.a.notify("Похоже, ребёнок проснулся или плачет.", title="👶 Радионяня", urgent=True)
                        bus.emit("baby_alert", level=db)
                else:
                    loud_since = None
        finally:
            self.a.mic.unsubscribe(q)

    @intent(r"\b(?:включи|запусти|активируй)\s+(?:режим\s+)?радионян\w*|\bрежим радионяни\b", priority=63)
    def start_monitor(self, ctx):
        if not self.a.mic.ok and ctx.source != "voice":
            return Reply("Для радионяни нужен микрофон.", emotion="sadness")
        if self.active:
            return Reply("Радионяня уже работает.")
        self.active = True
        self._thread = threading.Thread(target=self._watch, daemon=True, name="babymonitor")
        self._thread.start()
        self.a.whisper_mode = True
        self.a.scheduler.after(6, self.a.mood.sleep, "baby-sleep")
        port = self.cfg.get("web.port", 8765)
        proto = "https" if self.cfg.get("web.https") else "http"
        url = f"{proto}://{local_ip()}:{port}/baby"
        return Reply(f"Радионяня включена. Слушать можно на телефоне по адресу {url} или с другой Стеллы командой "
                     f"«послушай детскую». Если ребёнок заплачет — пришлю уведомление.", whisper=True,
                     emotion="love", intensity=0.5, card=url)

    @intent(r"\b(?:выключи|останови|отключи)\s+(?:режим\s+)?радионян\w*", priority=64)
    def stop_monitor(self, ctx):
        if self.link:
            self.link.stop()
            self.link = None
            return Reply("Больше не слушаю детскую.")
        if not self.active:
            return Reply("Радионяня и так выключена.")
        self.active = False
        self.a.whisper_mode = False
        self.a.mood.wake()
        return Reply("Радионяня выключена.", emotion="joy", intensity=0.4)

    @intent(r"\b(?:послушай|слушай|подключись к|включи прослушивание)\s+(?:в\s+)?(\w+)$|"
            r"\bчто (?:там )?(?:в|во) ((?:детск|кухн|спальн|гостин|комнат|зал|кабинет)\w*)\b", priority=62)
    def listen_peer(self, ctx):
        room = ctx.group(1) or ctx.group(2)
        peer = self.peers.find(room)
        if not peer:
            looks_like_room = re.match(r"(?:детск|кухн|спальн|гостин|комнат|зал|кабинет|ванн|прихож|коридор|этаж)", room)
            if not self.peers.all and looks_like_room and not ctx.group(2):
                return Reply("Другие Стеллы не настроены (раздел peers в настройках).")
            return None
        name, url = peer
        if self.link:
            self.link.stop()
        self.link = AudioLink(self.a, self.peers.ws_url(url, "/ws/baby"), send_mic=False,
                              headers=self.peers._headers(), on_end=lambda: setattr(self, "link", None))
        self.link.start()
        return Reply(f"Слушаю {name}. Скажи «хватит слушать», чтобы выключить.", emotion="interest", intensity=0.5)

    @intent(r"^(?:хватит слушать|перестань слушать|выключи прослушивание)$", priority=64)
    def stop_listen(self, ctx):
        if self.link:
            self.link.stop()
            self.link = None
            return Reply("Выключила.")
        return None
