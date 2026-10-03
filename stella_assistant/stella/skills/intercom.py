"""Звонки и объявления по дому: «позвони на кухню», «скажи в детской: обед готов», «объяви всем…»,
«включи музыку на кухне», мультирум (Snapcast) и «позвони мне» (ссылка на звонок с телефона)."""
from __future__ import annotations

import json
import re
import socket

from ..integrations.peers import AudioLink, Peers
from .base import Reply, Skill, intent
from .system import local_ip


class Intercom(Skill):
    name = "intercom"

    def __init__(self, a):
        super().__init__(a)
        self.peers = Peers(a)
        self.call: AudioLink | None = None

    # ---------------------------------------------------------- объявления --
    @intent(r"\b(?:скажи|передай|объяви)\s+(?:на|в|во)\s+(\w+)\s*,?\s*(?:что\s+)?(.+)$", priority=63)
    def say_room(self, ctx):
        peer = self.peers.find(ctx.group(1))
        if not peer:
            return None
        name, url = peer
        text = ctx.raw_group(2)
        try:
            self.peers.say(url, text)
            return Reply(f"Передала: {text}.", emotion="confidence", intensity=0.4)
        except Exception:
            return Reply(f"Стелла в комнате «{name}» не отвечает.", emotion="sadness")

    @intent(r"\b(?:объяви|скажи|передай)\s+(?:всем|везде|по всему дому|во всех комнатах)\s*,?\s*(?:что\s+)?(.+)$",
            priority=64)
    def announce_all(self, ctx):
        peers = self.peers.all
        if not peers:
            return Reply("Других Стелл в доме нет — некому объявлять.", emotion="sadness", intensity=0.4)
        text = ctx.raw_group(1)
        ok = 0
        for name, url in peers.items():
            try:
                self.peers.say(url, text)
                ok += 1
            except Exception:
                self.log.warning("объявление: %s не отвечает", name)
        return Reply(f"Объявила: {text}" if ok else "Никто не ответил.", emotion="confidence" if ok else "sadness")

    @intent(r"\b(включи|поставь|выключи|сделай)\s+(.+?)\s+(?:на|в|во)\s+(кухн\w*|детск\w*|спальн\w*|гостин\w*|"
            r"зал\w*|комнат\w*|ванн\w*|кабинет\w*|прихож\w*|коридор\w*|\w+)$", priority=47)
    def remote_command(self, ctx):
        peer = self.peers.find(ctx.group(3))
        if not peer:
            return None
        name, url = peer
        cmd = f"{ctx.group(1)} {ctx.raw_group(2)}"
        try:
            self.peers.command(url, cmd)
            return Reply(f"Готово, в комнате «{name}».", emotion="confidence", intensity=0.4)
        except Exception:
            return Reply(f"Стелла в комнате «{name}» не отвечает.", emotion="sadness")

    # --------------------------------------------------------------- звонки --
    @intent(r"\b(?:позвони|набери|соедини (?:меня )?с|вызови)\s+(?:на|в|во)?\s*(\w+)$", priority=62)
    def call_room(self, ctx):
        target = ctx.group(1)
        if re.match(r"^(?:мне|меня)$", target):
            return self.call_me(ctx)
        peer = self.peers.find(target)
        if not peer:
            if not self.peers.all and re.match(r"(?:кухн|детск|спальн|гостин|комнат|зал|кабинет|ванн|прихож)", target):
                return Reply("Чтобы звонить в другие комнаты, поставь там ещё одну Стеллу и добавь её адрес в раздел "
                             "peers настроек.", emotion="sadness", intensity=0.5)
            return None
        name, url = peer
        if self.call:
            self.call.stop()
        ws = self.peers.ws_url(url, f"/ws/call?from={self.a.name}")
        self.call = AudioLink(self.a, ws, send_mic=True, headers=self.peers._headers(), on_end=self._call_ended)
        self.call.start()
        # своё имя в ответе не произносим: распознаватель услышит его и разбудит Стеллу посреди фразы
        return Reply(f"Звоню: {name}. Чтобы закончить, позови меня и скажи «положи трубку».", emotion="joy",
                     intensity=0.5)

    def _call_ended(self):
        self.call = None
        if self.a.listener:
            self.a.listener.allow_barge_in = False

    @intent(r"^(?:позвони мне|набери меня)$", priority=63)
    def call_me(self, ctx):
        port = self.cfg.get("web.port", 8765)
        url = f"https://{local_ip()}:{port}/call" if self.cfg.get("web.https") else f"http://{local_ip()}:{port}/call"
        if not self.a.notifier.configured:
            return Reply(f"Открой на телефоне страницу {url} — и мы сможем поговорить.", card=url)
        self.a.notify(f"Стелла зовёт поговорить: {url}", title="📞 Звонок от Стеллы", urgent=True)
        return Reply("Отправила тебе ссылку для звонка в Telegram.", emotion="joy", intensity=0.5, card=url)

    @intent(r"^(?:положи трубку|заверши звонок|закончи звонок|отбой|сбрось звонок|пока пока)$", priority=90)
    def hangup(self, ctx):
        web = getattr(self.a, "web", None)
        ended = False
        if self.call:
            self.call.stop()
            self.call = None
            ended = True
        if web and web.hangup():
            ended = True
        if self.a.listener:
            self.a.listener.allow_barge_in = False
        return Reply("Звонок завершён." if ended else "Сейчас нет звонка.")

    # ------------------------------------------------------------ мультирум --
    def _snap(self, method: str, params: dict | None = None):
        host = self.cfg.get("multiroom.snapcast_host", "127.0.0.1")
        with socket.create_connection((host, 1705), timeout=4) as s:
            s.sendall((json.dumps({"id": 1, "jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.split(b"\n")[0]).get("result")

    @intent(r"\b(?:включи|запусти)\s+(?:музыку\s+)?(?:везде|во всем доме|во всех комнатах|мультирум)\b|"
            r"\bмузыку везде\b", priority=66)
    def multiroom_on(self, ctx):
        if not self.cfg.get("multiroom.enabled"):
            return Reply("Мультирум не настроен: нужен Snapcast (snapserver на главной Стелле, snapclient на остальных) "
                         "и multiroom.enabled: true в настройках.", emotion="sadness", intensity=0.5)
        self.a.player.set_multiroom(True)
        if not self.a.player.is_playing():
            music = self.a.skill("music")
            if music:
                music.play_default()
        return Reply("Включила музыку во всех комнатах.", emotion="joy", intensity=0.7)

    @intent(r"\b(?:выключи|останови)\s+мультирум\b|\bмузыку только здесь\b|\bтолько в этой комнате\b", priority=66)
    def multiroom_off(self, ctx):
        self.a.player.set_multiroom(False)
        return Reply("Теперь музыка играет только здесь.")

    @intent(r"\b(?:сделай|сделать)\s+(?:музыку\s+)?(тише|громче)\s+(?:на|в|во)\s+(\w+)$", priority=67)
    def room_volume(self, ctx):
        if not self.cfg.get("multiroom.enabled"):
            return None
        room = ctx.group(2)
        try:
            status = self._snap("Server.GetStatus")
            for g in status["server"]["groups"]:
                for c in g["clients"]:
                    name = c["config"].get("name") or c["host"]["name"]
                    if room[:4] in name.lower():
                        vol = c["config"]["volume"]["percent"] + (15 if ctx.group(1) == "громче" else -15)
                        self._snap("Client.SetVolume", {"id": c["id"], "volume": {"muted": False,
                                                                                    "percent": max(0, min(100, vol))}})
                        return Reply("Готово.")
        except Exception as e:
            self.log.warning("Snapcast: %s", e)
            return Reply("Snapcast не отвечает.", emotion="sadness")
        return Reply(f"Не нашла колонку «{room}» в мультируме.")
