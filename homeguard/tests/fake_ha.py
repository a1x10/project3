"""Имитация REST API Home Assistant с Яндекс Станцией для тестов и демо."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = "t" * 40


def serve(port: int = 0):
    calls: list[tuple[str, dict]] = []
    states = [
        {"entity_id": "media_player.yandex_station_mini", "state": "playing", "attributes": {
            "friendly_name": "Яндекс Станция Мини", "volume_level": 0.3, "is_volume_muted": False,
            "media_title": "Звуки дождя", "media_artist": "Алиса", "source": "Алиса"}},
        {"entity_id": "media_player.living_room_tv", "state": "off", "attributes": {"friendly_name": "Телевизор"}},
        {"entity_id": "light.kitchen", "state": "on", "attributes": {"friendly_name": "Кухня"}},
    ]

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, code=200):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _auth(self):
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                self._send({"message": "401: Unauthorized"}, 401)
                return False
            return True

        def do_GET(self):
            if not self._auth():
                return
            if self.path == "/api/":
                return self._send({"message": "API running."})
            if self.path == "/api/states":
                return self._send(states)
            self._send({}, 404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if not self._auth():
                return
            calls.append((self.path, body))
            if self.path.endswith("volume_set"):
                states[0]["attributes"]["volume_level"] = body["volume_level"]
            self._send([])

    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


if __name__ == "__main__":
    srv, _ = serve(18123)
    print("fake HA on 18123, token", TOKEN)
    threading.Event().wait()
