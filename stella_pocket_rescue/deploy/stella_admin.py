#!/usr/bin/python3 -I
"""Помощник страницы настроек: делает то, на что нужны права root.

Сайт (пользователь stella) вызывает его так:  sudo -n /usr/local/sbin/stella-admin ДЕЙСТВИЕ
Параметры приходят JSON-объектом через stdin, ответ уходит JSON-объектом в stdout.
Секреты (PIN, пароль Wi-Fi) никогда не попадают в командную строку: sudo пишет ее в журнал,
а /proc/*/cmdline видят все пользователи платы.

Здесь только строгий список действий, каждый параметр проверяется. Ключ Anthropic, сервер туннеля,
домены, пароль администратора и SSH через туннель сайт менять не может: это делается только командой
stella на самой плате. Файл совместим с системным Python 3.8+ (Debian 11), сторонних библиотек нет.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

CLI = "/usr/local/bin/stella"
ENV_FILE = "/etc/stella/stella.env"
TUNNEL_ENV = "/etc/stella/tunnel.env"
TLS_DIR = "/etc/stella/tls"
JOBS_DIR = "/run/stella-admin"
RUN_DIR = "/run"
SELF = "/usr/local/sbin/stella-admin"
PYTHON = "/usr/bin/python3"
MODE_FILE_DEFAULT = "/var/lib/stella/mode.json"
APP_GROUP = "stella"
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
MAX_INPUT = 16384
JOB_TTL = 24 * 3600
JOB_DELAY = 2.0

PIN_RE = re.compile(r"^[0-9]{4,12}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{1,99}$")
SSID_RE = re.compile(r"^[A-Za-z0-9_.()+-](?:[A-Za-z0-9 _.()+-]{0,30}[A-Za-z0-9_.()+-])?$")
JOB_RE = re.compile(r"^[0-9a-f]{16}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_-]+")
PIN_LINE_RE = re.compile(r"(PIN[^0-9\n]{0,40})[0-9]{4,12}", re.IGNORECASE)
AI_MODES = ("auto", "cloud", "local", "offline")
POWER = ("auto", "normal", "safe", "off")
LOG_UNITS = ("app", "llm", "hw", "wifi", "dns", "nginx", "install", "home", "tunnel")
ENV_VALUE_RE = {
    "STELLA_RESCUER_PIN": PIN_RE,
    "STELLA_SSID": SSID_RE,
    "STELLA_CHANNEL": re.compile(r"^(?:[1-9]|1[0-3])$"),
}


class Refused(Exception):
    """Понятный отказ: текст уходит на страницу настроек."""


def clean_env():
    return {"PATH": SAFE_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb", "HOME": "/root"}


def read_params(stream=None):
    stream = stream or sys.stdin
    raw = stream.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise Refused("слишком большой запрос")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise Refused("параметры не в формате JSON")
    if not isinstance(data, dict):
        raise Refused("параметры должны быть объектом")
    return data


def text_param(params, name, required=True):
    value = params.get(name)
    if value is None or value == "":
        if required:
            raise Refused("не задан параметр %s" % name)
        return ""
    if not isinstance(value, str):
        raise Refused("параметр %s должен быть строкой" % name)
    return value


def check_pin(value):
    if not PIN_RE.fullmatch(value):
        raise Refused("PIN: от 4 до 12 цифр")
    return value


def check_choice(value, allowed, what):
    value = value.strip().lower()
    if value not in allowed:
        raise Refused("%s: допустимо %s" % (what, ", ".join(allowed)))
    return value


def check_model(value):
    if not MODEL_RE.fullmatch(value):
        raise Refused("странное имя модели (пример: claude-opus-5)")
    return value


def check_ssid(value):
    if not SSID_RE.fullmatch(value):
        raise Refused("имя сети SOS: 1-32 латинских символа, цифры, пробел и _ . ( ) + -, без пробелов по краям")
    return value


def check_channel(value):
    if isinstance(value, bool):
        raise Refused("канал: число от 1 до 13")
    try:
        channel = int(str(value).strip())
    except ValueError:
        raise Refused("канал: число от 1 до 13")
    if not 1 <= channel <= 13:
        raise Refused("канал: число от 1 до 13")
    return str(channel)


def check_home_ssid(value):
    if not value or len(value.encode("utf-8")) > 32:
        raise Refused("имя домашней сети: от 1 до 32 байт")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise Refused("в имени сети не должно быть служебных символов и переносов строки")
    return value


def check_wifi_password(value):
    if value == "":
        return value
    if not 8 <= len(value) <= 63 or any(ord(ch) < 32 or ord(ch) > 126 for ch in value):
        raise Refused("пароль Wi-Fi: от 8 до 63 латинских символов или пусто для открытой сети")
    return value


def check_job_id(value):
    if not isinstance(value, str) or not JOB_RE.fullmatch(value):
        raise Refused("неверный номер задачи")
    return value


def env_read(path=None):
    path = path or ENV_FILE
    values = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def env_write(updates, path=None):
    """Меняет строки KEY=VALUE атомарно, сохраняя владельца и права файла."""
    path = path or ENV_FILE
    for key, value in updates.items():
        rx = ENV_VALUE_RE.get(key)
        if rx is None or not isinstance(value, str) or not rx.fullmatch(value):
            raise Refused("недопустимое значение настройки %s" % key)
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        st = os.stat(path)
    except OSError:
        raise Refused("нет файла настроек %s: сначала установите Stella" % path)
    done = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key in updates:
            if key not in done:
                out.append("%s=%s" % (key, updates[key]))
                done.add(key)
            continue
        out.append(line)
    for key, value in updates.items():
        if key not in done:
            out.append("%s=%s" % (key, value))
    fd, tmp = tempfile.mkstemp(prefix=".stella.env.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
        os.chmod(tmp, st.st_mode & 0o7777)
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def emergency():
    mode_file = env_read().get("STELLA_MODE_FILE") or MODE_FILE_DEFAULT
    try:
        with open(mode_file, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("mode") == "emergency"


def refuse_in_emergency(what):
    if emergency():
        raise Refused("включен режим ЧС: %s сейчас нельзя, чтобы не оборвать связь с пострадавшими" % what)


def redact(text):
    text = ANSI_RE.sub("", text)
    text = KEY_RE.sub("sk-ant-***", text)
    return PIN_LINE_RE.sub(lambda m: m.group(1) + "******", text)


def run_cli(args, timeout=60):
    try:
        proc = subprocess.run([CLI] + list(args), env=clean_env(), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Refused("команда не уложилась в %d с" % timeout)
    except OSError as exc:
        raise Refused("не удалось запустить %s: %s" % (CLI, exc))
    return proc.returncode, redact(proc.stdout.decode("utf-8", "replace"))


def _group_id():
    try:
        import grp
        return grp.getgrnam(APP_GROUP).gr_gid
    except (ImportError, KeyError):
        return -1


def _jobs_dir():
    os.makedirs(JOBS_DIR, mode=0o750, exist_ok=True)
    os.chmod(JOBS_DIR, 0o750)
    gid = _group_id()
    if gid >= 0:
        try:
            os.chown(JOBS_DIR, 0, gid)
        except OSError:
            pass
    return JOBS_DIR


def _write(path, text, mode, shared):
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path + ".tmp", mode)
    if shared:
        gid = _group_id()
        if gid >= 0:
            try:
                os.chown(path + ".tmp", 0, gid)
            except OSError:
                pass
    os.replace(path + ".tmp", path)


def _state(job_id, **fields):
    _write(os.path.join(JOBS_DIR, job_id + ".state"), json.dumps(fields, ensure_ascii=False), 0o640, True)


def _cleanup_jobs(now=None):
    now = now or time.time()
    try:
        names = os.listdir(JOBS_DIR)
    except OSError:
        return
    for name in names:
        path = os.path.join(JOBS_DIR, name)
        try:
            if now - os.lstat(path).st_mtime > JOB_TTL:
                os.unlink(path)
        except OSError:
            pass


def start_job(kind, argv, timeout=900, title=""):
    """Запускает команду отдельной службой systemd: перезапуск сайта ее не оборвет,
    а ответ сайту успевает уйти до начала работы (задержка JOB_DELAY)."""
    _jobs_dir()
    _cleanup_jobs()
    job_id = secrets.token_hex(8)
    spec = {"kind": kind, "argv": list(argv), "timeout": int(timeout), "title": title, "created": time.time()}
    _write(os.path.join(JOBS_DIR, job_id + ".json"), json.dumps(spec, ensure_ascii=False), 0o600, False)
    _state(job_id, state="queued", kind=kind, title=title, created=spec["created"])
    runner = [PYTHON, "-I", SELF, "__job", job_id]
    started = False
    if shutil.which("systemd-run", path=SAFE_PATH) and os.path.isdir("/run/systemd/system"):
        proc = subprocess.run(["systemd-run", "--quiet", "--collect", "--unit", "stella-job-" + job_id,
                               "--description", "Stella Pocket: " + (title or kind)] + runner,
                              env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=20)
        started = proc.returncode == 0
    if not started:
        subprocess.Popen(runner, env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    return {"job": job_id, "kind": kind, "title": title}


def run_job(job_id):
    check_job_id(job_id)
    spec_path = os.path.join(JOBS_DIR, job_id + ".json")
    with open(spec_path, encoding="utf-8") as fh:
        spec = json.load(fh)
    os.unlink(spec_path)
    argv = [str(a) for a in spec["argv"]]
    log_path = os.path.join(JOBS_DIR, job_id + ".log")
    _write(log_path, "", 0o640, True)
    started = time.time()
    _state(job_id, state="running", kind=spec.get("kind"), title=spec.get("title"), started=started)
    time.sleep(JOB_DELAY)
    rc = -1
    try:
        with open(log_path, "ab") as log:
            proc = subprocess.run(argv, env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=spec.get("timeout", 900))
            log.write(redact(proc.stdout.decode("utf-8", "replace")).encode("utf-8"))
            rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = 124
    except OSError:
        rc = 127
    _state(job_id, state="ok" if rc == 0 else "fail", rc=rc, kind=spec.get("kind"), title=spec.get("title"),
           started=started, finished=time.time())
    return rc


def cli_job(kind, args, title, timeout=900):
    return start_job(kind, [CLI] + list(args), timeout=timeout, title=title)


def restart_app_job(title):
    return start_job("restart-app", ["systemctl", "restart", "stella-app"], timeout=120, title=title)


# ---------------------------------------------------------------- действия

def act_pin_set(params):
    pin = check_pin(text_param(params, "pin").strip())
    env_write({"STELLA_RESCUER_PIN": pin})
    return restart_app_job("новый PIN консоли")


def act_pin_new(params):
    pin = "%06d" % (100000 + secrets.randbelow(900000))
    env_write({"STELLA_RESCUER_PIN": pin})
    result = restart_app_job("новый PIN консоли")
    result["pin"] = pin
    return result


def act_ai_mode(params):
    mode = check_choice(text_param(params, "mode"), AI_MODES, "режим ИИ")
    return cli_job("ai-mode", ["ai", "mode", mode], "режим ИИ: " + mode, timeout=120)


def act_ai_model(params):
    model = check_model(text_param(params, "model").strip())
    return cli_job("ai-model", ["ai", "model", model], "облачная модель " + model, timeout=120)


def act_power_set(params):
    profile = check_choice(text_param(params, "profile"), POWER, "профиль питания")
    return cli_job("power", ["power", profile], "питание: " + profile, timeout=180)


def act_power_reset(params):
    return cli_job("power", ["power", "reset"], "сброс истории сбоев питания", timeout=180)


def act_wifi_ap(params):
    updates = {}
    ssid = params.get("ssid")
    if ssid not in (None, ""):
        if not isinstance(ssid, str):
            raise Refused("имя сети должно быть строкой")
        updates["STELLA_SSID"] = check_ssid(ssid)
    if params.get("channel") not in (None, ""):
        updates["STELLA_CHANNEL"] = check_channel(params.get("channel"))
    if not updates:
        raise Refused("укажите новое имя сети или канал")
    refuse_in_emergency("менять сеть SOS")
    env_write(updates)
    return cli_job("wifi", ["wifi", "apply"], "сеть SOS: новые настройки", timeout=120)


def act_wifi_home(params):
    ssid = check_home_ssid(text_param(params, "ssid"))
    password = check_wifi_password(text_param(params, "password", required=False))
    refuse_in_emergency("выключать сеть SOS")
    fd, secret = tempfile.mkstemp(prefix="stella-home.", dir=RUN_DIR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("%s\n%s\n" % (ssid, password))
    os.chmod(secret, 0o600)
    return start_job("wifi-home", ["/bin/bash", CLI, "__home-worker", secret], timeout=300,
                     title="переход в домашний Wi-Fi")


def act_wifi_sos(params):
    return start_job("wifi-sos", ["/bin/bash", CLI, "__sos-worker"], timeout=300, title="возврат сети SOS")


def act_remote_off(params):
    return start_job("remote-off", ["systemctl", "disable", "--now", "stella-tunnel"], timeout=60,
                     title="выключение удаленного доступа")


def act_remote_test(params):
    rc, out = run_cli(["remote", "test"], timeout=40)
    return {"rc": rc, "text": out[-4000:]}


def act_tls_sync(params):
    return cli_job("tls", ["tls", "sync"], "обновление сертификатов HTTPS", timeout=180)


def act_restart(params):
    return cli_job("restart", ["restart"], "перезапуск служб", timeout=240)


def act_reboot(params):
    refuse_in_emergency("перезагружать коробку")
    return start_job("reboot", ["systemctl", "reboot"], timeout=60, title="перезагрузка")


def act_poweroff(params):
    refuse_in_emergency("выключать коробку")
    return start_job("poweroff", ["systemctl", "poweroff"], timeout=60, title="выключение")


def act_update(params):
    return cli_job("update", ["update", "--github"], "обновление из интернета", timeout=3600)


def act_logs(params):
    unit = check_choice(text_param(params, "unit"), LOG_UNITS, "журнал")
    rc, out = run_cli(["logs", unit], timeout=30)
    lines = out.splitlines()[-300:]
    return {"rc": rc, "text": "\n".join(lines)}


def _sshd_password_auth():
    if not shutil.which("sshd", path=SAFE_PATH):
        return None
    try:
        proc = subprocess.run(["sshd", "-T"], env=clean_env(), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        if line.lower().startswith("passwordauthentication "):
            return line.split()[1].lower() == "yes"
    return None


def _default_passwords(candidates=(("root", "orangepi"), ("orangepi", "orangepi"))):
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import crypt
    except ImportError:
        return None
    found = []
    try:
        with open("/etc/shadow", encoding="utf-8") as fh:
            shadow = dict(line.split(":")[:2] for line in fh if line.count(":") >= 2)
    except OSError:
        return None
    for user, password in candidates:
        stored = shadow.get(user, "")
        if stored.startswith("$") and crypt.crypt(password, stored) == stored:
            found.append(user)
    return found


def _unit_state(unit):
    try:
        proc = subprocess.run(["systemctl", "is-active", unit], env=clean_env(), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        active = proc.stdout.decode().strip()
        proc = subprocess.run(["systemctl", "is-enabled", unit], env=clean_env(), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        return {"active": active, "enabled": proc.stdout.decode().strip()}
    except (OSError, subprocess.TimeoutExpired):
        return {"active": "unknown", "enabled": "unknown"}


def _tls_info():
    info = {"active": os.path.exists(os.path.join(TLS_DIR, "active"))}
    meta = os.path.join(TLS_DIR, "info.json")
    try:
        with open(meta, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            info.update({k: data[k] for k in ("domains", "not_after", "synced") if k in data})
    except (OSError, ValueError):
        pass
    return info


def act_info(params):
    return {
        "ssh_password_auth": _sshd_password_auth(),
        "default_passwords": _default_passwords(),
        "tunnel": _unit_state("stella-tunnel"),
        "tunnel_configured": os.path.exists(TUNNEL_ENV),
        "tls": _tls_info(),
        "emergency": emergency(),
    }


ACTIONS = {
    "pin.set": act_pin_set,
    "pin.new": act_pin_new,
    "ai.mode": act_ai_mode,
    "ai.model": act_ai_model,
    "power.set": act_power_set,
    "power.reset": act_power_reset,
    "wifi.ap": act_wifi_ap,
    "wifi.home": act_wifi_home,
    "wifi.sos": act_wifi_sos,
    "remote.off": act_remote_off,
    "remote.test": act_remote_test,
    "tls.sync": act_tls_sync,
    "restart": act_restart,
    "reboot": act_reboot,
    "poweroff": act_poweroff,
    "update": act_update,
    "logs": act_logs,
    "info": act_info,
}


def main(argv=None, stdin=None, stdout=None):
    argv = sys.argv[1:] if argv is None else argv
    stdout = stdout or sys.stdout
    if len(argv) == 2 and argv[0] == "__job":
        if os.environ.get("SUDO_USER") or os.geteuid() != 0:
            stdout.write(json.dumps({"ok": False, "error": "задачи запускает только сам помощник"}) + "\n")
            return 2
        return run_job(argv[1])
    if len(argv) != 1 or argv[0] not in ACTIONS:
        stdout.write(json.dumps({"ok": False, "error": "неизвестное действие"}, ensure_ascii=False) + "\n")
        return 2
    if os.geteuid() != 0:
        stdout.write(json.dumps({"ok": False, "error": "помощник запущен без прав root"}, ensure_ascii=False) + "\n")
        return 2
    os.umask(0o077)
    try:
        params = read_params(stdin)
        result = ACTIONS[argv[0]](params)
        payload = {"ok": True}
        payload.update(result or {})
        code = 0
    except Refused as exc:
        payload, code = {"ok": False, "error": str(exc)}, 1
    except Exception as exc:  # отказ не должен показывать стек на странице
        payload, code = {"ok": False, "error": "сбой помощника: %s" % type(exc).__name__}, 1
    stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
