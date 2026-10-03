"""Ассистент Стелла: связывает слух, речь, лицо, характер, память, навыки и ИИ."""
from __future__ import annotations

import concurrent.futures as cf
import importlib
import importlib.util
import inspect
import logging
import queue
import random
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

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
# «стоп» из веб-панели или Telegram должен заглушить Стеллу сразу, не дожидаясь очереди команд
QUICK_STOP = re.compile(r"^(?:стоп|хватит|замолчи|тихо|перестань|остановись|прекрати|помолчи|достаточно)"
                        r"(?: пожалуйста)?$")
# команды, которыми отвечают звенящему будильнику (остальные команды значат «я уже проснулся»)
RINGER_INTENTS = {"alarms.snooze", "alarms.delete_alarm", "alarms.cancel_timer", "system.stop_cmd"}


@dataclass
class Utterance:
    """Фраза в очереди речи. gen — «поколение»: interrupt_speech() отменяет всё, что поставлено раньше."""
    text: str
    emotion: str | None = None
    whisper: bool | None = None
    lang: str = "ru"
    gen: int = 0
    after: Callable[[bool], None] | None = None   # вызвать после (аргумент — «перебили»)
    done: threading.Event = field(default_factory=threading.Event)


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
        self.ringing = None             # звенящий будильник/таймер (Ringer: stop / snooze / silence / resume)
        self.last_rang = None           # (Ringer, время) — что звенело последним: «отключи будильник» после звонка
        self.last_intent = ""
        self.stop_event = threading.Event()
        self._exec = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="brain")
        # речь — в своём потоке: длинный ответ не держит очередь команд, а «стоп» и будильник его прерывают
        self._speech_q: queue.Queue[Utterance] = queue.Queue()
        self._speech_gen = 0
        self._speech_busy = False
        self._speech_cut = threading.Event()
        self._speech_thread = threading.Thread(target=self._speech_loop, daemon=True, name="speech")
        self._speech_thread.start()
        self.skills: list[Skill] = []
        self.intents = []
        self._load_skills()
        self._subs: list[tuple[str, Callable]] = []
        self._sub("touch", lambda **_: self._on_touch())
        self._sub("say", lambda text, emotion=None, **_: self.say(text, emotion=emotion, wait=False))
        self._sub("wake", lambda **_: self.on_wake(manual=True))
        self._sub("face_reset", lambda **_: self.mood.refresh())

    def _sub(self, topic: str, fn: Callable):
        self._subs.append((topic, bus.on(topic, fn)))

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
        for topic, fn in self._subs:
            bus.off(topic, fn)
        self.interrupt_speech()
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
    def on_wake(self, manual: bool = False):
        """«Стелла!» (или пробел на клавиатуре — manual): замолкаем, приглушаем музыку и слушаем."""
        log.info("Активатор!")
        self.mood.on_activity()
        self.interrupt_speech()  # перебили — замолкаем
        if self.ringing:
            # не выключаем: следом может прозвучать «отложи» или «выключи будильник»
            self.ringing.silence()
        self.listening = True
        self.player.duck()
        bus.emit("state", state="listening")
        if manual and self.listener:
            self.listener.listen_now()  # без этого команду без «Стелла» распознаватель бы пропустил
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
        if self.ringing and self.ringing.silenced:
            self.ringing.resume()  # позвали и ничего не сказали — будильник звенит дальше
        if not self.is_speaking():
            bus.emit("state", state=self.idle_state())
            self.player.unduck()

    def _on_touch(self):
        """Касание экрана выключает будильник или прерывает речь; иначе Стелла реагирует на прикосновение."""
        if self.ringing:
            self.ringing.stop()
        elif self.is_speaking():
            self.interrupt_speech()
        else:
            self.mood.on_touch()

    def idle_state(self) -> str:
        return "sleep" if self.mood.sleeping else "idle"

    # --------------------------------------------------------- обработка --
    def submit(self, text: str, source: str = "voice", whisper: bool = False, user=None, chat_id=None,
               speak: bool | None = None) -> cf.Future:
        if source != "voice" and QUICK_STOP.match(norm(text or "")):
            self.interrupt_speech()
            if self.ringing:
                self.ringing.stop()
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
        # будильник замолчал на «Стелла» и ждёт: «отложи», «стоп» — или любая другая команда, значит, проснулись
        ringer = self.ringing if source == "voice" and self.ringing and self.ringing.silenced else None
        self.last_intent = ""
        reply = None
        # 1. активная сессия (игра, рецепт, внешний навык); сценарии и другие Стеллы в неё не попадают
        sess = self.session
        if sess and sess.expired():
            log.info("Сессия «%s» закончилась по тишине", sess.name)
            self.session = sess = None
        if sess and depth == 0 and source not in ("scenario", "peer"):
            words = set(ctx.norm.split())
            if words & set(sess.exit_words) and len(words) <= 4:
                self.session = None
                reply = Reply("Хорошо, закончили.", emotion="neutral")
            else:
                reply = self.route(ctx, min_priority=90)  # «стоп», «отложи», грубость — важнее игры
                if reply is None:
                    sess.touch()
                    try:
                        reply = as_reply(sess.handler(ctx))
                    except Exception:
                        log.exception("Сессия %s упала", sess.name)
                        self.session = None
                        reply = None
                    if reply is not None:
                        self.last_intent = f"session.{sess.name}"
        # 2. навыки по шаблонам
        if reply is None:
            reply = self.route(ctx)
        # 3. ИИ-собеседник
        if reply is None:
            reply = self.think(ctx, depth)
        if ringer is not None and ringer.active and self.last_intent not in RINGER_INTENTS:
            ringer.stop(greet=False)
        if depth == 0:
            self.memory.add_dialog("user", text)
            if reply and reply.text:
                self.memory.add_dialog("assistant", reply.text)
        return reply or Reply(random.choice(UNKNOWN), emotion="sadness", expect_reply=True)

    def route(self, ctx: Context, min_priority: int | None = None) -> Reply | None:
        for it in self.intents:
            if min_priority is not None and it.priority < min_priority:
                break  # намерения отсортированы по приоритету
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
                    self.last_intent = it.name
                    return r
        return None

    def matches_intent(self, ctx: Context, exclude: Skill | None = None) -> bool:
        """Похожа ли фраза на команду какого-нибудь навыка (без выполнения). Нужна играм и уточнениям,
        чтобы «включи музыку» посреди игры в города не считалось ходом."""
        for it in self.intents:
            if it.skill is exclude:
                continue
            for pat in it.patterns:
                if pat.pattern not in (".", ".+", ".*") and pat.search(ctx.norm):
                    return True
        return False

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
        """Показать и озвучить ответ. Не ждёт конца речи: очередь команд свободна, пока Стелла говорит."""
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
        follow = source == "voice" and reply.expect_reply and self.listener is not None
        if speak and reply.speak and reply.text:
            after = (lambda cut: None if cut else self._follow_up()) if follow else None
            self.say(reply.text, emotion=emotion, whisper=reply.whisper, lang=reply.lang, wait=False, after=after)
        elif follow:
            self._follow_up()
        elif not self.listening and not self.is_speaking():
            bus.emit("state", state=self.idle_state())
            self.player.unduck()

    def _follow_up(self):
        """Стелла задала вопрос — слушаем ответ без «Стелла»."""
        self.listener.listen_now(float(self.cfg.get("assistant.follow_up_seconds", 6)))
        self.listening = True
        bus.emit("state", state="listening")
        self.player.duck()

    def say(self, text: str, emotion: str | None = None, whisper: bool | None = None, lang: str = "ru",
            wait: bool = True, after: Callable[[bool], None] | None = None):
        """Произнести текст (с анимацией рта). wait=False — не ждать окончания.
        Фразы встают в очередь и звучат по одной; interrupt_speech() обрывает текущую и всю очередь."""
        if not text:
            if after:
                after(False)
            return
        u = Utterance(text, emotion, whisper, lang, self._speech_gen, after)
        if threading.current_thread() is self._speech_thread:
            self._speak(u)  # вызов изнутри речи (из after) — без очереди, иначе ждали бы сами себя
            return
        self._speech_q.put(u)
        if wait:
            while not u.done.wait(0.5) and not self.stop_event.is_set():
                pass

    def interrupt_speech(self):
        """Замолчать сразу и выбросить всё, что ждёт очереди («стоп», касание, «Стелла», будильник)."""
        self._speech_gen += 1
        self._speech_cut.set()
        self.speaker.stop()

    def is_speaking(self) -> bool:
        return self._speech_busy or not self._speech_q.empty() or self.speaker.speaking

    def _speech_loop(self):
        while not self.stop_event.is_set():
            try:
                u = self._speech_q.get(timeout=0.5)
            except queue.Empty:
                continue
            self._speak(u)

    def _speak(self, u: Utterance):
        complete = False
        try:
            if u.gen == self._speech_gen:
                self._speech_busy = True
                complete = self._speak_chunks(u)
        except Exception:
            log.exception("Ошибка речи")
        finally:
            self._speech_busy = False
            if u.after:
                try:
                    u.after(not complete)
                except Exception:
                    log.exception("Ошибка после речи")
            if not self.listening and self._speech_q.empty():
                bus.emit("state", state=self.idle_state())
                self.player.unduck()
            u.done.set()

    def _speak_chunks(self, u: Utterance) -> bool:
        """-> True, если фраза прозвучала до конца (False — перебили)."""
        whisper = u.whisper
        if whisper is None:
            whisper = self.whisper_mode or self.last_whisper
        volume = float(self.cfg.get("tts.volume", 1.0))
        if whisper:
            volume *= 0.7
        elif self.mood.is_night():
            volume *= 0.65
        self._speech_cut.clear()
        if u.gen != self._speech_gen:
            return False
        log.info("%s: %s", self.name, u.text)
        bus.emit("subtitle", text=u.text, seconds=min(12.0, 2 + len(u.text) / 14))
        self.player.duck()
        bus.emit("state", state="speaking")
        chunks = split_for_tts(u.text, 230)
        nxt = self._exec_tts(chunks[0], u.emotion, whisper, u.lang) if chunks else None
        complete = False
        try:
            for i in range(len(chunks)):
                samples, sr = nxt.result() if nxt else (None, 0)
                nxt = self._exec_tts(chunks[i + 1], u.emotion, whisper, u.lang) if i + 1 < len(chunks) else None
                if u.gen != self._speech_gen:
                    return False
                if samples is None:
                    log.warning("Нет движка синтеза речи — текст только на экране")
                    if self._speech_cut.wait(min(4.0, len(chunks[i]) / 15)):
                        return False
                    continue
                if self.listener:
                    self.listener.mute(len(samples) / sr + 0.8)
                if u.gen != self._speech_gen or not self.speaker.play(samples, sr, volume=volume):
                    return False  # перебили
            complete = True
            return True
        finally:
            if self.listener:
                # дочитали — сбрасываем распознаватель (в нём эхо своей речи); перебили «Стеллой» — нет,
                # иначе потеряется команда, которую человек уже говорит
                self.listener.unmute(reset=complete)
                self.listener.mute(0.35)  # хвост эха

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
    def start_session(self, skill: Skill, handler, name: str, exit_words=None, timeout: float = 180):
        """Реплики идут сначала в handler (игра, рецепт, уточнение). Без реплик дольше timeout сессия
        заканчивается сама. handler возвращает None, если фраза не ему, — её разберут навыки."""
        self.session = SessionHandler(skill, handler, name, exit_words or (
            "хватит", "стоп", "выход", "выйди", "закончи", "закончим", "надоело", "конец"), timeout=timeout)
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
