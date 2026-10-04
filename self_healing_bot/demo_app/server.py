"""Маленький веб-сервер, на котором удобно проверить бота (только стандартная библиотека Python).

Запуск: PORT=3000 python3 server.py
Проверка: curl http://127.0.0.1:3000/health

Чтобы устроить «аварию», сделай опечатку, например замени load_config() на load_confg(),
и перезапусти приложение (/restart в боте) — оно упадёт при старте, а бот позовёт ИИ.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.getenv("PORT", "3000"))


def load_config():
    return {"greeting": "Привет от demo-приложения!"}


config = load_config()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
        else:
            self.send_json(200, {"message": config["greeting"]})

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"{self.address_string()} {format % args}", flush=True)


if __name__ == "__main__":
    print(f"Demo app listening on http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
