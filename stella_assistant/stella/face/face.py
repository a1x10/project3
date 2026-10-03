"""Живое лицо Стеллы: окно pygame, моргание, бегающий взгляд, плавные эмоции.

Face работает в главном потоке (так требует SDL), остальные потоки управляют им
через потокобезопасные методы set_emotion / set_state / set_speech_level или через
события шины (emotion, state, speech_level, mic_level, gaze, subtitle, info).
"""
from __future__ import annotations

import io
import logging
import math
import os
import random
import threading
import time

from ..core.events import bus
from .emotions import PRESETS, FaceParams, preset, resolve
from .renderer import AnimState, FaceRenderer

log = logging.getLogger("stella.face")


class Face:
    def __init__(self, cfg, headless: bool = False):
        d = cfg["display"]
        self.cfg = cfg
        self.size = (int(d["width"]), int(d["height"]))
        self.fps = int(d.get("fps", 30))
        self.headless = headless or not d.get("enabled", True)
        self.fullscreen = bool(d.get("fullscreen", True))
        self.hide_cursor = bool(d.get("hide_cursor", True))
        self.backend = d.get("backend", "pygame")
        self._lock = threading.RLock()
        self.params = preset("neutral")
        self.anim = AnimState()
        # что сейчас показываем
        self.mood = ("neutral", 1.0)            # фоновое настроение (от EmotionEngine)
        self.transient = None                   # (имя, сила, до какого времени)
        self.state = "idle"                     # idle / listening / thinking / speaking / sleep
        self.gaze_override = None               # (x, y, до какого времени)
        self.extra = {}                         # доп. параметры поверх эмоции (anger_mark …)
        # анимация
        self._gaze = [0.0, 0.0]
        self._gaze_target = [0.0, 0.0]
        self._next_saccade = 0.0
        self._next_blink = time.time() + 2.0
        self._blink_start = None
        self._blink_len = 0.16
        self._double_blink = False
        self._yawn_start = None
        self._next_yawn = time.time() + 20
        self._speech_target = 0.0
        self._mic_target = 0.0
        self._subtitle_until = 0.0
        self._jpeg = None
        self._jpeg_wanted_until = 0.0
        self._jpeg_last = 0.0
        self.demo = False
        self.screen = None
        self.renderer = None
        self._luma = None
        bus.on("emotion", lambda name, intensity=1.0, hold=None, **_: self.set_emotion(name, intensity, hold))
        bus.on("state", lambda state, **_: self.set_state(state))
        bus.on("speech_level", lambda level, **_: self.set_speech_level(level))
        bus.on("mic_level", lambda level, **_: self.set_mic_level(level))
        bus.on("gaze", lambda x, y, hold=2.5, **_: self.look_at(x, y, hold))
        bus.on("subtitle", lambda text, seconds=4.0, **_: self.set_subtitle(text, seconds))
        bus.on("info", lambda text, **_: self.set_info(text))
        bus.on("mood", lambda name, intensity=1.0, extra=None, **_: self.set_mood(name, intensity, extra))

    # ------------------------------------------------- потокобезопасное API --
    def set_emotion(self, name: str, intensity: float = 1.0, hold: float | None = None):
        name = resolve(name)
        if hold is None:
            hold = 6.0 if name in ("surprise", "fear") else 9.0
        with self._lock:
            if name == "neutral":
                self.transient = None
            else:
                self.transient = (name, max(0.0, min(1.0, intensity)), time.time() + hold)
        log.debug("эмоция: %s %.2f на %.1f с", name, intensity, hold)

    def set_mood(self, name: str, intensity: float = 1.0, extra: dict | None = None):
        with self._lock:
            self.mood = (resolve(name), intensity)
            self.extra = dict(extra or {})

    def set_state(self, state: str):
        with self._lock:
            if state != self.state:
                self.state = state
                if state == "listening":  # внимательный взгляд прямо на собеседника
                    self._gaze_target = [0.0, 0.0]

    def set_speech_level(self, level: float):
        self._speech_target = max(0.0, min(1.0, level))

    def set_mic_level(self, level: float):
        self._mic_target = max(0.0, min(1.0, level))

    def look_at(self, x: float, y: float, hold: float = 2.5):
        with self._lock:
            self.gaze_override = (max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)), time.time() + hold)

    def set_subtitle(self, text: str, seconds: float = 4.0):
        if not self.cfg.get("display.subtitles", True):
            return
        text = (text or "").strip()
        if len(text) > 70:
            text = text[:67] + "…"
        self.anim.subtitle = text
        self._subtitle_until = time.time() + seconds

    def set_info(self, text: str):
        self.anim.info = text or ""

    def current_emotion(self) -> str:
        with self._lock:
            if self.transient and self.transient[2] > time.time():
                return self.transient[0]
            return self.mood[0]

    # -------------------------------------------------------------- логика --
    def _target(self) -> FaceParams:
        now = time.time()
        with self._lock:
            if self.transient and self.transient[2] <= now:
                self.transient = None
            emo, inten = (self.transient[0], self.transient[1]) if self.transient else self.mood
            state = self.state
            extra = dict(self.extra)
        if state == "sleep":
            return preset("sleep")
        p = preset(emo, inten)
        if state == "listening":
            listen = preset("listening")
            p = p.lerp(listen, 0.55 if emo != "neutral" else 1.0)
            p.ring = 1.0
        elif state == "thinking":
            p = p.lerp(preset("thinking"), 0.65)
            p.dots = 1.0
        for k, v in extra.items():
            if hasattr(p, k):
                setattr(p, k, v)
        return p

    def update(self, dt: float):
        now = time.time()
        a = self.anim
        a.t += dt
        target = self._target()
        p = self.params
        p.approach(target, 1 - math.exp(-dt * 7.0))
        # моргание
        if self._blink_start is None and now >= self._next_blink and p.closed < 0.5:
            self._blink_start = now
            self._blink_len = max(0.08, p.blink_time)
            self._double_blink = random.random() < 0.12
        if self._blink_start is not None:
            u = (now - self._blink_start) / self._blink_len
            if u >= 1.0:
                a.blink = 0.0
                self._blink_start = None
                if self._double_blink:
                    self._double_blink = False
                    self._next_blink = now + 0.12
                else:
                    rate = max(0.5, p.blink_rate) / 60.0
                    self._next_blink = now + min(14.0, max(0.6, random.expovariate(rate)))
            else:
                a.blink = (u / 0.42) if u < 0.42 else 1.0 - (u - 0.42) / 0.58
                a.blink = a.blink * a.blink * (3 - 2 * a.blink)  # сглаживание
        # взгляд: внешняя цель (касание/камера) или «бегающий» взгляд
        with self._lock:
            go = self.gaze_override
            if go and go[2] < now:
                self.gaze_override = go = None
        if go:
            self._gaze_target = [go[0], go[1]]
        elif now >= self._next_saccade:
            w = p.wander
            if p.saccade_rate > 0.01:
                self._gaze_target = [p.gaze_x + random.uniform(-1, 1) * w * 0.75,
                                     p.gaze_y + random.uniform(-1, 1) * w * 0.45]
                self._next_saccade = now + min(6.0, random.expovariate(max(0.05, p.saccade_rate)))
            else:
                self._gaze_target = [p.gaze_x, p.gaze_y]
                self._next_saccade = now + 0.3
        if go is None and p.saccade_rate <= 0.01:
            self._gaze_target = [p.gaze_x, p.gaze_y]
        k = 1 - math.exp(-dt * (22.0 if p.saccade_rate > 1.0 else 14.0))
        self._gaze[0] += (self._gaze_target[0] - self._gaze[0]) * k
        self._gaze[1] += (self._gaze_target[1] - self._gaze[1]) * k
        a.gaze = (self._gaze[0], self._gaze[1])
        # дрожь
        tr = p.tremble * 2.6 * self.renderer.s if self.renderer else 0
        a.jitter = (random.uniform(-tr, tr), random.uniform(-tr, tr)) if tr > 0.05 else (0.0, 0.0)
        # зевок от скуки
        if self.current_emotion() == "boredom" and self.state == "idle":
            if self._yawn_start is None and now >= self._next_yawn:
                self._yawn_start = now
            if self._yawn_start is not None:
                u = (now - self._yawn_start) / 2.6
                if u >= 1:
                    a.yawn = 0.0
                    self._yawn_start = None
                    self._next_yawn = now + random.uniform(15, 35)
                else:
                    a.yawn = math.sin(math.pi * u) ** 1.5
        else:
            a.yawn = max(0.0, a.yawn - dt * 2)
            self._next_yawn = max(self._next_yawn, now + 8)
        # речь и микрофон — сглаживание
        a.speech += (self._speech_target - a.speech) * (1 - math.exp(-dt * 25))
        a.mic += (self._mic_target - a.mic) * (1 - math.exp(-dt * 12))
        if a.subtitle and now > self._subtitle_until:
            a.subtitle = ""

    def demo_tick(self, now: float):
        """Режим --demo: перебор эмоций по кругу."""
        names = ["neutral", "joy", "sadness", "anger", "fear", "surprise", "love", "interest",
                 "contempt", "confidence", "boredom", "thinking", "listening", "sleep"]
        idx = int(now / 4.0) % len(names)
        name = names[idx]
        if name in ("thinking", "listening", "sleep"):
            self.set_mood("neutral")
            self.set_state(name)
            self.transient = None
        else:
            self.set_state("idle")
            self.set_mood(name, 1.0, {"anger_mark": 1.0} if name == "anger" else None)
        self.set_info(f"{name}")

    # ---------------------------------------------------------- окно / цикл --
    def _init_display(self):
        import pygame
        if self.headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        pygame.display.init()
        pygame.font.init()
        if self.headless or self.backend == "luma":
            self.screen = pygame.Surface(self.size)
        else:
            flags = pygame.SCALED
            if self.fullscreen:
                flags |= pygame.FULLSCREEN
            try:
                self.screen = pygame.display.set_mode(self.size, flags, vsync=1)
            except Exception:
                self.screen = pygame.display.set_mode(self.size, flags)
            pygame.display.set_caption(self.cfg.get("assistant.name", "Стелла"))
            if self.hide_cursor and self.fullscreen:
                pygame.mouse.set_visible(False)
        d = self.cfg["display"]
        self.renderer = FaceRenderer(self.size, tuple(d.get("eye_color", (70, 190, 255))),
                                     tuple(d.get("background", (0, 0, 0))), int(d.get("supersample", 1)),
                                     bool(d.get("show_mouth", True)), bool(d.get("show_brows", True)))
        if self.backend == "luma":
            self._luma = _open_luma(d.get("luma", {}))

    def request_frames(self, seconds: float = 5.0):
        """Веб-панель просит кадры лица (MJPEG) — рендерим JPEG только пока кто-то смотрит."""
        self._jpeg_wanted_until = time.time() + seconds

    def latest_jpeg(self):
        return self._jpeg

    def run(self, stop: threading.Event):
        import pygame
        self._init_display()
        clock = pygame.time.Clock()
        log.info("Лицо запущено: %sx%s, %s FPS", *self.size, self.fps)
        while not stop.is_set():
            dt = min(0.1, clock.tick(self.fps) / 1000.0)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    stop.set()
                elif ev.type == pygame.KEYDOWN:
                    if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                        stop.set()
                    elif ev.key == pygame.K_f:
                        pygame.display.toggle_fullscreen()
                    elif ev.key == pygame.K_d:
                        self.demo = not self.demo
                    elif ev.key == pygame.K_SPACE:
                        bus.emit("wake", source="key")
                elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                    if ev.type == pygame.MOUSEBUTTONDOWN and getattr(ev, "touch", False):
                        continue  # SDL дублирует касание «мышиным» событием — считаем один раз
                    if ev.type == pygame.FINGERDOWN:
                        x, y = ev.x * self.size[0], ev.y * self.size[1]
                    else:
                        x, y = ev.pos
                    bus.emit("touch", x=x, y=y, w=self.size[0], h=self.size[1])
                    self.look_at((x / self.size[0]) * 2 - 1, (y / self.size[1]) * 2 - 1, 2.0)
                elif ev.type == pygame.MOUSEMOTION and ev.buttons[0]:
                    self.look_at((ev.pos[0] / self.size[0]) * 2 - 1, (ev.pos[1] / self.size[1]) * 2 - 1, 1.5)
            if self.demo:
                self.demo_tick(time.time())
            self.update(dt)
            eyes = self.renderer.eye_positions(self.params, self.anim)
            self.renderer.update(dt, self.params, eyes)
            self.renderer.render(self.screen, self.params, self.anim)
            if self._luma is not None:
                _show_luma(self._luma, self.screen)
            elif not self.headless:
                pygame.display.flip()
            now = time.time()
            if now < self._jpeg_wanted_until and now - self._jpeg_last > 0.1:
                self._jpeg_last = now
                buf = io.BytesIO()
                try:
                    pygame.image.save(self.screen, buf, "face.jpg")
                    self._jpeg = buf.getvalue()
                except Exception:
                    log.debug("Не удалось сохранить JPEG кадра", exc_info=True)
        pygame.quit()


def _open_luma(opts: dict):
    """Маленький SPI-дисплей (ST7789/ILI9341…) через luma.lcd — для «глаз» в корпусе."""
    try:
        from luma.core.interface.serial import spi
        from luma.lcd import device as lcd
        serial = spi(port=opts.get("spi_port", 0), device=opts.get("spi_device", 0),
                     gpio_DC=opts.get("gpio_DC", 24), gpio_RST=opts.get("gpio_RST", 25),
                     bus_speed_hz=opts.get("bus_speed_hz", 52_000_000))
        cls = getattr(lcd, opts.get("driver", "st7789"))
        dev = cls(serial, width=opts.get("width", 320), height=opts.get("height", 240),
                  rotate=opts.get("rotate", 0), gpio_LIGHT=opts.get("gpio_LIGHT", 18))
        log.info("SPI-дисплей %s подключён", opts.get("driver"))
        return dev
    except Exception as e:  # pragma: no cover - железо
        log.error("SPI-дисплей недоступен (%s) — продолжаю без него", e)
        return None


def _show_luma(dev, surface):  # pragma: no cover - железо
    import pygame
    from PIL import Image
    img = Image.frombytes("RGB", surface.get_size(), pygame.image.tobytes(surface, "RGB"))
    dev.display(img.resize(dev.size))


__all__ = ["Face", "PRESETS"]
