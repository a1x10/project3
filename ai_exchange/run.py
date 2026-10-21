"""Запуск всего: биржа + боты + ИИ + сайт. Открывает http://localhost:8000"""
from __future__ import annotations

import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
import os
import subprocess
import sys
import threading
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    args = ap.parse_args()

    from exchange.config import load_env
    load_env()

    if not os.path.exists(os.path.join(ROOT, "models", "model.txt")):
        print("Модель ИИ ещё не обучена — делаю быстрое обучение (1–2 минуты). "
              "Для полноценной модели потом запустите: python train.py")
        subprocess.run([sys.executable, os.path.join(ROOT, "train.py"), "--quick"], check=True, cwd=ROOT)

    import uvicorn
    from exchange.server import create_app

    app = create_app()
    ctx = app.state.ctx
    print(f"ИИ-трейдер: {'LightGBM-модель загружена' if ctx.sim.ai.model else 'работает БЕЗ ML-модели (запустите train.py)'}")
    print(f"ИИ-аналитик (Claude): {'включён' if ctx.analyst.enabled else 'выключен (нет ANTHROPIC_API_KEY в .env)'}")
    url = f"http://localhost:{args.port}"
    print(f"Открываю {url}  (остановить: Ctrl+C)")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
