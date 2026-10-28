"""Имитация Telegram Bot API для демо и ручной проверки входа.

python tests/fake_telegram.py  → http://127.0.0.1:18081, токен любой.
POST /inject {"from_id": 1, "text": "/start <nonce>"} — «написать» боту.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

updates, sent = [], []
lock = threading.Condition()
uid = [0]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/inject":
            with lock:
                uid[0] += 1
                fid = body.get("from_id", 1)
                updates.append({"update_id": uid[0], "message": {
                    "text": body["text"], "chat": {"id": fid, "type": "private"},
                    "from": {"id": fid, "first_name": body.get("name", "Алекс"), "username": body.get("username", "alex")}}})
                lock.notify_all()
            return self._send({"ok": True})
        if self.path == "/sent":
            return self._send(sent)
        method = self.path.rsplit("/", 1)[-1]
        if method == "getMe":
            return self._send({"ok": True, "result": {"id": 1, "is_bot": True, "username": "homeguard_home_bot"}})
        if method == "getUpdates":
            off = body.get("offset", 0)
            end = time.time() + min(body.get("timeout", 0), 2)
            with lock:
                while time.time() < end and not [u for u in updates if u["update_id"] >= off]:
                    lock.wait(0.2)
                res = [u for u in updates if u["update_id"] >= off]
            return self._send({"ok": True, "result": res})
        sent.append({"method": method, **body})
        return self._send({"ok": True, "result": True})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 18081), H).serve_forever()
