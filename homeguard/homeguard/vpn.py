"""Менеджер VPN: профили WireGuard / OpenVPN, подключение, NAT для всей сети, kill switch.

Профили из интернета могут содержать команды, которые выполняются от root
(PostUp в WireGuard, up/script-security в OpenVPN), поэтому при импорте такие строки вырезаются.
"""
from __future__ import annotations
import logging
import re
import shutil
import subprocess
import time
import uuid

from . import config, db

log = logging.getLogger("homeguard.vpn")

COUNTRIES = {  # код: (название, синонимы в имени файла/профиля)
    "NL": ("Нидерланды", ["netherlands", "nederland", "holland", "amsterdam"]),
    "DE": ("Германия", ["germany", "deutschland", "frankfurt", "berlin"]),
    "FI": ("Финляндия", ["finland", "helsinki"]),
    "SE": ("Швеция", ["sweden", "stockholm"]),
    "US": ("США", ["usa", "united states", "america", "newyork", "new-york", "ashburn"]),
    "GB": ("Великобритания", ["uk", "united kingdom", "england", "london"]),
    "FR": ("Франция", ["france", "paris"]),
    "PL": ("Польша", ["poland", "warsaw"]),
    "KZ": ("Казахстан", ["kazakhstan", "almaty", "astana"]),
    "TR": ("Турция", ["turkey", "istanbul"]),
    "AE": ("ОАЭ", ["uae", "emirates", "dubai"]),
    "JP": ("Япония", ["japan", "tokyo"]),
    "SG": ("Сингапур", ["singapore"]),
    "CH": ("Швейцария", ["switzerland", "zurich"]),
    "LV": ("Латвия", ["latvia", "riga"]),
    "EE": ("Эстония", ["estonia", "tallinn"]),
    "RU": ("Россия", ["russia", "moscow"]),
}

WG_FORBIDDEN = {"preup", "postup", "predown", "postdown", "saveconfig", "dns", "table"}
OVPN_FORBIDDEN = {"up", "down", "plugin", "script-security", "route-up", "route-pre-down", "ipchange",
                  "tls-verify", "auth-user-pass-verify", "client-connect", "client-disconnect",
                  "learn-address", "management", "dev", "dev-type", "daemon", "writepid", "log", "log-append",
                  "setenv-safe"}


WG_KINDS = {"wireguard", "amneziawg"}
WG_TOOL = {"wireguard": "wg-quick", "amneziawg": "awg-quick"}


class VpnError(Exception):
    pass


def flag(code: str | None) -> str:
    if not code or len(code) != 2:
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code.upper())


def guess_country(text: str) -> str | None:
    t = text.lower()
    for code, (_name, words) in COUNTRIES.items():
        if re.search(rf"(?<![a-z]){code.lower()}(?![a-z])", t) or any(w in t for w in words):
            return code
    return None


def detect_kind(content: str) -> str:
    if "[Interface]" in content and "[Peer]" in content:
        # AmneziaWG — WireGuard с маскировкой (параметры Jc, Jmin, S1, H1…), нужен awg-quick
        if re.search(r"^\s*(Jc|Jmin|Jmax|S1|S2|H1|H2|H3|H4)\s*=", content, re.M | re.I):
            return "amneziawg"
        return "wireguard"
    if re.search(r"^\s*(client|remote\s+\S+)", content, re.M) and re.search(r"^\s*remote\s+\S+", content, re.M):
        return "openvpn"
    raise VpnError("Не похоже на конфиг WireGuard (.conf) или OpenVPN (.ovpn)")


def sanitize(kind: str, content: str) -> tuple[str, str | None]:
    """Вырезает опасные директивы. Возвращает (текст, endpoint)."""
    content = content.replace("\r\n", "\n").replace("\x00", "")
    if len(content) > 100_000:
        raise VpnError("Файл слишком большой")
    out, endpoint = [], None
    if kind in WG_KINDS:
        for line in content.split("\n"):
            key = line.split("=", 1)[0].strip().lower()
            if key in WG_FORBIDDEN:
                continue
            if key == "endpoint":
                endpoint = line.split("=", 1)[1].strip()
            out.append(line)
        text = "\n".join(out)
        if not re.search(r"^\s*PrivateKey\s*=", text, re.M | re.I) or not endpoint:
            raise VpnError("В конфиге WireGuard нет PrivateKey или Endpoint")
        return text.strip() + "\n", endpoint
    # openvpn: <ca>...</ca> блоки оставляем как есть, директивы фильтруем только вне блоков
    in_block = False
    for line in content.split("\n"):
        s = line.strip()
        if re.match(r"^</?[a-z\-]+>$", s, re.I):
            in_block = s.startswith("<") and not s.startswith("</")
            out.append(line)
            continue
        if not in_block and s and not s.startswith(("#", ";")):
            word = s.split()[0].lower()
            if word in OVPN_FORBIDDEN:
                continue
            if word == "remote" and endpoint is None and len(s.split()) >= 2:
                parts = s.split()
                endpoint = parts[1] + (":" + parts[2] if len(parts) > 2 else "")
        out.append(line)
    if endpoint is None:
        raise VpnError("В .ovpn нет строки remote")
    return "\n".join(out).strip() + "\n", endpoint


class Runner:
    """Запуск системных команд; в dry-run только запоминает их."""

    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        self.history: list[list[str]] = []

    def run(self, cmd: list[str], check: bool = True) -> str:
        self.history.append(cmd)
        if self.dry_run:
            return ""
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise VpnError(f"Не удалось выполнить {cmd[0]}: {e}")
        if check and p.returncode != 0:
            raise VpnError(f"{' '.join(cmd[:2])}: {(p.stderr or p.stdout).strip()[:300]}")
        return p.stdout


def lan_iface(runner: Runner) -> str:
    if config.LAN_IFACE:
        return config.LAN_IFACE
    out = runner.run(["ip", "-4", "route", "show", "default"], check=False)
    m = re.search(r"default via \S+ dev (\S+)", out)
    return m.group(1) if m else "eth0"


def firewall_rules(lan: str, vpn: str, kill_switch: bool) -> list[list[str]]:
    """Правила (в формате «-A»); для отката те же команды с «-D» вместо «-A»."""
    rules = [
        ["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", vpn, "-j", "MASQUERADE"],
        ["iptables", "-A", "FORWARD", "-i", lan, "-o", vpn, "-j", "ACCEPT"],
        ["iptables", "-A", "FORWARD", "-i", vpn, "-o", lan, "-m", "state",
         "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"],
    ]
    if kill_switch:  # весь остальной транзит из LAN режется, пока нет туннеля
        rules.append(["iptables", "-A", "FORWARD", "-i", lan, "!", "-o", vpn, "-j", "DROP"])
    return rules


class VpnManager:
    def __init__(self, runner: Runner | None = None):
        self.runner = runner or Runner(config.VPN_DRYRUN)
        self._rules: list[list[str]] = []
        self._last_error: str | None = None
        self._connected_at: float | None = None

    # ---- профили ----
    def _path(self, pid: str, kind: str):
        return config.VPN_DIR / f"{pid}.{'conf' if kind in WG_KINDS else 'ovpn'}"

    def add_profile(self, name: str, content: str, country: str | None = None,
                    username: str | None = None, password: str | None = None) -> dict:
        name = name.strip()[:60]
        if not name:
            raise VpnError("Укажи название")
        kind = detect_kind(content)
        text, endpoint = sanitize(kind, content)
        country = (country or "").upper() or guess_country(name) or guess_country(endpoint or "")
        if country and country not in COUNTRIES:
            raise VpnError("Неизвестный код страны")
        pid = uuid.uuid4().hex[:8]
        config.VPN_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._path(pid, kind).write_text(text, encoding="utf-8")
        self._path(pid, kind).chmod(0o600)
        has_auth = bool(username and password)
        if has_auth:
            auth = config.VPN_DIR / f"{pid}.auth"
            auth.write_text(f"{username}\n{password}\n", encoding="utf-8")
            auth.chmod(0o600)
        db.execute("INSERT INTO vpn_profiles VALUES (?,?,?,?,?,?,?)",
                   (pid, name, country, kind, endpoint, int(has_auth), time.time()))
        return self.profile(pid)

    def profile(self, pid: str) -> dict:
        rows = db.query("SELECT * FROM vpn_profiles WHERE id = ?", (pid,))
        if not rows:
            raise VpnError("Профиль не найден")
        return self._view(rows[0])

    @staticmethod
    def _view(r: dict) -> dict:
        r["flag"] = flag(r["country"])
        r["country_name"] = COUNTRIES.get(r["country"], (None,))[0]
        return r

    def profiles(self) -> list[dict]:
        return [self._view(r) for r in db.query("SELECT * FROM vpn_profiles ORDER BY created")]

    def delete_profile(self, pid: str) -> None:
        p = self.profile(pid)
        if db.get_setting("vpn_active") == pid:
            self.disconnect()
        for f in (self._path(pid, p["kind"]), config.VPN_DIR / f"{pid}.auth"):
            f.unlink(missing_ok=True)
        db.execute("DELETE FROM vpn_profiles WHERE id = ?", (pid,))

    # ---- подключение ----
    def connect(self, pid: str) -> None:
        p = self.profile(pid)
        if db.get_setting("vpn_active"):
            self.disconnect()
        if not self.runner.dry_run:
            tool = WG_TOOL.get(p["kind"], "openvpn")
            if not shutil.which(tool) or not shutil.which("iptables"):
                raise VpnError(f"Не установлены {tool} и/или iptables")
        iface = config.VPN_IFACE
        src = self._path(pid, p["kind"])
        try:
            if p["kind"] in WG_KINDS:
                tool = WG_TOOL[p["kind"]]
                run_conf = config.VPN_DIR / f"{iface}.conf"
                run_conf.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                run_conf.chmod(0o600)
                self.runner.run([tool, "down", str(run_conf)], check=False)
                self.runner.run([tool, "up", str(run_conf)])
            else:
                cmd = ["openvpn", "--config", str(src), "--daemon", "hgvpn", "--dev", iface, "--dev-type", "tun",
                       "--writepid", str(config.VPN_DIR / "openvpn.pid"), "--redirect-gateway", "def1",
                       "--connect-retry-max", "3"]
                auth = config.VPN_DIR / f"{pid}.auth"
                if auth.exists():
                    cmd += ["--auth-user-pass", str(auth)]
                self.runner.run(cmd)
                self._wait_iface(iface)
            self._apply_firewall()
        except VpnError as e:
            self._last_error = str(e)
            self._teardown(p["kind"])
            raise
        self._last_error = None
        self._connected_at = time.time()
        db.set_setting("vpn_active", pid)

    def _wait_iface(self, iface: str, timeout: float = 25.0) -> None:
        if self.runner.dry_run:
            return
        end = time.time() + timeout
        while time.time() < end:
            if subprocess.run(["ip", "link", "show", iface], capture_output=True).returncode == 0:
                return
            time.sleep(1)
        raise VpnError("OpenVPN не поднял туннель за 25 с — проверь логин/пароль и сервер")

    def _apply_firewall(self) -> None:
        self.runner.run(["sysctl", "-w", "net.ipv4.ip_forward=1"], check=False)
        self._rules = firewall_rules(lan_iface(self.runner), config.VPN_IFACE, self.kill_switch)
        for r in self._rules:
            self.runner.run(r)

    def _teardown(self, kind: str | None = None) -> None:
        for r in reversed(self._rules):
            self.runner.run([("-D" if a == "-A" else a) for a in r], check=False)
        self._rules = []
        iface = config.VPN_IFACE
        run_conf = config.VPN_DIR / f"{iface}.conf"
        if kind is None or kind in WG_KINDS:
            self.runner.run([WG_TOOL.get(kind, "wg-quick"), "down", str(run_conf)], check=False)
            run_conf.unlink(missing_ok=True)
        if kind in (None, "openvpn"):
            pidf = config.VPN_DIR / "openvpn.pid"
            if pidf.exists():
                self.runner.run(["kill", pidf.read_text().strip()], check=False)
                pidf.unlink(missing_ok=True)

    def disconnect(self) -> None:
        pid = db.get_setting("vpn_active")
        kind = None
        if pid:
            rows = db.query("SELECT kind FROM vpn_profiles WHERE id = ?", (pid,))
            kind = rows[0]["kind"] if rows else None
        self._teardown(kind)
        self._connected_at = None
        db.set_setting("vpn_active", "")

    # ---- состояние ----
    @property
    def kill_switch(self) -> bool:
        return db.get_setting("vpn_kill_switch") == "1"

    def set_kill_switch(self, on: bool) -> None:
        db.set_setting("vpn_kill_switch", "1" if on else "0")
        if db.get_setting("vpn_active"):  # перестроить правила
            for r in reversed(self._rules):
                self.runner.run([("-D" if a == "-A" else a) for a in r], check=False)
            self._apply_firewall()

    def tunnel_up(self) -> bool:
        if self.runner.dry_run:
            return bool(db.get_setting("vpn_active"))
        return subprocess.run(["ip", "link", "show", config.VPN_IFACE], capture_output=True).returncode == 0

    def status(self) -> dict:
        active = db.get_setting("vpn_active") or None
        if active and self.tunnel_up():
            state = "connected"
        elif active:
            state = "down"  # профиль выбран, но туннель пропал
        else:
            state = "disconnected"
        return {"active": active, "state": state, "kill_switch": self.kill_switch,
                "dry_run": self.runner.dry_run, "error": self._last_error,
                "since": self._connected_at, "profiles": self.profiles()}

    def restore(self) -> None:
        """После перезапуска сервиса поднять последний выбранный профиль."""
        pid = db.get_setting("vpn_active")
        if pid:
            db.set_setting("vpn_active", "")
            try:
                self.connect(pid)
            except VpnError as e:
                log.warning("Не удалось восстановить VPN: %s", e)


manager = VpnManager()
