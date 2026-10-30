"""Лайк текущего трека в Spotify через официальный Web API (вход по PKCE: секрет не нужен).

Один раз: создайте приложение на developer.spotify.com, добавьте Redirect URI
http://127.0.0.1:8888/callback, впишите Client ID в .env (SPOTIFY_CLIENT_ID=...) и запустите spotify_login.py
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, "spotify_token.json")
REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "user-read-currently-playing user-read-playback-state user-library-modify"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"


def _client_id():
    cid = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    if not cid:
        raise RuntimeError("Не задан SPOTIFY_CLIENT_ID в .env (см. инструкцию по Spotify)")
    return cid


def pkce_pair():
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _post_token(data: dict) -> dict:
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _save(tok: dict, old=None):
    tok = dict(tok)
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 30
    if "refresh_token" not in tok and old:
        tok["refresh_token"] = old.get("refresh_token")
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(tok, f)
    return tok


def login():
    """Открывает браузер, ждёт подтверждения и сохраняет токены в spotify_token.json."""
    cid = _client_id()
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(8)
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Готово! Можно закрыть вкладку и вернуться к колонке.</h2>".encode("utf-8"))

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 8888), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cid, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES,
        "state": state, "code_challenge_method": "S256", "code_challenge": challenge})
    print("Открываю браузер для входа в Spotify…\nЕсли не открылся, перейдите по ссылке:\n" + url)
    webbrowser.open(url)
    for _ in range(300):
        if got:
            break
        time.sleep(1)
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        raise RuntimeError("Вход не подтверждён: " + str(got.get("error", "нет ответа")))
    tok = _post_token({"grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT,
                       "client_id": cid, "code_verifier": verifier})
    _save(tok)
    print("Spotify подключён.")


def _token() -> str:
    if not os.path.exists(TOKEN_FILE):
        raise RuntimeError("Spotify не подключён: запустите spotify_login.py")
    with open(TOKEN_FILE, encoding="utf-8") as f:
        tok = json.load(f)
    if time.time() >= tok.get("expires_at", 0):
        tok = _save(_post_token({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                 "client_id": _client_id()}), tok)
    return tok["access_token"]


def _call(method, path, query=None):
    url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
    req = urllib.request.Request(url, method=method, headers={"Authorization": "Bearer " + _token()})
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read()
        return r.status, (json.loads(body) if body else None)


def current_track():
    status, data = _call("GET", "/me/player/currently-playing")
    if status == 204 or not data or not data.get("item"):
        return None
    it = data["item"]
    return it["id"], it["name"], ", ".join(a["name"] for a in it.get("artists", []))


def like_current() -> str:
    cur = current_track()
    if not cur:
        return "Сейчас ничего не играет в Spotify, лайкать нечего."
    tid, name, artist = cur
    try:  # новый эндпоинт библиотеки, при отказе — классический
        _call("PUT", "/me/library", {"uris": f"spotify:track:{tid}"})
    except urllib.error.HTTPError as e:
        if e.code not in (400, 404, 405):
            raise
        _call("PUT", "/me/tracks", {"ids": tid})
    return f"Лайк: «{name}» — {artist}"
