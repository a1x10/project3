"""Будильники, таймеры, напоминания (по времени и «когда приду домой»), календарь (локальный + CalDAV)."""
from __future__ import annotations

import random
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta

from ..audio import dsp
from ..core.events import bus
from ..nlp.numbers import plural
from ..nlp.text import strip_words
from ..nlp.timeparse import (describe_duration, describe_dt, describe_repeat, parse_day, parse_duration,
                             parse_when, MONTHS_GEN, WEEKDAYS_NOM)
from .base import Reply, Skill, intent


class Ringer:
    """Звенящий будильник/таймер.

    «Стелла» — звонок замолкает (silence) и ждёт команду: «отложи» откладывает, «стоп» / «выключи будильник»
    выключает, любая другая команда тоже выключает (раз разговаривают — проснулись). Если после «Стелла»
    ничего не сказали, звонок продолжается (resume): случайное «Стелла» из телевизора не должно
    отменить будильник. Касание экрана выключает сразу. Сам звонок длится не дольше limit.
    """

    SILENCE_MAX = 45  # сколько секунд можно молчать после «Стелла», потом звонок продолжится
    MUSIC_WAIT = 6.0  # сколько ждать, пока заиграет музыка будильника, прежде чем звонить мелодией

    def __init__(self, skill: "Alarms", kind: str, label: str, music: bool = False):
        self.skill = skill
        self.a = skill.a
        self.kind = kind
        self.label = label
        self.music = music
        self._stop = threading.Event()
        self.snoozed = False
        self.greet = True
        self.silenced = False
        self._silenced_at = 0.0
        self._music_on = False

    @property
    def active(self) -> bool:
        return not self._stop.is_set()

    def start(self):
        self.a.interrupt_speech()  # будильник важнее недочитанной статьи
        self.a.ringing = self
        threading.Thread(target=self._run, daemon=True, name=f"ring-{self.kind}").start()

    def stop(self, greet: bool = True):
        """Выключить. greet=False — без утреннего приветствия (человек уже занят другой командой)."""
        self.greet = self.greet and greet
        self._stop.set()
        self.a.interrupt_speech()  # и «Подъём!», если его ещё договаривают
        if self.music:
            self.a.player.pause()

    def silence(self):
        """Замолчать на время команды после «Стелла», не выключая будильник."""
        self.silenced = True
        self._silenced_at = time.time()
        self.a.speaker.stop()

    def resume(self):
        if self.active and self.silenced:
            self.silenced = False
            if self._music_on:
                self.a.player.unduck()

    def snooze(self, minutes: int = 5):
        self.snoozed = True
        self.stop()
        return self.skill.snooze_alarm(self.label, minutes)

    def _run(self):
        a = self.a
        now = datetime.now()
        try:
            if self.kind == "alarm":
                bus.emit("emotion", name="joy", intensity=0.9, hold=20)
                a.mood.wake()
                intro = random.choice(["Подъём! Пора вставать!", "Доброе утро! Просыпайся!", "Время вставать, соня!"])
                a.say(f"{intro} Сейчас {now.hour}:{now.minute:02d}.", emotion="joy", whisper=False)
                limit = 10 * 60
                melody = dsp.alarm_melody(22050, 1)
            elif self.kind == "timer":
                bus.emit("emotion", name="surprise", intensity=1.0, hold=10)
                what = f" Таймер {self.label}." if self.label else ""
                a.say(f"Время вышло!{what}", emotion="surprise", whisper=False)
                limit = 2 * 60
                melody = dsp.timer_melody(22050)
            else:
                limit = 0
                melody = None
            t0 = time.time()
            if self.music and self.active and self._start_music():
                while self.active and time.time() - t0 < limit:
                    self._check_silence()
                    self._stop.wait(0.5)
            elif melody is not None:
                rep = 0
                while self.active and time.time() - t0 < limit:
                    if self._check_silence():
                        self._stop.wait(0.3)
                        continue
                    vol = min(1.0, 0.35 + 0.1 * rep)
                    a.speaker.play(melody, 22050, animate=False, volume=vol)
                    rep += 1
                    self._stop.wait(0.6)
        except Exception:
            self.skill.log.exception("Будильник")
        finally:
            if a.ringing is self:
                a.ringing = None
            a.last_rang = (self, time.time())
        if self.kind == "alarm" and not self.snoozed and self._stop.is_set() and self.greet:
            self.skill.morning_greeting()

    def _check_silence(self) -> bool:
        """-> True, пока звонок приглушён после «Стелла»."""
        if self.silenced and time.time() - self._silenced_at > self.SILENCE_MAX:
            self.resume()
        return self.silenced

    def _start_music(self) -> bool:
        """Будильник под музыку. Нет сети, mpv или токена — звоним обычной мелодией, а не молчим."""
        music = self.a.skill("music")
        if not music:
            return False
        try:
            music.play_default(quiet_start=True)
            deadline = time.time() + self.MUSIC_WAIT  # поток из сети стартует не сразу
            while time.time() < deadline:
                if self.a.player.is_playing():
                    self._music_on = True
                    return True
                if self._stop.wait(0.25):
                    return True
        except Exception as e:
            self.skill.log.warning("Будильник: музыка не включилась (%s) — звоню мелодией", e)
            return False
        self.skill.log.warning("Будильник: музыка не заиграла — звоню мелодией")
        return False


class Alarms(Skill):
    name = "alarms"

    def start(self):
        self.a.scheduler.every(1.0, self.check_due, "alarms")  # только база данных — быстро; звонок в своём потоке
        if self.cfg.get("presence.phone_ip"):
            self._home = None
            self._seen = []
            self.a.scheduler.every(float(self.cfg.get("presence.interval", 60)), self.check_presence, "presence",
                                   first_delay=10, threaded=True)

    # ------------------------------------------------------ срабатывание --
    def check_due(self):
        now = time.time()
        for al in self.a.memory.alarms():
            if al["kind"] == "presence" or al["due"] is None or al["due"] > now:
                continue
            late = now - al["due"]
            if al["repeat"]:
                nxt = datetime.fromtimestamp(al["due"]) + timedelta(days=1)
                while nxt.weekday() not in al["repeat"] or nxt.timestamp() <= now:
                    nxt += timedelta(days=1)
                self.a.memory.alarm_update(al["id"], due=nxt.timestamp())
            else:
                self.a.memory.alarm_delete(al["id"])
            if late > 3600 and al["kind"] != "reminder":
                continue  # Стелла была выключена — старые будильники не звоним
            self.fire(al)

    def fire(self, al: dict):
        kind, label = al["kind"], al["label"] or ""
        self.log.info("Срабатывание %s: %s", kind, label)
        if kind == "reminder":
            # в своём потоке: планировщик не должен ждать, пока Стелла договорит
            threading.Thread(target=self._remind_aloud, args=(label,), daemon=True, name="reminder").start()
            return
        if self.a.ringing:
            self.a.ringing.stop(greet=False)
        Ringer(self, kind, label, music=bool(al["extra"].get("music"))).start()
        if kind == "timer":
            self.a.notify(f"Таймер {label} сработал".strip(), title="⏱ Таймер")

    def _remind_aloud(self, label: str):
        self.a.notify(label, title="⏰ Напоминание")
        bus.emit("emotion", name="interest", intensity=1.0, hold=10)
        self.a.mood.wake()
        self.a.interrupt_speech()  # напоминание важнее недочитанного ответа
        self.a.speaker.play(dsp.beep("listen"), 22050, False, 0.8)
        self.a.say(f"Напоминаю: {label}.", emotion="interest", whisper=False)

    def snooze_alarm(self, label: str, minutes: int) -> float:
        due = time.time() + minutes * 60
        self.a.memory.alarm_add("alarm", due, label or "отложенный будильник", extra={"snoozed": True})
        return due

    def _recent_ringer(self, kind: str, seconds: float):
        """Будильник/таймер, который звенит сейчас или выключен не больше seconds назад."""
        if self.a.ringing and self.a.ringing.kind == kind:
            return self.a.ringing
        last = getattr(self.a, "last_rang", None)
        if last and last[0].kind == kind and time.time() - last[1] < seconds:
            return last[0]
        return None

    def morning_greeting(self):
        weather = self.a.skill("weather")
        text = ""
        if weather:
            try:
                text = weather.short_today()
            except Exception:
                text = ""
        events = self.today_events_text()
        msg = " ".join(x for x in (text, events) if x)
        if msg:
            self.a.say(msg, emotion="joy")

    # ---------------------------------------------------------- будильники --
    @intent(r"\b(?:разбуди|подними) меня\b|\b(?:поставь|заведи|установи|включи|создай|сделай)\s+будильник\w*|"
            r"^будильник на\b|\bбудильник (?:на|в) \d", priority=70)
    def set_alarm(self, ctx):
        # «будильник на 10 минут», «на полчаса» — время от текущего момента («на 7 часов» — это 7:00)
        rel = re.search(r"\bна\s+(?:\d+\s+)?(?:минут\w*|мин)\b|\bна\s+(?:полчаса|полтора часа)\b", ctx.norm)
        if rel and not re.search(r"\b\d{1,2}:\d{2}\b|\b(?:утра|вечера|дня|ночи)\b", ctx.norm):
            sec, _ = parse_duration(ctx.norm[rel.start():])
            if sec:
                due = time.time() + sec
                self.a.memory.alarm_add("alarm", due, "")
                at = datetime.fromtimestamp(due)
                return Reply(f"Будильник прозвенит через {describe_duration(sec)}, в {at.hour}:{at.minute:02d}.",
                             emotion="confidence", intensity=0.6)
        when = parse_when(ctx.text, prefer="morning", default_time=datetime.now().time())
        if not when or not when.has_time:
            self.a.start_session(self, self._alarm_followup, "будильник: время")
            return Reply("На какое время поставить будильник?", expect_reply=True, emotion="interest")
        music = bool(re.search(r"\bпод музык\w*|\bс музык\w*|\bпод песн\w*", ctx.norm))
        return self._create_alarm(when, music)

    def _alarm_followup(self, ctx):
        self.a.end_session()
        when = parse_when(ctx.text, prefer="morning")
        if not when or not when.has_time:
            if self.a.matches_intent(ctx, exclude=self):
                return None  # ответили другой командой — пусть её выполнят
            return Reply("Не поняла время. Скажи, например: «разбуди меня в 7 утра».", emotion="sadness")
        return self._create_alarm(when, False)

    def _create_alarm(self, when, music: bool):
        due = when.dt.timestamp()
        self.a.memory.alarm_add("alarm", due, "", repeat=when.repeat, extra={"music": music} if music else None)
        rep = describe_repeat(when.repeat)
        hm = f"{when.dt.hour}:{when.dt.minute:02d}"
        if rep:
            return Reply(f"Будильник на {hm} {rep} поставлен.", emotion="confidence", intensity=0.6)
        left = describe_duration(due - time.time() + 30)
        return Reply(f"Будильник поставлен на {describe_dt(when.dt)}. Это через {left}.",
                     emotion="confidence", intensity=0.6)

    @intent(r"\b(?:какие|мои|список|покажи|все) будильник\w*|\bна (?:сколько|какое время) (?:стоит|поставлен|заведен) "
            r"будильник|\bесть ли будильник|\bкогда (?:сработает|прозвенит) будильник", priority=71)
    def list_alarms(self, ctx):
        al = self.a.memory.alarms("alarm")
        if not al:
            return Reply("Будильников нет.")
        parts = []
        for x in al[:6]:
            dt = datetime.fromtimestamp(x["due"])
            rep = describe_repeat(x["repeat"])
            parts.append(f"на {dt.hour}:{dt.minute:02d} {rep}".strip() if rep else describe_dt(dt))
        n = len(al)
        return Reply(f"{n} {plural(n, 'будильник', 'будильника', 'будильников')}: " + ", ".join(parts) + ".")

    @intent(r"\b(?:удали|отмени|отключи|выключи|убери|сними|сбрось)\s+(?:все\s+)?будильник\w*", priority=72)
    def delete_alarm(self, ctx):
        explicit = re.search(r"\bвсе\b|\d", ctx.norm)
        if self.a.ringing and self.a.ringing.kind == "alarm" and not explicit:
            self.a.ringing.stop()  # «выключи будильник», пока звенит, — выключить звонок, а не удалить будильник
            return Reply("", speak=False)
        if not explicit and self._recent_ringer("alarm", 600):
            # только что прозвенел: постоянный будильник не удаляем, а отложенный — отменяем
            snoozed = [x for x in self.a.memory.alarms("alarm") if x["extra"].get("snoozed")]
            for x in snoozed:
                self.a.memory.alarm_delete(x["id"])
            return Reply("Хорошо, больше не разбужу." if snoozed else "Будильник уже выключен.", emotion="neutral")
        alarms = self.a.memory.alarms("alarm")
        if not alarms:
            return Reply("Будильников и так нет.")
        if re.search(r"\bвсе\b", ctx.norm) or len(alarms) == 1:
            for x in alarms:
                self.a.memory.alarm_delete(x["id"])
            return Reply("Все будильники удалены." if len(alarms) > 1 else "Будильник удалён.")
        when = parse_when(ctx.text, prefer="morning")
        if when and when.has_time:
            hm = (when.dt.hour, when.dt.minute)
            hit = [x for x in alarms if (datetime.fromtimestamp(x["due"]).hour,
                                         datetime.fromtimestamp(x["due"]).minute) == hm]
            for x in hit:
                self.a.memory.alarm_delete(x["id"])
            if hit:
                return Reply(f"Будильник на {hm[0]}:{hm[1]:02d} удалён.")
            return Reply(f"Будильника на {hm[0]}:{hm[1]:02d} нет.")
        return Reply("Какой именно? Скажи время или «удали все будильники».", expect_reply=True)

    @intent(r"\b(?:отложи|разбуди позже|дай поспать|еще (?:\d+ )?минут\w*|еще немного)\b", priority=95)
    def snooze(self, ctx):
        ringer = self._recent_ringer("alarm", 120)  # звенит или выключили только что («ой, отложи»)
        if ringer is None:
            return None
        sec, _ = parse_duration(ctx.text)
        minutes = max(1, int((sec or 300) / 60))
        if ringer.active:
            ringer.snooze(minutes)
        elif not ringer.snoozed:
            ringer.snoozed = True
            self.snooze_alarm(ringer.label, minutes)
        else:
            return None
        return Reply(f"Хорошо, разбужу через {minutes} {plural(minutes, 'минуту', 'минуты', 'минут')}.",
                     emotion="love", intensity=0.5, whisper=True)

    # ------------------------------------------------------------ таймеры --
    @intent(r"^(?!.*\b(?:удали|отмени|сбрось|выключи|останови|отключи|убери|сколько)\b).*?"
            r"\b(?:поставь|заведи|установи|засеки|запусти|включи|начни)?\s*таймер\w*\b|^засеки\b", priority=69)
    def set_timer(self, ctx):
        sec, rest = parse_duration(ctx.text)
        if not sec:
            self.a.start_session(self, self._timer_followup, "таймер: время")
            return Reply("На сколько поставить таймер?", expect_reply=True, emotion="interest")
        label = strip_words(rest, "поставь", "заведи", "установи", "засеки", "запусти", "включи", "начни",
                            "таймер", "таймера", "пожалуйста", "мне", "на")
        return self._create_timer(sec, label)

    def _timer_followup(self, ctx):
        self.a.end_session()
        sec, _ = parse_duration(ctx.text)
        if not sec:
            if self.a.matches_intent(ctx, exclude=self):
                return None
            return Reply("Не поняла. Скажи, например: «таймер на 5 минут».", emotion="sadness")
        return self._create_timer(sec, "")

    def _create_timer(self, sec: int, label: str):
        self.a.memory.alarm_add("timer", time.time() + sec, label)
        what = f" {label}" if label else ""
        return Reply(f"Засекла {describe_duration(sec)}{what}.", emotion="confidence", intensity=0.5)

    @intent(r"\bсколько (?:\w+ )?(?:осталось|еще|времени осталось)\b|\bсколько\b.*\bтаймер\w*", priority=70)
    def timer_left(self, ctx):
        if "таймер" not in ctx.norm and len(ctx.norm.split()) > 3:
            return None  # «сколько осталось до нового года» — не про таймер
        timers = self.a.memory.alarms("timer")
        if not timers:
            return None if "таймер" not in ctx.norm else Reply("Таймер не запущен.")
        parts = []
        for x in timers[:3]:
            left = describe_duration(x["due"] - time.time())
            parts.append(f"{x['label'] + ': ' if x['label'] else ''}{left}")
        return Reply("Осталось " + "; ".join(parts) + ".")

    @intent(r"\b(?:удали|отмени|сбрось|выключи|останови|отключи|убери)\s+(?:все\s+)?таймер\w*", priority=72)
    def cancel_timer(self, ctx):
        if self.a.ringing and self.a.ringing.kind == "timer":
            self.a.ringing.stop()
            return Reply("", speak=False)
        timers = self.a.memory.alarms("timer")
        for x in timers:
            self.a.memory.alarm_delete(x["id"])
        return Reply("Таймер отменён." if timers else "Таймер и так не запущен.")

    # -------------------------------------------------------- напоминания --
    @intent(r"\bнапомни\w*\b(?!.*\b(?:какие|список)\b)", priority=67)
    def remind(self, ctx):
        t = ctx.norm
        presence = None
        m = re.search(r"\bкогда (?:я )?(?:приду|вернусь|буду|окажусь|доберусь) домой\b", t)
        if m:
            presence = "arrive"
        m2 = re.search(r"\bкогда (?:я )?(?:уйду|выйду|буду уходить|соберусь уходить) (?:из дома|из дому|на работу)?",
                       t)
        if m2:
            presence = "leave"
        text = re.sub(r"\bнапомни\w*\b|\bмне\b|\bпожалуйста\b|\bо том что\b|\bчто\b(?= нужно| надо)", " ", t)
        if presence:
            text = re.sub(r"\bкогда (?:я )?(?:приду|вернусь|буду|окажусь|доберусь) домой\b|"
                          r"\bкогда (?:я )?(?:уйду|выйду|буду уходить|соберусь уходить)(?: из дома| из дому| на работу)?",
                          " ", text)
            text = re.sub(r"\s+", " ", text).strip(" ,")
            if not self.cfg.get("presence.phone_ip"):
                return Reply("Для напоминаний «когда приду домой» укажите IP телефона в настройках (presence.phone_ip): "
                             "я пойму, что ты дома, когда телефон подключится к домашнему Wi-Fi.", emotion="sadness")
            self.a.memory.alarm_add("presence", None, text, extra={"presence": presence})
            where = "когда придёшь домой" if presence == "arrive" else "когда будешь уходить"
            return Reply(f"Хорошо, напомню {where}: {text}.", emotion="confidence", intensity=0.5)
        when = parse_when(text, prefer="nearest")
        if not when:
            self.a.start_session(self, lambda c, txt=text.strip(): self._remind_followup(c, txt), "напоминание: время")
            return Reply("Когда напомнить?", expect_reply=True, emotion="interest")
        what = re.sub(r"^(?:о|об|про|чтобы|что)\s+", "", when.rest.strip(" ,")) or "то, о чём ты просил"
        return self._create_reminder(when, what)

    def _remind_followup(self, ctx, what):
        self.a.end_session()
        when = parse_when(ctx.text, prefer="nearest")
        if not when:
            if self.a.matches_intent(ctx, exclude=self):
                return None
            return Reply("Не поняла время, давай ещё раз.", emotion="sadness")
        return self._create_reminder(when, what or when.rest or "напоминание")

    def _create_reminder(self, when, what):
        if not when.has_time and not when.relative and when.dt.timestamp() <= time.time() + 60:
            # «напомни сегодня позвонить маме» вечером: утреннее время по умолчанию уже прошло
            self.a.start_session(self, lambda c, w=what: self._remind_time_followup(c, w, when), "напоминание: время",
                                 timeout=60)
            return Reply("Во сколько напомнить?", expect_reply=True, emotion="interest")
        self.a.memory.alarm_add("reminder", when.dt.timestamp(), what, repeat=when.repeat)
        rep = describe_repeat(when.repeat)
        if when.relative:
            return Reply(f"Напомню через {describe_duration(when.dt.timestamp() - time.time())}: {what}.",
                         emotion="confidence", intensity=0.5)
        return Reply(f"Напомню {rep + ' в ' + f'{when.dt.hour}:{when.dt.minute:02d}' if rep else describe_dt(when.dt)}: "
                     f"{what}.", emotion="confidence", intensity=0.5)

    def _remind_time_followup(self, ctx, what, day_when):
        self.a.end_session()
        when = parse_when(ctx.text, prefer="nearest")
        if not when or not when.has_time:
            if self.a.matches_intent(ctx, exclude=self):
                return None
            return Reply("Не поняла время, давай ещё раз: «напомни в 7 вечера …».", emotion="sadness")
        dt = datetime.combine(day_when.dt.date(), when.dt.time())
        if dt.timestamp() <= time.time():
            dt = when.dt  # «в 9» уже прошло сегодня — parse_when сам выбрал ближайшее
        when.dt = dt
        return self._create_reminder(when, what)

    @intent(r"\b(?:какие|мои|список|покажи|все) напоминани\w*|\bо ч[её]м (?:ты )?(?:должна |хотела )?напомнить",
            priority=71)
    def list_reminders(self, ctx):
        rem = self.a.memory.alarms("reminder") + self.a.memory.alarms("presence")
        if not rem:
            return Reply("Напоминаний нет.")
        parts = []
        for x in rem[:6]:
            if x["kind"] == "presence":
                parts.append(f"когда придёшь домой — {x['label']}" if x["extra"].get("presence") == "arrive"
                             else f"когда будешь уходить — {x['label']}")
            else:
                parts.append(f"{describe_dt(datetime.fromtimestamp(x['due']))} — {x['label']}")
        return Reply("Напоминания: " + "; ".join(parts) + ".", card="\n".join(parts))

    @intent(r"\b(?:удали|отмени|убери|сотри)\s+(?:все\s+)?напоминани\w*", priority=72)
    def delete_reminders(self, ctx):
        rem = self.a.memory.alarms("reminder") + self.a.memory.alarms("presence")
        if not rem:
            return Reply("Напоминаний нет.")
        if re.search(r"\bвсе\b", ctx.norm) or len(rem) == 1:
            for x in rem:
                self.a.memory.alarm_delete(x["id"])
            return Reply("Напоминания удалены.")
        from ..nlp.text import best_match
        q = re.sub(r"\b(?:удали|отмени|убери|сотри|напоминани\w*|про|о)\b", " ", ctx.norm).strip()
        best, _ = best_match(q, rem, key=lambda x: x["label"], threshold=0.4)
        if best:
            self.a.memory.alarm_delete(best["id"])
            return Reply(f"Удалила напоминание: {best['label']}.")
        return Reply("Какое напоминание удалить?", expect_reply=True)

    # ----------------------------------------------- «когда приду домой» --
    def _phone_home(self) -> bool:
        ip = self.cfg.get("presence.phone_ip")
        try:
            if subprocess.run(["ping", "-c", "1", "-W", "2", ip], capture_output=True, timeout=5).returncode == 0:
                return True
            out = subprocess.run(["ip", "neigh", "show", ip], capture_output=True, text=True, timeout=3).stdout
            return any(s in out for s in ("REACHABLE", "DELAY", "PROBE"))
        except Exception:
            return False

    def check_presence(self):
        home = self._phone_home()
        self._seen = (self._seen + [home])[-3:]
        # телефоны «засыпают» в Wi-Fi: считаем, что ушёл, только после трёх пропусков подряд;
        # один-два пропуска — «непонятно» (None), а не «ушёл»
        stable = True if home else (False if len(self._seen) == 3 and not any(self._seen) else None)
        if self._home is None:
            self._home = stable if not home else True
            return
        if home and not self._home:
            self._home = True
            self._presence_event("arrive")
        elif stable is False and self._home:
            self._home = False
            self._presence_event("leave")

    def _presence_event(self, kind):
        self.log.info("Присутствие: %s", kind)
        bus.emit("presence", state=kind)
        for x in self.a.memory.alarms("presence"):
            if x["extra"].get("presence") == kind:
                self.a.memory.alarm_delete(x["id"])
                if kind == "arrive":
                    self.a.say(f"С возвращением! Ты просил напомнить: {x['label']}.", emotion="joy")
                self.a.notify(x["label"], title="📍 Напоминание")

    # ------------------------------------------------------------ календарь --
    def _caldav(self):
        if not (self.cfg.get("calendar.username") and self.cfg.get("calendar.password")):
            return None
        try:
            from caldav import DAVClient
            client = DAVClient(url=self.cfg.get("calendar.caldav_url"), username=self.cfg.get("calendar.username"),
                               password=self.cfg.get("calendar.password"))
            principal = client.get_principal()
            cals = principal.get_calendars()
            return cals[0] if cals else None
        except Exception as e:
            self.log.warning("CalDAV недоступен: %s", e)
            return None

    @intent(r"\b(?:создай|добавь|запиши|поставь|занеси|запланируй)\b.*\b(?:событие|встреч\w*|в календарь|в ежедневник|"
            r"мероприятие)\b|\bзапиши меня (?:к|на)\b", priority=66)
    def add_event(self, ctx):
        when = parse_when(ctx.text, prefer="nearest")
        if not when:
            return Reply("На какое время записать? Скажи, например: «встреча завтра в 15».", emotion="interest")
        title = strip_words(when.rest, "создай", "добавь", "запиши", "поставь", "занеси", "запланируй", "событие",
                            "в календарь", "в ежедневник", "мероприятие", "меня", "мне", "пожалуйста") or "событие"
        title = re.sub(r"^(?:на|о|про)\s+", "", title)
        start = when.dt
        end = start + timedelta(hours=1)
        uid = None
        synced = False
        cal = self._caldav()
        if cal is not None:
            try:
                ev = cal.add_event(dtstart=start.astimezone(), dtend=end.astimezone(), summary=title)
                uid = str(getattr(ev, "id", "") or "")
                synced = True
            except Exception as e:
                self.log.warning("CalDAV: %s", e)
        self.a.memory.event_add(start.timestamp(), end.timestamp(), title, uid, synced)
        # напоминание за 15 минут
        remind_at = start - timedelta(minutes=15)
        if remind_at > datetime.now():
            self.a.memory.alarm_add("reminder", remind_at.timestamp(), f"через 15 минут {title}")
        sync = " и в календарь Яндекса" if synced else ""
        return Reply(f"Записала{sync}: {title}, {describe_dt(start)}.", emotion="confidence", intensity=0.5)

    def events_for(self, day) -> list[tuple[datetime, str]]:
        a = datetime.combine(day, datetime.min.time())
        b = a + timedelta(days=1)
        out = [(datetime.fromtimestamp(e["start"]), e["title"]) for e in
               self.a.memory.events_between(a.timestamp(), b.timestamp()) if not e["synced"]]
        cal = self._caldav()
        if cal is not None:
            try:
                for ev in cal.search(start=a.astimezone(), end=b.astimezone(), event=True, expand=True):
                    c = ev.component
                    st = c.start
                    if not isinstance(st, datetime):
                        st = datetime.combine(st, datetime.min.time())
                    out.append((st.replace(tzinfo=None) if st.tzinfo is None else st.astimezone().replace(tzinfo=None),
                                str(c.get("SUMMARY", "событие"))))
            except Exception as e:
                self.log.warning("CalDAV: %s", e)
        else:
            out = [(datetime.fromtimestamp(e["start"]), e["title"]) for e in
                   self.a.memory.events_between(a.timestamp(), b.timestamp())]
        return sorted(out)

    def today_events_text(self) -> str:
        ev = self.events_for(datetime.now().date())
        if not ev:
            return ""
        return "Сегодня в планах: " + ", ".join(f"в {d.hour}:{d.minute:02d} {t}" for d, t in ev[:4]) + "."

    @intent(r"\b(?:что|какие)\b.*\b(?:в календаре|в планах|запланировано|событи\w*|встреч\w*|дела)\b|"
            r"\bмое расписание\b|\bчто у меня (?:сегодня|завтра|послезавтра|в \w+)\b", priority=64)
    def what_planned(self, ctx):
        day, _ = parse_day(ctx.text)
        day = day or datetime.now().date()
        ev = self.events_for(day)
        when = "сегодня" if day == datetime.now().date() else \
            "завтра" if day == datetime.now().date() + timedelta(days=1) else \
            f"{WEEKDAYS_NOM[day.weekday()]}, {day.day} {MONTHS_GEN[day.month - 1]}"
        if not ev:
            return Reply(f"На {when} ничего не запланировано." if when in ("сегодня", "завтра")
                         else f"{when.capitalize()} — ничего не запланировано.", emotion="neutral")
        items = [f"в {d.hour}:{d.minute:02d} — {t}" for d, t in ev]
        return Reply(f"{when.capitalize()}: " + "; ".join(items) + ".", card="\n".join(items))
