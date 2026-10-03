"""Ассистент Стелла: связывает слух, речь, лицо, характер, память, навыки и ИИ."""
from __future__ import annotations

import concurrent.futures as cf
import importlib
import importlib.util
import inspect
import logging
import random
import re
import threading
import time

import requests

from ..audio import dsp
from ..audio.io import MicHub, Speaker
from ..audio.player import MusicPlayer
from ..audio.tts import TTS
from ..audio.volume import SystemVolume
from ..face.emotion_engine import EmotionEngine, guess_emotion
from ..integrations.notify import Notifier
from ..llm.brain import Brain
from ..nlp.text import norm, split_for_tts
from ..skills.base import Context, Reply, SessionHandler, Skill, as_reply
from .events import bus
from .memory import Memory
from .scheduler import Scheduler

log = logging.getLogger("stella")

SKILL_MODULES = [
    "system", "social", "memory_skill", "volume", "alarms", "lists", "music", "shazam", "weather", "calc",
    "search", "maps", "smarthome", "tv", "babymonitor", "intercom", "findphone", "games",
    "recipes", "reader", "external", "chat",
]

REFUSALS = [
    "Не буду. Сначала извинись.", "Попроси вежливо — может, и сделаю.", "Ой, всё. Я обиделась.",
    "Не хочу. Ты со мной грубо разговаривал.", "Нет. Мне нужно извинение.",
]
UNKNOWN = [
    "Я пока не поняла. Скажи по-другому?", "Хм, этого я не умею… пока.",
    "Не расслышала, повтори, пожалуйста.",
]


class Assistant:
    def __init__(self, cfg, face=None, voice: bool = True):
        self.cfg = cfg
        self.face = face
        self.voice_enabled = voice
        self.name = cfg.get("assistant.name", "Стелла")
        self.memory = Memory(cfg.data_dir / "stella.db")
        self.mood = EmotionEngine(cfg, self.memory)
        self.brain = Brain(cfg, self.memory, self.mood)
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "StellaAssistant/1.0 (Raspberry Pi home voice assistant)"
        self.tts = TTS(cfg)
        self.speaker = Speaker(cfg)
        self.mic = MicHub(cfg)
        self.listener = None
        self.player = MusicPlayer(cfg)
        self.volume = SystemVolume(cfg)
        self.notifier = Notifier(cfg)
        self.scheduler = Scheduler()
        self.session: SessionHandler | None = None
        self.whisper_mode = False       # «говори шёпотом»
        self.last_whisper = False       # последняя команда была шёпотом
        self.last_reply = ""
        self.listening = False
        self.ringing = None             # активный будильник/таймер (объект с .stop() и .snooze())
        self.stop_event = threading.Event()
        self._exec = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="brain")
        self._say_lock = threading.RLock()
        self.skills: list[Skill] = []
        self.intents = []
        self._load_skills()
        bus.on("say", lambda text, emotion=None, **_: threading.Thread(
            target=self.say, args=(text,), kwargs={"emotion": emotion}, daemon=True).start())
        bus.on("wake", lambda **_: self.on_wake())
        bus.on("touch", lambda **_: self._on_touch())

    # ---------------------------------------------------------- навыки --
    def _load_skills(self):
        for mod_name in SKILL_MODULES:
            try:
                mod = importlib.import_module(f"stella.skills.{mod_name}")
            except Exception:
                log.exception("Навык %s не загрузился", mod_name)
                continue
            self._register_module(mod)
        plugins = self.cfg.path_of("skills.plugins_dir", "plugins")
        if plugins.is_dir():
            for path in sorted(plugins.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                try:
                    spec = importlib.util.spec_from_file_location(f"stella_plugin_{path.stem}", path)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    self._register_module(mod)
                    log.info("Плагин подключён: %s", path.name)
                except Exception:
                    log.exception("Плагин %s не загрузился", path.name)
        self.intents.sort(key=lambda it: -it.priority)
        log.info("Навыков: %d, команд: %d", len(self.skills), len(self.intents))

    def _register_module(self, mod):
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if issubclass(cls, Skill) and cls is not Skill and cls.__module__ == mod.__name__:
                try:
                    sk = cls(self)
                except Exception:
                    log.exception("Навык %s не создан", cls.__name__)
                    continue
                self.skills.append(sk)
                self.intents.extend(sk.intents())

    def skill(self, name: str):
        return next((s for s in self.skills if s.name == name), None)

    # ----------------------------------------------------------- запуск --
    def start(self):
        self.scheduler.start()
        self.scheduler.every(1.0, self.mood.tick, "mood")
        if self.voice_enabled and self.cfg.get("stt.engine", "vosk") != "off":
            if self.mic.start():
                from ..audio.stt import Listener
                self.listener = Listener(self.cfg, self.mic, self.on_wake, self.on_command,
                                         self.on_timeout, self.on_partial)
                self.listener.start()
        for sk in self.skills:
            try:
                sk.start()
            except Exception:
                log.exception("Навык %s не стартовал", sk.name)
        log.info("%s готова к работе", self.name)

    def shutdown(self):
        self.stop_event.set()
        for sk in self.skills:
            try:
                sk.stop()
            except Exception:
                pass
        if self.listener:
            self.listener.stop()
        self.mic.stop()
        self.player.close()
        self.scheduler.stop()
        self._exec.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------- голосовые события --
    def on_wake(self):
        log.info("Активатор!")
        self.mood.on_activity()
        if self.speaker.speaking:
            self.speaker.stop()  # перебили — замолкаем
        if self.ringing:
            self.ringing.stop()
        self.listening = True
        self.player.duck()
        bus.emit("state", state="listening")
        if self.cfg.get("audio.beep", True):
            threading.Thread(target=self.speaker.play, args=(dsp.beep("listen"), 22050, False, 0.7),
                             daemon=True).start()

    def on_partial(self, text: str):
        bus.emit("subtitle", text=text, seconds=2.5)

    def on_command(self, text: str, whisper: bool = False):
        self.listening = False
        self.submit(text, source="voice", whisper=whisper)

    def on_timeout(self):
        self.listening = False
        bus.emit("state", state="idle")
        if not self.speaker.speaking:
            self.player.unduck()

    def _on_touch(self):
        if self.ringing:  # касание экрана выключает будильник
            self.ringing.stop()

    # --------------------------------------------------------- обработка --
    def submit(self, text: str, source: str = "voice", whisper: bool = False, user=None, chat_id=None,
               speak: bool | None = None) -> cf.Future:
        return self._exec.submit(self._process, text, source, whisper, user, chat_id, speak)

    def ask(self, text: str, source: str = "web", timeout: float = 60, **kw) -> Reply:
        """Синхронно: текст -> ответ (для веб-панели, Telegram, тестов)."""
        try:
            return self.submit(text, source=source, **kw).result(timeout=timeout)
        except cf.TimeoutError:
            return Reply("Я задумалась слишком надолго, попробуй ещё раз.", emotion="sadness")

    def _process(self, text, source, whisper, user, chat_id, speak):
        try:
            if source == "voice":
                bus.emit("state", state="thinking")
            reply = self.handle(text, source, whisper, user, chat_id)
            if speak is None:
                speak = source in ("voice", "scenario", "peer")
            self.respond(reply, source, speak)
            return reply
        except Exception:
            log.exception("Ошибка при обработке «%s»", text)
            r = Reply("Ой, что-то пошло не так. Попробуй ещё раз.", emotion="sadness")
            self.respond(r, source, source == "voice")
            return r

    def handle(self, text: str, source: str = "voice", whisper: bool = False, user=None, chat_id=None,
               depth: int = 0) -> Reply:
        text = (text or "").strip()
        ctx = Context(text=text, norm=norm(text), source=source, whisper=whisper, user=user,
                      assistant=self, chat_id=chat_id)
        if source == "voice":
            self.last_whisper = whisper
        bus.emit("heard", text=text, whisper=whisper, source=source)
        if not text:
            return Reply("Слушаю!", expect_reply=True, emotion="interest")
        if depth == 0:
            self.mood.on_user_text(text)
        reply = None
        # 1. активная сессия (игра, рецепт, внешний навык)
        if self.session:
            sess = self.session
            words = set(ctx.norm.split())
            if words & set(sess.exit_words) and len(words) <= 4:
                self.session = None
                reply = Reply("Хорошо, закончили.", emotion="neutral")
            else:
                try:
                    reply = as_reply(sess.handler(ctx))
                except Exception:
                    log.exception("Сессия %s упала", sess.name)
                    self.session = None
                    reply = None
        # 2. навыки по шаблонам
        if reply is None:
            reply = self.route(ctx)
        # 3. ИИ-собеседник
        if reply is None:
            reply = self.think(ctx, depth)
        if depth == 0:
            self.memory.add_dialog("user", text)
            if reply and reply.text:
                self.memory.add_dialog("assistant", reply.text)
        return reply or Reply(random.choice(UNKNOWN), emotion="sadness", expect_reply=True)

    def route(self, ctx: Context) -> Reply | None:
        for it in self.intents:
            for pat in it.patterns:
                m = pat.search(ctx.norm)
                if not m:
                    continue
                if it.fun and self.mood.should_refuse(fun=True):
                    return Reply(random.choice(REFUSALS), emotion="anger")
                ctx.match = m
                try:
                    r = as_reply(it.handler(ctx))
                except Exception:
                    log.exception("Навык %s упал на «%s»", it.name, ctx.text)
                    return Reply("Не получилось, извини. Что-то сломалось внутри.", emotion="sadness")
                if r is not None:
                    log.debug("→ %s", it.name)
                    return r
        return None

    def think(self, ctx: Context, depth: int = 0) -> Reply | None:
        if not self.brain.available:
            return None
        if self.mood.should_refuse(fun=True):
            return Reply(random.choice(REFUSALS), emotion="anger")
        th = self.brain.think(ctx.text)
        if th.command and depth == 0 and th.command.lower() != ctx.text.lower():
            log.info("ИИ понял как команду: %s", th.command)
            sub = Context(text=th.command, norm=norm(th.command), source=ctx.source, whisper=ctx.whisper,
                          assistant=self, chat_id=ctx.chat_id)
            r = self.route(sub)
            if r:
                return r
        if th.search:
            search = self.skill("search")
            if search:
                return search.answer_with_search(ctx, th.search)
        if not th.text:
            return Reply("Мой облачный мозг сейчас недоступен. Давай попробуем чуть позже?", emotion="sadness")
        return Reply(th.text, emotion=th.emotion)

    # ------------------------------------------------------------- ответ --
    def respond(self, reply: Reply, source: str = "voice", speak: bool = True):
        if reply is None:
            return
        emotion = reply.emotion
        if emotion is None and reply.text:
            g = guess_emotion(reply.text)
            emotion = g[0] if g else None
        if emotion:
            bus.emit("emotion", name=emotion, intensity=reply.intensity)
        self.last_reply = reply.text or self.last_reply
        bus.emit("reply", text=reply.text, emotion=emotion, card=reply.card, source=source)
        if speak and reply.speak and reply.text:
            self.say(reply.text, emotion=emotion, whisper=reply.whisper, lang=reply.lang)
        if source == "voice" and reply.expect_reply and self.listener:
            self.listener.listen_now(float(self.cfg.get("assistant.follow_up_seconds", 6)))
            self.listening = True
            bus.emit("state", state="listening")
            self.player.duck()
        else:
            if not self.listening:
                bus.emit("state", state="idle")
                self.player.unduck()

    def say(self, text: str, emotion: str | None = None, whisper: bool | None = None, lang: str = "ru",
            wait: bool = True):
        """Произнести текст (с анимацией рта). wait=False — не ждать окончания."""
        if not text:
            return
        if not wait:
            threading.Thread(target=self.say, args=(text, emotion, whisper, lang, True), daemon=True).start()
            return
        if whisper is None:
            whisper = self.whisper_mode or self.last_whisper
        volume = float(self.cfg.get("tts.volume", 1.0))
        if whisper:
            volume *= 0.7
        elif self.mood.is_night():
            volume *= 0.65
        log.info("%s: %s", self.name, text)
        bus.emit("subtitle", text=text, seconds=min(12.0, 2 + len(text) / 14))
        with self._say_lock:
            self.player.duck()
            bus.emit("state", state="speaking")
            chunks = split_for_tts(text, 230)
            nxt = self._exec_tts(chunks[0], emotion, whisper, lang) if chunks else None
            for i in range(len(chunks)):
                samples, sr = nxt.result() if nxt else (None, 0)
                nxt = self._exec_tts(chunks[i + 1], emotion, whisper, lang) if i + 1 < len(chunks) else None
                if samples is None:
                    log.warning("Нет движка синтеза речи — текст только на экране")
                    time.sleep(min(4.0, len(chunks[i]) / 15))
                    continue
                if self.listener:
                    self.listener.mute(len(samples) / sr + 0.8)
                if not self.speaker.play(samples, sr, volume=volume):
                    break  # перебили
            if self.listener:
                self.listener.unmute()
                self.listener.mute(0.35)  # хвост эха
            if not self.listening:
                bus.emit("state", state="idle")
                self.player.unduck()

    def _exec_tts(self, chunk, emotion, whisper, lang) -> cf.Future:
        fut: cf.Future = cf.Future()

        def work():
            try:
                fut.set_result(self.tts.synth(chunk, emotion or "neutral", whisper, lang))
            except Exception as e:
                log.warning("TTS: %s", e)
                fut.set_result((None, 0))
        threading.Thread(target=work, daemon=True).start()
        return fut

    def notify(self, text: str, title: str | None = None, urgent: bool = False):
        self.notifier.send(text, title, urgent)
        bus.emit("notify", text=text, title=title, urgent=urgent)

    # ------------------------------------------------------------- сессии --
    def start_session(self, skill: Skill, handler, name: str, exit_words=None):
        self.session = SessionHandler(skill, handler, name, exit_words or (
            "хватит", "стоп", "выход", "выйди", "закончи", "закончим", "надоело", "конец"))
        log.info("Сессия: %s", name)

    def end_session(self):
        self.session = None

    # ------------------------------------------------------------ утилиты --
    def location(self) -> tuple[float, float, str]:
        a = self.cfg["assistant"]
        return float(a.get("latitude", 55.7558)), float(a.get("longitude", 37.6173)), a.get("city", "")

    def get_json(self, url: str, params=None, timeout: float = 10, retries: int = 1, **kw):
        """GET + JSON с одним повтором при таймауте/ошибке сервера."""
        last = None
        for attempt in range(retries + 1):
            try:
                r = self.http.get(url, params=params, timeout=timeout, **kw)
                if r.status_code >= 500 or r.status_code == 429:
                    last = requests.HTTPError(f"{r.status_code} {url}")
                    time.sleep(1.0 + attempt)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.Timeout, requests.ConnectionError) as e:
                last = e
                time.sleep(0.5)
        raise last


def strip_wake(text: str, wake_words) -> str:
    for w in wake_words:
        text = re.sub(rf"\b{re.escape(w)}\b[,!]?\s*", "", text, flags=re.I)
    return text.strip()
