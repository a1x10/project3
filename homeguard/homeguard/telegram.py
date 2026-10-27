"""Telegram-бот HomeGuard: вход в панель, подтверждение новых людей, тревоги и быстрые команды.

Работает через long polling (getUpdates) — белый IP и домен не нужны.
"""
import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request

from . import auth, blocklists, config, db

log = logging.getLogger("homeguard.tg")


class TgError(Exception):
    pass


def token() -> str:
    return config.TG_TOKEN or db.get_setting("tg_token")


def api(method: str, payload: dict | None = None, tok: str | None = None, timeout: float = 35.0):
    tok = tok or token()
    if not tok:
        raise TgError("Бот не настроен")
    req = urllib.request.Request(f"{config.TG_API}/bot{tok}/{method}",
                                 data=json.dumps(payload or {}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            raise TgError("Telegram не принял токен бота")
        raise TgError(f"Telegram: HTTP {e.code}")
    except (OSError, ValueError) as e:
        raise TgError("Нет связи с Telegram") from e
    if not out.get("ok"):
        raise TgError(out.get("description", "Ошибка Telegram"))
    return out["result"]


def configure(tok: str) -> str:
    """Проверяет токен и сохраняет. Возвращает @username бота."""
    tok = tok.strip()
    me = api("getMe", tok=tok, timeout=10)
    db.set_setting("tg_token", tok)
    db.set_setting("tg_username", me["username"])
    bot.ensure_running()
    return me["username"]


def username() -> str:
    u = db.get_setting("tg_username")
    if not u and token():
        try:
            u = api("getMe", timeout=10)["username"]
            db.set_setting("tg_username", u)
        except TgError:
            return ""
    return u


def deep_link(nonce: str) -> str:
    return f"https://t.me/{username()}?start={nonce}"


LEVEL_NAMES = {k: v["title"] for k, v in blocklists.LEVELS.items()}
HELP = ("🛡 <b>HomeGuard</b>\n\n"
        "/status — что происходит в сети\n"
        "/level — уровень защиты (off / basic / medium / strict)\n"
        "/vpn — состояние VPN\n"
        "/check <ссылка> — проверить ссылку антивирусом")


class Bot:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._out: "queue.Queue[tuple[int, str, dict | None]]" = queue.Queue()
        self._alerted: dict[str, float] = {}
        self.offset = 0

    # ---- жизненный цикл ----
    def ensure_running(self) -> None:
        if not token() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="tg-bot", daemon=True)
        self._thread.start()
        threading.Thread(target=self._sender, name="tg-send", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        log.info("Telegram-бот запущен")
        while not self._stop.is_set():
            try:
                updates = api("getUpdates", {"offset": self.offset, "timeout": 25,
                                             "allowed_updates": ["message", "callback_query"]})
            except TgError as e:
                log.warning("getUpdates: %s", e)
                self._stop.wait(5)
                continue
            for u in updates:
                self.offset = u["update_id"] + 1
                try:
                    self.handle(u)
                except Exception:
                    log.exception("Ошибка обработки апдейта")

    def _sender(self) -> None:
        while not self._stop.is_set():
            try:
                chat, text, markup = self._out.get(timeout=1)
            except queue.Empty:
                continue
            payload = {"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
            if markup:
                payload["reply_markup"] = markup
            try:
                api("sendMessage", payload, timeout=15)
            except TgError as e:
                log.warning("sendMessage: %s", e)

    def send(self, chat: int, text: str, markup: dict | None = None) -> None:
        self._out.put((chat, text, markup))

    # ---- тревоги ----
    def alert(self, text: str, key: str, cooldown: float = 600) -> None:
        """Сообщение владельцу, не чаще раза в cooldown секунд на один key."""
        o = auth.owner()
        if not o or not token():
            return
        now = time.time()
        if now - self._alerted.get(key, 0) < cooldown:
            return
        self._alerted[key] = now
        self.send(o["tg_id"], text)

    # ---- обработка ----
    def handle(self, u: dict) -> None:
        if "callback_query" in u:
            return self._callback(u["callback_query"])
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        frm = msg.get("from") or {}
        chat = (msg.get("chat") or {}).get("id")
        if not chat or not frm or msg.get("chat", {}).get("type") != "private":
            return
        name = " ".join(filter(None, [frm.get("first_name"), frm.get("last_name")])) or "Без имени"
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        arg = arg.strip()

        if cmd == "/start" and arg:
            return self._login(chat, frm["id"], name, frm.get("username"), arg)
        user = auth.get_user(frm["id"])
        if not user or user["role"] == "pending":
            return self.send(chat, "Привет! Чтобы войти, открой панель HomeGuard и нажми «Войти через Telegram».")
        if cmd in ("/start", "/help"):
            return self.send(chat, HELP)
        if cmd == "/status":
            return self.send(chat, self._status_text())
        if cmd == "/level":
            return self._level(chat, user, arg)
        if cmd == "/vpn":
            from . import vpn
            st = vpn.manager.status()
            act = next((p for p in st["profiles"] if p["id"] == st["active"]), None)
            txt = (f"🌍 VPN включён: {act['flag']} {act['name']}" if st["state"] == "connected" and act
                   else "VPN выключен" if st["state"] == "disconnected" else "⚠ Туннель VPN упал")
            return self.send(chat, txt)
        if cmd == "/check" and arg:
            from . import antivirus
            r = antivirus.check_url(arg)
            return self.send(chat, antivirus.verdict_text(r))
        self.send(chat, HELP)

    def _login(self, chat, tg_id, name, uname, nonce) -> None:
        res = auth.bot_start(nonce, tg_id, name, uname)
        if res == "approved":
            role = auth.get_user(tg_id)["role"]
            extra = "\nТы — владелец этой сети 👑" if role == "owner" else ""
            self.send(chat, f"✅ Вход подтверждён. Возвращайся в панель.{extra}\n\n{HELP}")
        elif res == "pending_owner":
            self.send(chat, "⏳ Запрос отправлен владельцу сети. Как только он подтвердит — панель откроется.")
            o = auth.owner()
            who = f"{name}" + (f" (@{uname})" if uname else "")
            self.send(o["tg_id"], f"👤 <b>{_esc(who)}</b> хочет войти в HomeGuard.",
                      {"inline_keyboard": [[{"text": "✅ Пустить", "callback_data": f"ok:{nonce}"},
                                            {"text": "⛔ Отказать", "callback_data": f"no:{nonce}"}]]})
        else:
            self.send(chat, "Ссылка для входа устарела. Обнови страницу панели и попробуй ещё раз.")

    def _callback(self, cq: dict) -> None:
        o = auth.owner()
        data = cq.get("data") or ""
        ans = {"callback_query_id": cq["id"]}
        if not o or cq["from"]["id"] != o["tg_id"]:
            ans["text"] = "Только владелец может это сделать"
        elif data.startswith(("ok:", "no:")):
            nonce = data[3:]
            try:
                if data.startswith("ok:"):
                    auth.approve(nonce)
                    ans["text"] = "Пользователь добавлен"
                else:
                    auth.deny(nonce)
                    ans["text"] = "Отказано"
            except auth.AuthError as e:
                ans["text"] = str(e)
            msg = cq.get("message")
            if msg:
                try:
                    api("editMessageReplyMarkup", {"chat_id": msg["chat"]["id"], "message_id": msg["message_id"],
                                                   "reply_markup": {"inline_keyboard": []}}, timeout=10)
                except TgError:
                    pass
        elif data.startswith("lvl:") and data[4:] in blocklists.LEVELS:
            db.set_setting("level", data[4:])
            ans["text"] = f"Защита: {LEVEL_NAMES[data[4:]]}"
        try:
            api("answerCallbackQuery", ans, timeout=10)
        except TgError:
            pass

    def _level(self, chat, user, arg) -> None:
        if arg:
            if arg not in blocklists.LEVELS:
                return self.send(chat, "Уровни: off, basic, medium, strict")
            db.set_setting("level", arg)
            return self.send(chat, f"🛡 Защита: <b>{LEVEL_NAMES[arg]}</b>")
        cur = db.get_setting("level")
        kb = [[{"text": ("● " if k == cur else "") + v, "callback_data": f"lvl:{k}"}] for k, v in LEVEL_NAMES.items()]
        self.send(chat, f"Сейчас: <b>{LEVEL_NAMES.get(cur, cur)}</b>", {"inline_keyboard": kb})

    @staticmethod
    def _status_text() -> str:
        since = time.time() - 86400
        q = db.query("SELECT COUNT(*) n, SUM(action='blocked') b FROM queries WHERE ts > ?", (since,))[0]
        on = db.query("SELECT COUNT(*) n FROM devices WHERE last_seen > ?", (time.time() - config.ONLINE_WINDOW,))[0]["n"]
        threats = db.query("SELECT COUNT(*) n FROM queries WHERE ts > ? AND reason IN ('malware','phishing')",
                           (since,))[0]["n"]
        return (f"📡 Устройств в сети: <b>{on}</b>\n"
                f"🌐 Запросов за сутки: <b>{q['n']}</b>, заблокировано: <b>{q['b'] or 0}</b>\n"
                f"☣ Угроз остановлено: <b>{threats}</b>\n"
                f"🛡 Защита: <b>{LEVEL_NAMES.get(db.get_setting('level'))}</b>")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


bot = Bot()
