#!/usr/bin/env python3
"""Стелла — мини ИИ-ассистент с живыми глазами для Raspberry Pi 4.

Запуск:
    python3 main.py                 # обычный режим: лицо на экране + голос
    python3 main.py --text          # чат в консоли (удобно на ПК без микрофона)
    python3 main.py --demo          # показать все эмоции по кругу
    python3 main.py --windowed      # в окне, а не на весь экран
    python3 main.py --no-face       # без экрана (только голос, веб и Telegram)
    python3 main.py --emotion-sheet eyes.png   # нарисовать все эмоции в одну картинку
"""
from __future__ import annotations

import argparse
import importlib
import logging
import os
import signal
import sys
import threading

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stella.config import Config  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="Стелла — голосовой ассистент с эмоциями")
    p.add_argument("-c", "--config", help="путь к config.yaml")
    p.add_argument("--text", action="store_true", help="консольный чат вместо голоса")
    p.add_argument("--demo", action="store_true", help="демонстрация всех эмоций")
    p.add_argument("--windowed", action="store_true", help="лицо в окне")
    p.add_argument("--no-face", action="store_true", help="без экрана")
    p.add_argument("--no-voice", action="store_true", help="без микрофона")
    p.add_argument("--emotion-sheet", metavar="PNG", help="сохранить картинку со всеми эмоциями и выйти")
    p.add_argument("-v", "--verbose", action="store_true", help="подробный журнал")
    return p.parse_args()


def emotion_sheet(cfg, path: str):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    from stella.face.emotions import EMOTION_NAMES_RU, preset
    from stella.face.renderer import AnimState, FaceRenderer
    pygame.display.init()
    pygame.font.init()
    names = ["neutral", "joy", "sadness", "anger", "fear", "surprise", "love", "interest", "contempt",
             "confidence", "boredom", "listening", "thinking", "sleep"]
    d = cfg["display"]
    r = FaceRenderer((800, 480), tuple(d["eye_color"]), tuple(d["background"]), 2, d["show_mouth"], d["show_brows"])
    cols, tw, th = 4, 400, 240
    rows = (len(names) + cols - 1) // cols
    sheet = pygame.Surface((cols * tw, rows * (th + 30)))
    sheet.fill((24, 26, 34))
    font = pygame.font.Font(None, 30)
    for i, n in enumerate(names):
        p = preset(n)
        if n == "anger":
            p.anger_mark = 1.0
        st = AnimState(t=1.3, gaze=(p.gaze_x, p.gaze_y), mic=0.5)
        surf = pygame.Surface((800, 480))
        eyes = r.eye_positions(p, st)
        r.particles = []
        for _ in range(50):
            r.update(0.05, p, eyes)
        r.render(surf, p, st)
        x, y = (i % cols) * tw, (i // cols) * (th + 30)
        sheet.blit(pygame.transform.smoothscale(surf, (tw, th)), (x, y + 30))
        sheet.blit(font.render(f"{n} / {EMOTION_NAMES_RU.get(n, '')}", True, (230, 230, 230)), (x + 8, y + 6))
    pygame.image.save(sheet, path)
    print("Сохранено:", path)


def main():
    args = parse_args()
    cfg = Config.load(args.config)
    logging.basicConfig(level=logging.DEBUG if args.verbose else getattr(logging, str(cfg.get("log_level", "INFO"))),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    for noisy in ("urllib3", "asyncio", "primp", "httpx", "yandex_music", "aiohttp.access", "trafilatura"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if args.emotion_sheet:
        emotion_sheet(cfg, args.emotion_sheet)
        return
    if args.windowed:
        cfg.set("display.fullscreen", False)

    from stella.core.assistant import Assistant
    from stella.face.face import Face

    face = None
    if not args.no_face and cfg.get("display.enabled", True):
        face = Face(cfg)
        face.demo = args.demo
    assistant = Assistant(cfg, face=face, voice=not (args.no_voice or args.text))
    stop = assistant.stop_event

    def on_signal(*_):
        stop.set()
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    try:
        assistant.start()
        start_integrations(cfg, assistant)
        if args.text:
            threading.Thread(target=console, args=(assistant,), daemon=True, name="console").start()
        if face is not None:
            face.run(stop)  # SDL требует главный поток
        else:
            while not stop.wait(0.5):
                pass
    finally:
        stop.set()
        assistant.shutdown()
        logging.getLogger("stella").info("Пока!")


def start_integrations(cfg, assistant):
    """Веб-панель, Telegram, камера. Сбой одной из них не должен останавливать остальное."""
    log = logging.getLogger("stella")
    parts = []
    if cfg.get("web.enabled", True):
        parts.append(("веб-панель", "stella.web.server", "WebServer"))
    if cfg.get("telegram.token"):
        parts.append(("Telegram", "stella.integrations.telegram_bot", "TelegramBot"))
    if cfg.get("vision.enabled"):
        parts.append(("камера", "stella.integrations.vision", "Vision"))
    for title, module, cls in parts:
        try:
            getattr(importlib.import_module(module), cls)(assistant).start()
        except Exception:
            log.exception("Не запустилась %s — работаю без неё", title)


def console(assistant):
    print("\n💬 Пишите команды так же, как сказали бы голосом (Ctrl+C — выход)\n")
    while not assistant.stop_event.is_set():
        try:
            text = input("вы> ").strip()
        except (EOFError, KeyboardInterrupt):
            assistant.stop_event.set()
            break
        if not text:
            continue
        reply = assistant.ask(text, source="console", speak=True)
        emo = f" [{reply.emotion}]" if reply.emotion else ""
        print(f"{assistant.name}{emo}> {reply.text}")
        if reply.card and reply.card not in reply.text and "\n" in reply.card:
            print(reply.card)


if __name__ == "__main__":
    main()
