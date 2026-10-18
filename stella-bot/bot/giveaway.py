"""Розыгрыш: страница участника (/giveaway/), админка (/giveaway/admin) и рассылка в личку Telegram.

- Участник: имя, ник в Telegram или телефон, согласие -> вопрос-капча на время -> по желанию почта.
- Админка без пароля: владелец (или админ бота) пишет Стелле в личку «/розыгрыш» — она присылает одноразовую
  ссылку (действует 15 минут). Токен — после «#» в адресе: на сервер он не уходит ни в превью ссылок, ни в логи.
- Рассылка — только тем, кто сам писал Стелле в личку Telegram: каждому — один раз за розыгрыш, с кнопками
  «Участвовать» и «Не присылать такое» (отписка навсегда); заблокировавшие бота пропускаются.
- Кнопка у каждого получателя — своя подписанная ссылка (?t=…): по ней заявка привязывается к его Telegram —
  один человек из рассылки = одна заявка, и победителя можно выбирать только среди пришедших по кнопке
  (капча — лишь «лежачий полицейский», скрипт её решит, а подпись — нет).
- Данные — в отдельной SQLite (DATA_DIR/giveaway.db). «Новый розыгрыш» в админке начинает следующий круг —
  прошлые заявки остаются в базе.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import ipaddress
import logging
import os
import random
import re
import secrets
import smtplib
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any, Callable, Iterator

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from .brain import Brain

log = logging.getLogger("stella.giveaway")

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "giveaway_static")
PREFIX = "/giveaway"
COOKIE = "gw_admin"
SESSION_HOURS = 6
LINK_MINUTES = 15
HITS_MAX = 50000  # адресов в памяти для ограничения частоты (дальше — забываем самые старые)
CAPTCHAS_MAX = 20000
FLOOD_TRIES = 3  # Telegram просит подождать — ждём и шлём этому же человеку ещё раз
SPIKE_PER_MINUTE = 40  # столько заявок за минуту — похоже на накрутку: сообщаем владельцу
CAPTCHA_SECONDS = 25
TIMER_MINUTES = 30
STOP_DATA = "gw:stop"  # кнопка «Не присылать такое»
SEND_PAUSE = 0.07  # Telegram пускает ~30 сообщений в секунду от бота — идём с запасом
MAX_TEXT = 3500
DEFAULT_BUTTON = "Участвовать 🎁"
DEFAULT_TEXT = (
    "Добрый вечер! 👋\n\n"
    "Сегодня у нас небольшой розыгрыш 🎁\n\n"
    "Кто перейдёт по ссылке и оставит заявку, участвует в розыгрыше безлимитного доступа к ИИ на 35 дней.\n\n"
    "⏰ Победителя выберем ровно через 30 минут, среди всех, кто успеет зарегистрироваться. "
    "Безлимит выдадим сразу же.\n\n"
    "Регистрация занимает меньше минуты. Жмите кнопку ниже и успевайте 👇"
)
# Страницы: свои стили и скрипты внутри, шрифты — Google Fonts
CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")

# как у Telegram: 5–32 символа, с буквы, без «_» на конце (обрезанная при вставке ссылка не пройдёт)
USERNAME_RE = re.compile(r"^@?[A-Za-z][A-Za-z0-9_]{3,30}[A-Za-z0-9]$")
INVITE_RE = re.compile(r"(\d{1,15})\.([0-9a-f]{20})", re.ASCII)
SESSION_RE = re.compile(r"(\d{1,12})\.(\d{1,9})\.([0-9a-f]{64})", re.ASCII)
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-zА-Яа-я]{2,24}$")
DAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
ODD_ONE = [
    (["яблоко", "груша", "слива"], "морковь"),
    (["кошка", "собака", "корова"], "тюльпан"),
    (["красный", "синий", "зелёный"], "круглый"),
    (["январь", "март", "май"], "среда"),
    (["Алматы", "Астана", "Шымкент"], "Волга"),
    (["стул", "стол", "шкаф"], "облако"),
    (["футбол", "теннис", "хоккей"], "борщ"),
    (["молоток", "отвёртка", "пила"], "банан"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    round INTEGER NOT NULL DEFAULT 1,
    token TEXT UNIQUE NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT,
    contact TEXT NOT NULL,
    contact_key TEXT NOT NULL,
    contact_type TEXT NOT NULL,
    email TEXT,
    captcha_sec REAL,
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL,
    is_winner INTEGER DEFAULT 0,
    email_sent_at TEXT,
    UNIQUE(round, contact_key)
);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS optout(chat_jid TEXT PRIMARY KEY, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sent(round INTEGER NOT NULL, chat_jid TEXT NOT NULL, at TEXT NOT NULL,
                                PRIMARY KEY(round, chat_jid));
"""
MIGRATIONS = [
    # чем кончилась отправка: pending (идёт) | sent | blocked (заблокировал бота, удалил аккаунт)
    "ALTER TABLE sent ADD COLUMN outcome TEXT NOT NULL DEFAULT 'sent'",
    # заявка по личной кнопке из рассылки: чей это Telegram (одна заявка на человека в розыгрыше)
    "ALTER TABLE entries ADD COLUMN tg_chat_id INTEGER",
    "CREATE UNIQUE INDEX IF NOT EXISTS entries_tg ON entries(round, tg_chat_id)",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean(s: str | None, n: int) -> str:
    return re.sub(r"[\x00-\x1f<>]", "", s or "").strip()[:n]


def normalize_contact(raw: str) -> tuple[str, str, str] | None:
    """Ник Telegram или телефон -> (как показать, ключ для «одна заявка на контакт», тип)."""
    s = re.sub(r"\s", " ", raw or "").strip()  # неразрывные и узкие пробелы (так часто копируется номер) — обычные
    # только обычные цифры: «７７０１…» (широкие, арабские и т.п.) — тот же номер, второй заявки по нему быть не должно
    if re.fullmatch(r"[+0-9 \-()]{10,22}", s):
        digits = re.sub(r"[^0-9]", "", s)
        if digits.startswith("00"):  # 007 701… — то же, что +7 701…
            digits = digits[2:]
        if len(digits) == 11 and digits[0] == "8":
            digits = "7" + digits[1:]
        if 10 <= len(digits) <= 15:
            return "+" + digits, "phone:" + digits, "phone"
        return None
    s2 = re.sub(r"^(https?://)?t\.me/", "", s)
    if USERNAME_RE.fullmatch(s2):
        u = s2.lstrip("@")
        return "@" + u, "tg:" + u.lower(), "telegram"
    return None


def csv_safe(value: Any) -> Any:
    """Excel не должен принять имя «=HYPERLINK(…)» за формулу."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def make_question(rng: random.Random | None = None) -> tuple[str, str, list[str]]:
    """Вопрос на сообразительность (человек отвечает за секунды, простой бот — нет) -> (вопрос, ответ, варианты)."""
    r = rng or random.SystemRandom()
    kind = r.choice(["seq", "story", "day", "odd", "compare"])
    if kind == "seq":
        a, d = r.randint(1, 9), r.randint(2, 6)
        nums = [a + d * i for i in range(4)]
        q = f"Продолжите ряд: {nums[0]}, {nums[1]}, {nums[2]}, ?"
        ans = str(nums[3])
        opts = {ans, str(nums[3] + d), str(nums[3] - 1), str(nums[2] + 1)}
    elif kind == "story":
        x, y, z = r.randint(3, 8), r.randint(1, 2), r.randint(2, 5)
        w = "яблока" if x in (2, 3, 4) else "яблок"
        q = f"У Димы было {x} {w}. Он отдал {y} другу и купил ещё {z}. Сколько яблок у Димы?"
        res = x - y + z
        ans = str(res)
        opts = {ans, str(res + 1), str(res - 1), str(x + y + z)}
    elif kind == "day":
        i, shift = r.randint(0, 6), r.choice([1, 2])
        word = "завтра" if shift == 1 else "послезавтра"
        q = f"Если сегодня {DAYS[i]}, какой день недели будет {word}?"
        ans = DAYS[(i + shift) % 7]
        opts = {ans, DAYS[(i + shift + 1) % 7], DAYS[(i - 1) % 7], DAYS[(i + shift + 3) % 7]}
    elif kind == "odd":
        group, odd = r.choice(ODD_ONE)
        q = "Какое слово здесь лишнее?"
        ans = odd
        opts = set(group) | {odd}
    else:
        a, b = r.sample(range(10, 99), 2)
        q = f"Какое число больше: {a} или {b}?"
        ans = str(max(a, b))
        opts = {str(a), str(b)}
    options = sorted(opts)
    r.shuffle(options)
    return q, ans, options


class Giveaway:
    """Всё состояние розыгрыша: база, капчи, входы в админку, рассылка."""

    def __init__(self, settings: Any, brain: "Brain | None" = None, path: str | None = None,
                 clock: Callable[[], float] = time.time):
        self.s = settings
        self.brain = brain
        self.path = path or os.path.join(settings.data_dir, "giveaway.db")
        self.clock = clock
        self._lock = threading.Lock()  # записи — по одной
        self._init_lock = threading.Lock()
        self._ready = False
        # по времени создания / последнего запроса: самые старые — в начале (выбрасываем оттуда, без перебора всего)
        self.captchas: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self.hits: OrderedDict[str, deque[float]] = OrderedDict()
        self.links: dict[str, float] = {}  # sha256(одноразовый токен входа) -> до какого времени действует
        self.progress: dict[str, Any] = {"state": "idle"}  # ход рассылки — видно в админке
        self._broadcast: asyncio.Task | None = None
        self._start_lock = asyncio.Lock()  # две вкладки нажали «Разослать» разом — уйдёт одна рассылка
        self._url_checked = 0.0
        self.recent: deque[float] = deque()  # время последних заявок — заметить накрутку
        self._spike_told = 0.0

    # ---------- база ----------
    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        if not self._ready:
            with self._init_lock:
                if not self._ready:
                    os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
                    con = sqlite3.connect(self.path)
                    try:
                        con.execute("PRAGMA journal_mode=WAL")
                        con.executescript(SCHEMA)
                        for ddl in MIGRATIONS:  # база от прошлой версии — добавить новое (уже есть — пропустить)
                            try:
                                con.execute(ddl)
                            except sqlite3.OperationalError:
                                pass
                        con.commit()
                    finally:
                        con.close()
                    self._ready = True
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            with con:  # транзакция: commit или rollback
                yield con
        finally:
            con.close()

    def setting(self, k: str, default: str | None = None) -> str | None:
        with self.db() as con:
            r = con.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    def set_setting(self, k: str, v: str | None) -> None:
        with self._lock, self.db() as con:
            if v is None:
                con.execute("DELETE FROM settings WHERE k=?", (k,))
            else:
                con.execute("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))

    def round(self) -> int:
        return int(self.setting("round", "1") or 1)

    def prize(self) -> str:
        return self.setting("prize") or getattr(self.s, "giveaway_prize", "") or "Безлимитный ИИ на 35 дней"

    def secret(self) -> bytes:
        """Ключ подписи сессий админки: создаётся один раз и живёт в базе (сессии переживают перезапуск)."""
        value = self.setting("secret")
        if not value:
            value = secrets.token_hex(32)
            with self._lock, self.db() as con:
                con.execute("INSERT OR IGNORE INTO settings(k,v) VALUES('secret',?)", (value,))
            value = self.setting("secret") or value
        return value.encode()

    # ---------- адреса ----------
    def base_url(self) -> str | None:
        """Внешний адрес бота: свой домен (GIVEAWAY_PUBLIC_URL) или туннель Cloudflare."""
        own = (getattr(self.s, "giveaway_public_url", "") or "").strip().rstrip("/")
        if own:
            return own[: -len(PREFIX)] if own.endswith(PREFIX) else own
        tunnel = getattr(self.brain, "tunnel_url", None) if self.brain is not None else None
        return tunnel.rstrip("/") if tunnel else None

    def page_url(self) -> str | None:
        base = self.base_url()
        return f"{base}{PREFIX}/" if base else None

    def admin_link(self) -> str:
        """Одноразовая ссылка в админку (15 минут). Без внешнего адреса — локальная (через SSH-туннель)."""
        token = secrets.token_urlsafe(24)
        now = self.clock()
        self.links = {h: t for h, t in self.links.items() if t > now}
        self.links[_hash(token)] = now + LINK_MINUTES * 60
        base = self.base_url() or f"http://localhost:{os.getenv('BOT_HOST_PORT', '18000')}"
        return f"{base}{PREFIX}/admin#t={token}"

    def use_link(self, token: str) -> bool:
        until = self.links.pop(_hash(token or ""), None)
        return until is not None and until > self.clock()

    def invite(self, chat_id: int) -> str:
        """Подпись личной ссылки получателя рассылки: «<id чата>.<hmac>» — подделать или подобрать чужую нельзя."""
        sig = hmac.new(self.secret(), f"invite:{self.round()}:{chat_id}".encode(), hashlib.sha256).hexdigest()[:20]
        return f"{chat_id}.{sig}"

    def invited_chat(self, token: str | None) -> int | None:
        m = INVITE_RE.fullmatch(token or "")
        if not m or not hmac.compare_digest(self.invite(int(m.group(1))), token or ""):
            return None
        return int(m.group(1))

    def note_registration(self) -> str | None:
        """Заявок за минуту подозрительно много — текст для владельца (не чаще раза в 10 минут)."""
        now = self.clock()
        self.recent.append(now)
        while self.recent and now - self.recent[0] > 60:
            self.recent.popleft()
        if len(self.recent) >= SPIKE_PER_MINUTE and now - self._spike_told > 600:
            self._spike_told = now
            return (f"⚠️ Розыгрыш: {len(self.recent)} заявок за минуту — похоже на накрутку. В админке у пришедших "
                    "по кнопке из рассылки метка «TG»; выбирай победителя с галочкой «Только из рассылки»")
        return None

    def owner_text(self) -> list[str]:
        """Ответ владельцу на «/розыгрыш»."""
        page = self.page_url()
        link = self.admin_link()
        lines = [f"🎁 Розыгрыш: {self.prize()}"]
        if page:
            lines.append(f"Страница для участников: {page}")
        else:
            lines.append("Внешней ссылки пока нет: включи туннель (COMPOSE_PROFILES=panel в .env и "
                         "docker compose up -d) или задай GIVEAWAY_PUBLIC_URL — без неё рассылка не уйдёт")
        lines.append(f"Админка (ссылка одноразовая, {LINK_MINUTES} минут — никому не пересылай): {link}")
        return lines

    # ---------- сессия админки ----------
    def make_session(self) -> str:
        value = f"{int(self.clock()) + SESSION_HOURS * 3600}.{self.setting('session_gen', '1')}"
        return f"{value}.{self._sign(value)}"

    def _sign(self, value: str) -> str:
        return hmac.new(self.secret(), value.encode(), hashlib.sha256).hexdigest()

    def is_admin(self, request: Request) -> bool:
        """Подпись верна, срок не вышел и после выдачи никто не нажимал «Выйти» (это закрывает все входы)."""
        m = SESSION_RE.fullmatch(request.cookies.get(COOKIE, ""))
        if not m:
            return False
        exp, gen, sig = m.groups()
        return (hmac.compare_digest(sig, self._sign(f"{exp}.{gen}")) and int(exp) > self.clock()
                and gen == self.setting("session_gen", "1"))

    def logout_everywhere(self) -> None:
        self.set_setting("session_gen", str(int(self.setting("session_gen", "1") or 1) + 1))

    # ---------- защита от частых запросов ----------
    def rate_limit(self, ip: str, limit: int, window: int, bucket: str) -> None:
        now = self.clock()
        key = f"{bucket}:{ip_key(ip)}"
        q = self.hits.pop(key, None) or deque()
        while q and now - q[0] > window:
            q.popleft()
        blocked = len(q) >= limit
        if not blocked:
            q.append(now)
        self.hits[key] = q  # в конец: недавние — в конце, давние — в начале
        while len(self.hits) > 1:  # не копим память: выбрасываем давно молчащих и лишних — с начала, без перебора
            oldest = next(iter(self.hits.values()))
            if len(self.hits) <= HITS_MAX and now - oldest[-1] < 3600:
                break
            self.hits.popitem(last=False)
        if blocked:
            raise HTTPException(429, "Слишком много попыток, подождите минуту")

    def new_captcha(self) -> dict[str, Any]:
        now = self.clock()
        while self.captchas:
            oldest = next(iter(self.captchas.values()))
            if len(self.captchas) < CAPTCHAS_MAX and now - oldest[1] <= CAPTCHA_SECONDS + 60:
                break
            self.captchas.popitem(last=False)
        q, ans, opts = make_question()
        cid = secrets.token_urlsafe(16)
        self.captchas[cid] = (ans, now)
        return {"id": cid, "question": q, "options": opts, "seconds": CAPTCHA_SECONDS}

    # ---------- заявки ----------
    def state(self) -> dict[str, Any]:
        rnd = self.round()
        with self.db() as con:
            n = con.execute("SELECT COUNT(*) c FROM entries WHERE round=?", (rnd,)).fetchone()["c"]
        return {"prize": self.prize(), "project": getattr(self.s, "giveaway_title", "") or "Розыгрыш",
                "draw_at": self.setting("draw_at"), "closed": self.setting("closed", "0") == "1", "count": n,
                "captcha_seconds": CAPTCHA_SECONDS, "round": rnd}

    def register(self, data: "RegisterIn", ip: str, user_agent: str) -> dict[str, Any]:
        if self.setting("closed", "0") == "1":
            raise HTTPException(400, "Регистрация уже закрыта — итоги подводятся")
        if data.website:
            raise HTTPException(400, "Проверка не пройдена")
        cap = self.captchas.pop(data.captcha_id, None)
        if not cap:
            raise HTTPException(400, "Проверка устарела — ответьте на новый вопрос")
        ans, started = cap
        spent = self.clock() - started
        if spent > CAPTCHA_SECONDS + 3:
            raise HTTPException(400, "Время на ответ вышло — попробуйте ещё раз")
        if spent < 1.2:
            raise HTTPException(400, "Слишком быстро — похоже на робота. Попробуйте ещё раз")
        if data.captcha_answer.strip().lower() != ans.lower():
            raise HTTPException(400, "Неверный ответ — попробуйте ещё раз")
        first, last = clean(data.first_name, 60), clean(data.last_name, 60)
        if len(first) < 2:
            raise HTTPException(400, "Укажите имя")
        if not data.consent:
            raise HTTPException(400, "Нужно согласие на обработку данных")
        norm = normalize_contact(data.contact)
        if not norm:
            raise HTTPException(400, "Укажите ник в Telegram (например, @username) или номер телефона")
        contact, key, ctype = norm
        token = secrets.token_urlsafe(18)
        rnd = self.round()
        tg_chat = self.invited_chat(data.invite)  # пришёл по своей кнопке из рассылки
        try:
            with self._lock, self.db() as con:
                cur = con.execute(
                    "INSERT INTO entries(round,token,first_name,last_name,contact,contact_key,contact_type,"
                    "captcha_sec,ip,user_agent,created_at,tg_chat_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (rnd, token, first, last, contact, key, ctype, round(spent, 1), ip, clean(user_agent, 300),
                     now_iso(), tg_chat))
        except sqlite3.IntegrityError as exc:
            if "tg_chat_id" in str(exc):
                raise HTTPException(409, "Вы уже участвуете в этом розыгрыше 👍") from None
            raise HTTPException(409, "Этот контакт уже участвует в розыгрыше 👍") from None
        return {"ok": True, "token": token, "number": cur.lastrowid, "round": rnd}

    def save_email(self, token: str, email: str) -> None:
        e = (email or "").strip()[:254]
        if not EMAIL_RE.fullmatch(e):
            raise HTTPException(400, "Проверьте адрес почты")
        rnd = self.round()
        with self._lock, self.db() as con:
            cur = con.execute("UPDATE entries SET email=? WHERE token=? AND round=?", (e, token, rnd))
        if cur.rowcount == 0:
            raise HTTPException(404, "Заявка не найдена")

    def entries(self) -> list[dict[str, Any]]:
        with self.db() as con:
            rows = con.execute("SELECT * FROM entries WHERE round=? ORDER BY id DESC", (self.round(),)).fetchall()
        return [_row(r) for r in rows]

    def draw(self, only_with_email: bool, exclude_winners: bool, only_invited: bool = False) -> dict[str, Any]:
        q = "SELECT * FROM entries WHERE round=?"
        if only_with_email:
            q += " AND email IS NOT NULL AND email<>''"
        if exclude_winners:
            q += " AND is_winner=0"
        if only_invited:
            q += " AND tg_chat_id IS NOT NULL"
        with self.db() as con:
            pool = con.execute(q, (self.round(),)).fetchall()
        if not pool:
            raise HTTPException(400, "Нет подходящих участников" + (
                " — пришедших по кнопке из рассылки нет: сними галочку «Только из рассылки»" if only_invited else ""))
        win = secrets.choice(pool)  # криптостойкий случайный выбор
        with self._lock, self.db() as con:
            con.execute("UPDATE entries SET is_winner=1 WHERE id=?", (win["id"],))
            r = con.execute("SELECT * FROM entries WHERE id=?", (win["id"],)).fetchone()
        return {"winner": _row(r), "pool": len(pool), "names": [p["first_name"] for p in pool[:60]]}

    def new_round(self) -> int:
        rnd = self.round() + 1
        self.set_setting("round", str(rnd))
        self.set_setting("draw_at", None)
        self.set_setting("closed", "0")
        return rnd

    def start_timer(self, minutes: float) -> None:
        ts = datetime.fromtimestamp(self.clock() + minutes * 60, timezone.utc)
        self.set_setting("draw_at", ts.isoformat(timespec="seconds"))

    def export_csv(self) -> str:
        with self.db() as con:
            rows = con.execute("SELECT * FROM entries WHERE round=? ORDER BY id", (self.round(),)).fetchall()
        buf = io.StringIO()
        buf.write("﻿")  # Excel откроет кириллицу правильно
        w = csv.writer(buf, delimiter=";")
        w.writerow(["ID", "Имя", "Фамилия", "Контакт", "Тип", "Почта", "Капча, сек", "IP", "Дата (UTC)", "Победитель",
                    "Письмо отправлено", "По кнопке из рассылки"])
        for r in rows:
            # контакт проверен при заявке (+цифры или @ник) — пишем так, чтобы таблица не приняла его за формулу:
            # Telegram — ссылкой, телефон — tel:+…
            contact = (f"https://t.me/{r['contact'].lstrip('@')}" if r["contact_type"] == "telegram"
                       else f"tel:{r['contact']}")
            w.writerow([*(csv_safe(v) for v in (r["id"], r["first_name"], r["last_name"])), contact,
                        *(csv_safe(v) for v in (
                            r["contact_type"], r["email"] or "", r["captcha_sec"], r["ip"], r["created_at"],
                            "да" if r["is_winner"] else "", r["email_sent_at"] or "",
                            "да" if r["tg_chat_id"] else ""))])
        return buf.getvalue()

    def send_mail(self, entry_id: int, to: str | None, subject: str, body: str) -> str:
        host, user = getattr(self.s, "giveaway_smtp_host", ""), getattr(self.s, "giveaway_smtp_user", "")
        if not (host and user):
            raise HTTPException(400, "Почта не настроена (GIVEAWAY_SMTP_HOST / _USER / _PASS)")
        with self.db() as con:
            r = con.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        if not r:
            raise HTTPException(404, "Участник не найден")
        address = (to or r["email"] or "").strip()
        if not EMAIL_RE.fullmatch(address):
            raise HTTPException(400, "У участника нет корректной почты")
        msg = EmailMessage()
        msg["From"] = getattr(self.s, "giveaway_smtp_from", "") or user
        msg["To"] = address
        msg["Subject"] = subject[:200]
        msg.set_content(body[:20000])
        port = int(getattr(self.s, "giveaway_smtp_port", 465) or 465)
        try:
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
                    smtp.login(user, getattr(self.s, "giveaway_smtp_pass", ""))
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=20) as smtp:
                    smtp.starttls()
                    smtp.login(user, getattr(self.s, "giveaway_smtp_pass", ""))
                    smtp.send_message(msg)
        except Exception as exc:
            log.warning("розыгрыш: письмо не ушло: %s", exc)
            raise HTTPException(502, f"Не удалось отправить: {type(exc).__name__}") from None
        with self._lock, self.db() as con:
            con.execute("UPDATE entries SET email_sent_at=? WHERE id=?", (now_iso(), entry_id))
        return address

    # ---------- рассылка в Telegram ----------
    def _tg(self) -> Any:
        return getattr(getattr(self.brain, "evo", None), "tg", None)

    async def recipients(self) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """Кому уйдёт рассылка: личные чаты Telegram, кроме отписавшихся и тех, кому в этом розыгрыше уже слали.
        -> (чаты, счётчики: optout — отписались, sent — получили, blocked — заблокировали бота)."""
        chats = [c for c in await self.brain.db.all_chats(self.s.evolution_instance)
                 if str(c["jid"]).endswith("@tg.chat") and not c["is_group"]]
        with self.db() as con:
            off = {r["chat_jid"] for r in con.execute("SELECT chat_jid FROM optout")}
            done = {r["chat_jid"]: r["outcome"] for r in con.execute(
                "SELECT chat_jid, outcome FROM sent WHERE round=?", (self.round(),))}
        todo = [c for c in chats if c["jid"] not in off and c["jid"] not in done]
        jids = {c["jid"] for c in chats}
        counts = {"optout": len(off & jids),
                  "sent": sum(1 for j, o in done.items() if o == "sent" and j in jids),
                  "blocked": sum(1 for j, o in done.items() if o == "blocked" and j in jids)}
        return todo, counts

    async def fresh_url(self) -> str | None:
        """Адрес страницы, проверенный только что: туннель Cloudflare после перезапуска получает новый адрес, и
        рассылать старый — значит разослать мёртвую кнопку. Свой домен (GIVEAWAY_PUBLIC_URL) не проверяем."""
        refresh = getattr(self.brain, "refresh_tunnel", None)
        own = (getattr(self.s, "giveaway_public_url", "") or "").strip()
        if refresh is not None and not own and self.clock() - self._url_checked > 10:
            self._url_checked = self.clock()
            await refresh()
        return self.page_url()

    async def broadcast_info(self) -> dict[str, Any]:
        tg = self._tg()
        todo, counts = await self.recipients() if self.brain is not None else ([], {})
        return {"telegram": tg is not None, "url": await self.fresh_url(), "recipients": len(todo),
                "optout": counts.get("optout", 0), "already": counts.get("sent", 0),
                "blocked": counts.get("blocked", 0), "progress": dict(self.progress), "default_text": DEFAULT_TEXT,
                "default_button": DEFAULT_BUTTON, "timer_minutes": TIMER_MINUTES,
                "timer_running": bool(self.setting("draw_at"))}

    def _markup(self, button: str, url: str) -> dict[str, Any]:
        return {"inline_keyboard": [[{"text": button, "url": url}],
                                    [{"text": "Не присылать такое", "callback_data": STOP_DATA}]]}

    async def _send(self, tg: Any, chat: dict[str, Any], text: str, button: str, url: str) -> None:
        """Отправить и записать в историю чата. Ушло, а запись не удалась, — всё равно «ушло» (иначе пришлём дважды)."""
        from .telegram import msg_id

        cid = int(str(chat["jid"]).split("@", 1)[0])
        personal = f"{url}?t={self.invite(cid)}"  # своя ссылка: заявка по ней привяжется к этому Telegram
        result = await tg.call("sendMessage", data={"chat_id": cid, "text": text,
                                                     "reply_markup": self._markup(button, personal),
                                                     "link_preview_options": {"is_disabled": True}})
        try:
            wa_id = msg_id(cid, result["message_id"])
            self.brain.outbox.remember_sent(wa_id)
            # в истории чата (со ссылкой): ответят «а что за розыгрыш? дай ссылку» — Стелла поймёт и даст настоящую
            await self.brain.db.add_message(chat["id"], "assistant", f"{text}\n[кнопка «{button}»: {personal}]",
                                            wa_message_id=wa_id, sender_name=self.s.bot_name)
        except Exception:
            log.warning("рассылка: ушло, но не записалось в историю чата", exc_info=True)

    async def send_test(self, text: str, button: str) -> str:
        """Пробное сообщение — только владельцу в личку Telegram."""
        tg, url = await self._check(text, button)
        owner = (getattr(self.s, "telegram_owner_id", "") or "").strip()
        if not owner.lstrip("-").isdigit():
            raise HTTPException(400, "Не задан TELEGRAM_OWNER_ID — некому прислать пробное сообщение")
        chat = await self.brain.db.get_chat_by_jid(self.s.evolution_instance, f"{owner}@tg.chat")
        if chat is None:
            raise HTTPException(400, "Напиши Стелле в личку Telegram хоть одно сообщение — тогда пришлю пробное")
        try:
            await self._send(tg, chat, text, button, url)
        except Exception as exc:
            raise HTTPException(502, f"Telegram не принял сообщение: {exc}") from None
        return "пробное сообщение отправлено тебе в Telegram"

    async def _check(self, text: str, button: str) -> tuple[Any, str]:
        tg = self._tg()
        if tg is None:
            raise HTTPException(400, "Telegram не подключён (TELEGRAM_BOT_TOKEN)")
        if not text.strip() or len(text) > MAX_TEXT:
            raise HTTPException(400, f"Текст рассылки — от 1 до {MAX_TEXT} символов")
        if not button.strip() or len(button) > 40:
            raise HTTPException(400, "Надпись на кнопке — от 1 до 40 символов")
        self._url_checked = 0.0  # перед отправкой — всегда свежий адрес
        url = await self.fresh_url()
        if not url or not url.startswith("https://"):
            raise HTTPException(400, "Нет внешней https-ссылки на страницу: включи туннель (COMPOSE_PROFILES=panel) "
                                     "или задай GIVEAWAY_PUBLIC_URL")
        return tg, url

    async def start_broadcast(self, text: str, button: str, start_timer: bool) -> dict[str, Any]:
        async with self._start_lock:  # проверка «уже идёт» и запуск — без зазора для второго запроса
            if self._broadcast is not None and not self._broadcast.done():
                raise HTTPException(409, "Рассылка уже идёт")
            tg, url = await self._check(text, button)
            todo, _ = await self.recipients()
            if not todo:
                raise HTTPException(400, "Некому отправлять: все уже получили это сообщение, отписались или "
                                         "ещё никто не писал Стелле в личку Telegram")
            # таймер — только при первой рассылке круга: идущий отсчёт не двигаем, закрытую регистрацию не открываем
            if start_timer and not self.setting("draw_at") and self.setting("closed", "0") != "1":
                self.start_timer(TIMER_MINUTES)
            self.progress = {"state": "running", "total": len(todo), "sent": 0, "blocked": 0, "failed": 0,
                             "started_at": now_iso()}
            self._broadcast = asyncio.ensure_future(self._run_broadcast(tg, todo, text, button, url))
            if self.brain is not None:
                self.brain.tasks.add(self._broadcast)
                self._broadcast.add_done_callback(self.brain.tasks.discard)
            return dict(self.progress)

    def _claim(self, rnd: int, jid: str) -> bool:
        """Застолбить человека до отправки: второй запуск (или повтор после сбоя) ему уже не пришлёт."""
        with self._lock, self.db() as con:
            return con.execute("INSERT OR IGNORE INTO sent(round,chat_jid,at,outcome) VALUES(?,?,?,'pending')",
                               (rnd, jid, now_iso())).rowcount == 1

    def _settle(self, rnd: int, jid: str, outcome: str) -> None:
        with self._lock, self.db() as con:
            con.execute("UPDATE sent SET outcome=? WHERE round=? AND chat_jid=?", (outcome, rnd, jid))

    def _unclaim(self, rnd: int, jid: str) -> None:
        with self._lock, self.db() as con:
            con.execute("DELETE FROM sent WHERE round=? AND chat_jid=?", (rnd, jid))

    async def _deliver(self, tg: Any, chat: dict[str, Any], text: str, button: str, url: str) -> str:
        """-> sent | blocked (заблокировал бота, удалил аккаунт — больше не пробуем) | failed (можно позже)."""
        from .telegram import TelegramError

        for attempt in range(FLOOD_TRIES):
            try:
                await self._send(tg, chat, text, button, url)
                return "sent"
            except TelegramError as exc:
                msg = str(exc).lower()
                if any(w in msg for w in ("blocked", "deactivated", "chat not found", "forbidden")):
                    return "blocked"
                wait = getattr(exc, "retry_after", 0) or 0
                if wait and attempt < FLOOD_TRIES - 1:  # Telegram просит подождать — ждём сколько сказал
                    log.info("рассылка: Telegram просит подождать %s с", wait)
                    self.progress["waiting"] = min(wait, 300) + 1  # в админке: «пауза», а не «зависла»
                    await asyncio.sleep(min(wait, 300) + 1)
                    self.progress.pop("waiting", None)
                    continue
                log.warning("рассылка: не ушло: %s", exc)
                return "failed"
            except Exception:
                log.warning("рассылка: ошибка", exc_info=True)
                return "failed"
        return "failed"

    async def _run_broadcast(self, tg: Any, todo: list[dict[str, Any]], text: str, button: str, url: str) -> None:
        p = self.progress
        rnd = self.round()
        try:
            for chat in todo:
                if not self._claim(rnd, chat["jid"]):
                    p["total"] -= 1  # уже получил — от другого запуска
                    continue
                outcome = await self._deliver(tg, chat, text, button, url)
                p[outcome] += 1
                if outcome == "failed":
                    self._unclaim(rnd, chat["jid"])  # временная ошибка — при следующей рассылке попробуем снова
                else:
                    self._settle(rnd, chat["jid"], outcome)
                await asyncio.sleep(SEND_PAUSE)
        finally:
            p["state"] = "done"
            p["finished_at"] = now_iso()
            log.info("рассылка: доставлено %s из %s", p["sent"], p["total"])
            if self.brain is not None:
                try:
                    await self.brain.tell_owner(
                        f"📣 Рассылка о розыгрыше: доставлено {p['sent']} из {p['total']}"
                        + (f", заблокировали бота {p['blocked']}" if p["blocked"] else "")
                        + (f", не ушло {p['failed']} (попробую снова при следующей рассылке)" if p["failed"] else ""))
                except Exception:
                    log.warning("рассылка: не смогла сообщить владельцу", exc_info=True)

    async def on_callback(self, tg: Any, cb: dict[str, Any]) -> None:
        """Кнопка под сообщением рассылки: «Не присылать такое» — больше не шлём этому человеку."""
        answer: dict[str, Any] = {"callback_query_id": cb.get("id")}
        msg = cb.get("message") or {}
        chat = msg.get("chat") or {}
        if cb.get("data") == STOP_DATA and chat.get("id") is not None and chat.get("type") == "private":
            with self._lock, self.db() as con:
                con.execute("INSERT OR IGNORE INTO optout(chat_jid,at) VALUES(?,?)",
                            (f"{chat['id']}@tg.chat", now_iso()))
            answer["text"] = "Хорошо, больше не пришлю такие сообщения"
            keep = [row for row in ((msg.get("reply_markup") or {}).get("inline_keyboard") or [])
                    if not any(b.get("callback_data") == STOP_DATA for b in row)]
            try:
                await tg.call("editMessageReplyMarkup", data={
                    "chat_id": chat["id"], "message_id": msg.get("message_id"),
                    "reply_markup": {"inline_keyboard": keep}})
            except Exception:
                log.debug("рассылка: не смогла убрать кнопку", exc_info=True)
        try:
            await tg.call("answerCallbackQuery", data=answer)
        except Exception:
            log.debug("рассылка: не ответила на кнопку", exc_info=True)


def ip_key(ip: str) -> str:
    """IPv6 — по сети /64 (её целиком выдают одному абоненту: менять адрес внутри неё ничего не даёт)."""
    if ":" in ip:
        try:
            return str(ipaddress.ip_network(f"{ip}/64", strict=False))
        except ValueError:
            return ip
    return ip


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _row(r: sqlite3.Row) -> dict[str, Any]:
    return {k: r[k] for k in r.keys() if k != "token"}


def client_ip(request: Request) -> str:
    """Через туннель адрес человека — в CF-Connecting-IP (его ставит Cloudflare); X-Forwarded-For можно подделать."""
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "")


def is_https(request: Request) -> bool:
    return bool(request.headers.get("cf-connecting-ip")) or request.headers.get("x-forwarded-proto") == "https" \
        or request.url.scheme == "https"


class RegisterIn(BaseModel):
    first_name: str
    last_name: str | None = ""
    contact: str
    consent: bool
    captcha_id: str
    captcha_answer: str
    website: str | None = ""  # ловушка для ботов: человек это поле не видит
    invite: str | None = ""  # подпись из личной ссылки рассылки (?t=…)


class EmailIn(BaseModel):
    token: str
    email: str


class EnterIn(BaseModel):
    token: str


class DrawIn(BaseModel):
    only_with_email: bool = False
    only_invited: bool = False
    exclude_winners: bool = True


class SettingsIn(BaseModel):
    draw_minutes: int | None = None
    clear_timer: bool = False
    closed: bool | None = None
    prize: str | None = None


class SendIn(BaseModel):
    entry_id: int
    subject: str
    body: str
    to: str | None = None


class BroadcastIn(BaseModel):
    text: str
    button: str = DEFAULT_BUTTON
    test: bool = False
    start_timer: bool = True


def build_router(get_giveaway: Callable[[Request], Giveaway | None]) -> APIRouter:
    router = APIRouter(prefix=PREFIX)

    def gw(request: Request) -> Giveaway:
        g = get_giveaway(request)
        if g is None:
            raise HTTPException(404, "not found")
        return g

    def admin(request: Request) -> Giveaway:
        g = gw(request)
        if not g.is_admin(request):
            raise HTTPException(401, "Нужен вход: напиши Стелле в личку «/розыгрыш»")
        if request.method != "GET" and not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415, "нужен JSON")  # чужой сайт не сможет отправить форму от имени админа
        return g

    def page(name: str) -> FileResponse:
        return FileResponse(os.path.join(STATIC, name), media_type="text/html; charset=utf-8")

    # ---------- страницы ----------
    @router.get("", include_in_schema=False)
    async def root(request: Request) -> RedirectResponse:
        gw(request)
        return RedirectResponse(f"{PREFIX}/", status_code=307)

    @router.get("/")
    async def index(request: Request) -> FileResponse:
        gw(request)
        return page("index.html")

    @router.get("/admin")
    async def admin_page(request: Request) -> FileResponse:
        return page("admin.html" if gw(request).is_admin(request) else "enter.html")

    @router.get("/favicon.svg")
    async def favicon(request: Request) -> FileResponse:
        gw(request)
        return FileResponse(os.path.join(STATIC, "favicon.svg"), media_type="image/svg+xml")

    # ---------- участник ----------
    @router.get("/api/state")
    async def state(request: Request) -> dict[str, Any]:
        return await asyncio.to_thread(gw(request).state)

    @router.get("/api/captcha")
    async def captcha(request: Request) -> dict[str, Any]:
        g = gw(request)
        g.rate_limit(client_ip(request), 150, 60, "cap")
        return g.new_captcha()

    @router.post("/api/register")
    async def register(data: RegisterIn, request: Request) -> dict[str, Any]:
        g = gw(request)
        ip = client_ip(request)
        g.rate_limit(ip, 10, 600, "reg")  # 10 заявок за 10 минут с одного адреса (IPv6 — с одной сети /64)
        result = await asyncio.to_thread(g.register, data, ip, request.headers.get("user-agent", ""))
        alert = g.note_registration()
        if alert and g.brain is not None:
            g.brain.spawn(g.brain.tell_owner(alert))
        return result

    @router.post("/api/email")
    async def email(data: EmailIn, request: Request) -> dict[str, bool]:
        g = gw(request)
        g.rate_limit(client_ip(request), 10, 60, "mail")
        await asyncio.to_thread(g.save_email, data.token, data.email)
        return {"ok": True}

    # ---------- админка ----------
    @router.post("/api/admin/enter")
    async def enter(data: EnterIn, request: Request, response: Response) -> dict[str, bool]:
        g = gw(request)
        g.rate_limit(client_ip(request), 10, 300, "enter")
        if not g.use_link(data.token):
            raise HTTPException(401, "Ссылка устарела или уже использована — напиши Стелле «/розыгрыш» ещё раз")
        response.set_cookie(COOKIE, g.make_session(), max_age=SESSION_HOURS * 3600, path=PREFIX, httponly=True,
                            samesite="lax", secure=is_https(request))
        if g.brain is not None:
            g.brain.spawn(g.brain.tell_owner("🔐 Вход в админку розыгрыша"))
        return {"ok": True}

    @router.post("/api/admin/logout")
    async def logout(request: Request, response: Response) -> dict[str, bool]:
        g = gw(request)
        if g.is_admin(request):  # «Выйти» закрывает все входы (и на других устройствах)
            await asyncio.to_thread(g.logout_everywhere)
        response.delete_cookie(COOKIE, path=PREFIX)
        return {"ok": True}

    @router.get("/api/admin/entries")
    async def entries(request: Request) -> dict[str, Any]:
        g = admin(request)

        def collect() -> dict[str, Any]:
            return {"entries": g.entries(), "draw_at": g.setting("draw_at"), "closed": g.setting("closed", "0") == "1",
                    "prize": g.prize(), "round": g.round(),
                    "smtp": bool(getattr(g.s, "giveaway_smtp_host", "") and getattr(g.s, "giveaway_smtp_user", "")),
                    "smtp_from": getattr(g.s, "giveaway_smtp_from", "") or getattr(g.s, "giveaway_smtp_user", "")}
        return await asyncio.to_thread(collect)

    @router.post("/api/admin/draw")
    async def draw(data: DrawIn, request: Request) -> dict[str, Any]:
        g = admin(request)
        return await asyncio.to_thread(g.draw, data.only_with_email, data.exclude_winners, data.only_invited)

    @router.post("/api/admin/entries/{eid}/winner")
    async def toggle_winner(eid: int, request: Request) -> dict[str, bool]:
        g = admin(request)

        def toggle() -> None:
            with g._lock, g.db() as con:
                con.execute("UPDATE entries SET is_winner = 1 - is_winner WHERE id=?", (eid,))
        await asyncio.to_thread(toggle)
        return {"ok": True}

    @router.delete("/api/admin/entries/{eid}")
    async def delete_entry(eid: int, request: Request) -> dict[str, bool]:
        g = admin(request)

        def delete() -> None:
            with g._lock, g.db() as con:
                con.execute("DELETE FROM entries WHERE id=?", (eid,))
        await asyncio.to_thread(delete)
        return {"ok": True}

    @router.post("/api/admin/settings")
    async def settings(data: SettingsIn, request: Request) -> dict[str, bool]:
        g = admin(request)

        def apply() -> None:
            if data.draw_minutes:
                g.start_timer(max(1, min(data.draw_minutes, 24 * 60)))
            if data.clear_timer:
                g.set_setting("draw_at", None)
            if data.closed is not None:
                g.set_setting("closed", "1" if data.closed else "0")
            if data.prize:
                g.set_setting("prize", clean(data.prize, 120))
        await asyncio.to_thread(apply)
        return {"ok": True}

    @router.post("/api/admin/new_round")
    async def new_round(request: Request) -> dict[str, Any]:
        g = admin(request)
        if g._broadcast is not None and not g._broadcast.done():
            raise HTTPException(409, "Дождись конца рассылки")
        rnd = await asyncio.to_thread(g.new_round)
        g.progress = {"state": "idle"}
        return {"ok": True, "round": rnd}

    @router.post("/api/admin/send")
    async def send(data: SendIn, request: Request) -> dict[str, Any]:
        g = admin(request)
        to = await asyncio.to_thread(g.send_mail, data.entry_id, data.to, data.subject, data.body)
        return {"ok": True, "to": to}

    @router.get("/api/admin/export.csv")
    async def export(request: Request) -> Response:
        g = admin(request)
        body = await asyncio.to_thread(g.export_csv)
        return Response(body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=participants.csv"})

    @router.get("/api/admin/broadcast")
    async def broadcast_info(request: Request) -> dict[str, Any]:
        return await admin(request).broadcast_info()

    @router.post("/api/admin/broadcast")
    async def broadcast(data: BroadcastIn, request: Request) -> dict[str, Any]:
        g = admin(request)
        text, button = data.text.strip(), " ".join(data.button.split())
        if data.test:
            return {"ok": True, "message": await g.send_test(text, button)}
        return {"ok": True, "progress": await g.start_broadcast(text, button, data.start_timer)}

    return router
