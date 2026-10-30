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
SCOPES = "user-read-currently-playing user-read-playback-state user-library-modify user-modify-playback-state"
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


def _call(method, path, query=None, body=None):
    url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
    headers = {"Authorization": "Bearer " + _token()}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
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


class PremiumRequired(RuntimeError):
    pass


STOP_WORDS = {"песню", "песни", "трек", "композицию", "группу", "исполнителя", "артиста", "альбом", "плейлист",
              "музыку", "пожалуйста", "мне", "от", "группы"}


def _kind(query: str):
    low = query.lower()
    if "плейлист" in low:
        return "playlist"
    if any(w in low for w in ("группу", "группы", "исполнителя", "артиста")):
        return "artist"
    return "track"


def _clean(query: str) -> str:
    return " ".join(w for w in query.split() if w.lower() not in STOP_WORDS) or query


def _error_reason(e: urllib.error.HTTPError) -> str:
    try:
        return json.loads(e.read().decode("utf-8")).get("error", {}).get("reason", "")
    except Exception:
        return ""


def _device_id():
    _, data = _call("GET", "/me/player/devices")
    devices = (data or {}).get("devices", [])
    for pref in (lambda d: d.get("is_active"), lambda d: d.get("type") == "Computer", lambda d: True):
        for d in devices:
            if pref(d):
                return d["id"]
    return None


def search_and_play(query: str) -> str:
    """Ищет трек/исполнителя/плейлист и запускает на активном устройстве Spotify (нужен Premium)."""
    kind = _kind(query)
    _, res = _call("GET", "/search", {"q": _clean(query), "type": kind, "limit": 1})
    items = (res or {}).get(kind + "s", {}).get("items", [])
    items = [i for i in items if i]
    if not items:
        raise LookupError(f"ничего не нашла по запросу «{query}»")
    item = items[0]
    body = {"uris": [item["uri"]]} if kind == "track" else {"context_uri": item["uri"]}
    label = item["name"] + (" - " + ", ".join(a["name"] for a in item["artists"]) if kind == "track" else "")
    try:
        _call("PUT", "/me/player/play", None, body)
    except urllib.error.HTTPError as e:
        reason = _error_reason(e)
        if e.code == 403:
            raise PremiumRequired("нужен Spotify Premium для запуска трека по названию") from e
        if e.code != 404:
            raise
        # нет активного устройства: открываем приложение и пробуем на его устройстве
        try:
            import os as _os
            if hasattr(_os, "startfile"):
                _os.startfile("spotify:")
        except Exception:
            pass
        dev = None
        for _ in range(10):
            time.sleep(1)
            dev = _device_id()
            if dev:
                break
        if not dev:
            raise RuntimeError("не нашла устройство Spotify: откройте приложение Spotify") from e
        _call("PUT", "/me/player/play", {"device_id": dev}, body)
    return f"Включаю: {label}"
