"""Телевизор: умный дом Яндекса (ТВ и ТВ-приставки), HDMI-CEC прямо с Raspberry Pi (любой ТВ)
и ADB для Android TV / Яндекс ТВ (поиск фильмов, пульт)."""
from __future__ import annotations

import random
import shutil
import subprocess

from ..nlp.numbers import words_to_number
from .base import Reply, Skill, intent

ADB_KEYS = {"home": 3, "back": 4, "up": 19, "down": 20, "left": 21, "right": 22, "ok": 23, "vol_up": 24,
            "vol_down": 25, "power": 26, "mute": 164, "play_pause": 85, "play": 126, "pause": 127, "stop": 86,
            "next": 87, "prev": 88, "ch_up": 166, "ch_down": 167, "wakeup": 224, "sleep": 223}
MOVIES = ["«Интерстеллар»", "«Остров проклятых»", "«Легенда № 17»", "«Король Лев»", "«Начало»", "«Брат»",
          "«Москва слезам не верит»", "«Головоломка»", "«Зелёная миля»", "«Иван Васильевич меняет профессию»"]


class TV(Skill):
    name = "tv"

    # ---------------------------------------------------------------- CEC --
    def cec(self, *args) -> bool:
        if not (self.cfg.get("tv.cec", True) and shutil.which("cec-ctl")):
            return False
        dev = self.cfg.get("tv.cec_device", "/dev/cec0")
        try:
            subprocess.run(["cec-ctl", "-d", dev, "--playback", "-o", "Stella"], capture_output=True, timeout=5)
            r = subprocess.run(["cec-ctl", "-d", dev, *args], capture_output=True, text=True, timeout=8)
            return r.returncode == 0
        except Exception as e:
            self.log.warning("CEC: %s", e)
            return False

    def cec_key(self, ui_cmd: str, times: int = 1) -> bool:
        ok = False
        for _ in range(times):
            ok = self.cec("--to", "0", "--user-control-pressed", f"ui-cmd={ui_cmd}", "--user-control-released") or ok
        return ok

    # ---------------------------------------------------------------- ADB --
    def adb(self, *shell_args) -> bool:
        host = self.cfg.get("tv.adb_host")
        if not host or not shutil.which("adb"):
            return False
        target = host if ":" in host else f"{host}:5555"
        try:
            subprocess.run(["adb", "connect", target], capture_output=True, timeout=8)
            r = subprocess.run(["adb", "-s", target, "shell", *shell_args], capture_output=True, text=True, timeout=10)
            return r.returncode == 0
        except Exception as e:
            self.log.warning("ADB: %s", e)
            return False

    def adb_key(self, name: str, times: int = 1) -> bool:
        ok = False
        for _ in range(times):
            ok = self.adb("input", "keyevent", str(ADB_KEYS[name])) or ok
        return ok

    # ------------------------------------------------------ умный дом Яндекса --
    def iot_tv(self):
        sh = self.a.skill("smarthome")
        if not (sh and sh.configured):
            return None, None
        name = self.cfg.get("tv.iot_name")
        devs = sh.find(name) if name else sh.find("телевизор")
        devs = [d for d in devs if "media_device" in d.type or d.domain == "media_player"]
        return (sh, devs) if devs else (None, None)

    def _none(self):
        return Reply("Телевизор не подключён: нужен HDMI-кабель от Raspberry Pi (HDMI-CEC), ADB для Android TV "
                     "или телевизор в умном доме Яндекса.", emotion="sadness", intensity=0.5)

    # ------------------------------------------------------------- команды --
    @intent(r"^(?:включи|выключи|отключи|вруби|выруби)\s+(?:телевизор|телек|тв|телевидение)\b", priority=52)
    def power(self, ctx):
        on = ctx.norm.split()[0] in ("включи", "вруби")
        sh, devs = self.iot_tv()
        if devs:
            try:
                sh.switch(devs, on)
                return Reply("Включаю телевизор." if on else "Выключаю телевизор.", emotion="confidence", intensity=0.4)
            except Exception as e:
                self.log.warning("ТВ через умный дом: %s", e)
        ok = self.cec("--to", "0", "--image-view-on") if on else self.cec("--to", "0", "--standby")
        if on and ok:
            self.cec("--active-source", "phys-addr=1.0.0.0")
        if not ok:
            ok = self.adb_key("wakeup" if on else "sleep")
        if not ok:
            return self._none()
        return Reply("Включаю телевизор." if on else "Выключаю телевизор.", emotion="confidence", intensity=0.4)

    @intent(r"\b(?:телевизор\w*|телек\w*|на тв)\b.*\b(громче|тише|выключи звук|без звука|включи звук)\b|"
            r"\b(громче|тише|выключи звук|включи звук)\b.*\b(?:на |у )?(?:телевизор\w*|телек\w*|тв)\b", priority=53)
    def volume(self, ctx):
        n = ctx.norm
        up = "громче" in n
        mute = "выключи звук" in n or "без звука" in n
        steps = 3
        sh, devs = self.iot_tv()
        if devs:
            try:
                if mute:
                    sh.ya.act([d.id for d in devs if d.backend == "yandex"],
                              [{"type": "devices.capabilities.toggle", "state": {"instance": "mute", "value": True}}])
                else:
                    sh.set_range(devs, "volume", steps if up else -steps, relative=True)
                return Reply("", speak=False)
            except Exception as e:
                self.log.warning("ТВ громкость: %s", e)
        cmd = "mute" if mute else ("volume-up" if up else "volume-down")
        ok = self.cec_key(cmd, 1 if mute else steps) or self.adb_key("mute" if mute else ("vol_up" if up else "vol_down"),
                                                                   1 if mute else steps)
        return Reply("", speak=False) if ok else self._none()

    @intent(r"\b(?:переключи|включи|поставь)\s+(?:на\s+)?(\d+|первый|второй|третий|четвертый|пятый)\s+канал\b|"
            r"\bканал\s+(\d+)\b|\b(следующий|предыдущий) канал\b", priority=53)
    def channel(self, ctx):
        n = ctx.norm
        sh, devs = self.iot_tv()
        rel = "следующий" in n or "предыдущий" in n
        num = None if rel else words_to_number(n)
        if devs:
            try:
                if rel:
                    sh.set_range(devs, "channel", 1 if "следующий" in n else -1, relative=True)
                else:
                    sh.set_range(devs, "channel", int(num))
                return Reply("", speak=False)
            except Exception as e:
                self.log.warning("ТВ канал: %s", e)
        if rel:
            ok = self.cec_key("channel-up" if "следующий" in n else "channel-down") or \
                self.adb_key("ch_up" if "следующий" in n else "ch_down")
        else:
            ok = self.adb("input", "text", str(int(num))) if num is not None else False
        return Reply("", speak=False) if ok else self._none()

    @intent(r"\b(?:найди|включи|покажи|открой)\s+(?:фильм|сериал|мультфильм|мультик|кино)\s+(.+?)(?:\s+на (?:телевизоре|тв))?$",
            priority=54)
    def find_movie(self, ctx):
        title = ctx.raw_group(1)
        ok = self.adb("am", "start", "-a", "android.search.action.GLOBAL_SEARCH", "--es", "query", f"'{title}'")
        if ok:
            return Reply(f"Ищу «{title}» на телевизоре.", emotion="joy", intensity=0.5)
        if not self.cfg.get("tv.adb_host"):
            return Reply("Для поиска фильмов на телевизоре включите отладку по сети на Android TV или Яндекс ТВ "
                         "и укажите его IP в настройках (tv.adb_host).", emotion="sadness", intensity=0.5)
        return Reply("Телевизор не ответил. Он включён?", emotion="sadness")

    @intent(r"\b(?:пауза|останови|продолжи|воспроизведи|play)\b.*\b(?:на )?(?:телевизор\w*|тв)\b", priority=53)
    def playback(self, ctx):
        ok = self.adb_key("play_pause") or self.cec_key("pause" if "пауз" in ctx.norm or "останов" in ctx.norm
                                                         else "play")
        return Reply("", speak=False) if ok else self._none()

    @intent(r"\b(?:что посмотреть|посоветуй (?:фильм|сериал|что посмотреть|кино)|какой фильм посмотреть)\b",
            priority=50, fun=True)
    def recommend(self, ctx):
        if self.a.brain.available:
            th = self.a.brain.think(ctx.text + ". Посоветуй 2–3 фильма с одной фразой о каждом.")
            if th.text:
                return Reply(th.text, emotion=th.emotion or "interest")
        pick = random.sample(MOVIES, 2)
        return Reply(f"Посмотри {pick[0]} или {pick[1]}. Хочешь, найду на телевизоре?", emotion="interest",
                     expect_reply=True)
