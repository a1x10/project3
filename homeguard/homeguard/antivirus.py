"""Антивирус HomeGuard: проверка ссылок и файлов.

Источники (чем больше настроено, тем точнее):
- свои базы блокировки и эвристики (без интернета): поддельные домены банков, punycode, IP вместо домена…
- Google Safe Browsing (ключ HG_GSB_KEY или в панели) — бесплатно;
- VirusTotal (ключ HG_VT_KEY или в панели) — бесплатный ключ, 4 запроса в минуту;
- ClamAV (если установлен clamscan/clamdscan) — локальная проверка файлов.

Плюс фоновый «сторож»: новые домены из журнала DNS проверяются через Safe Browsing
и опасные сразу попадают в блок-лист.
"""
import base64
import hashlib
import json
import logging
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import blocklists, config, db

log = logging.getLogger("homeguard.av")

# Официальные домены — всё похожее на них, но не они, подозрительно
BRANDS = {
    "sberbank": ["sberbank.ru", "sber.ru", "sberbank.com", "sberbank-online.ru"],
    "sber": ["sber.ru", "sberbank.ru", "sberbank.com", "sbermarket.ru", "sberdevices.ru"],
    "tinkoff": ["tinkoff.ru", "tbank.ru"], "tbank": ["tbank.ru", "tinkoff.ru"],
    "vtb": ["vtb.ru", "vtb.com"], "alfabank": ["alfabank.ru"], "gosuslugi": ["gosuslugi.ru"],
    "nalog": ["nalog.ru", "nalog.gov.ru"], "ozon": ["ozon.ru", "ozon.com"],
    "wildberries": ["wildberries.ru", "wb.ru"], "avito": ["avito.ru"], "yandex": ["yandex.ru", "ya.ru", "yandex.com"],
    "telegram": ["telegram.org", "t.me", "telegram.me"], "whatsapp": ["whatsapp.com", "whatsapp.net"],
    "vk": ["vk.com", "vk.ru", "vkontakte.ru"], "mail": ["mail.ru"], "apple": ["apple.com", "icloud.com"],
    "google": ["google.com", "google.ru", "youtube.com", "gmail.com"], "paypal": ["paypal.com"],
    "steam": ["steampowered.com", "steamcommunity.com"], "pochta": ["pochta.ru"],
    "rostelecom": ["rt.ru", "rostelecom.ru"], "mts": ["mts.ru"], "beeline": ["beeline.ru"],
}
RISKY_EXT = {".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".vbs", ".js", ".jse", ".wsf", ".ps1", ".msi",
             ".apk", ".jar", ".hta", ".lnk", ".docm", ".xlsm", ".pptm", ".iso", ".img"}
SHORTENERS = {"bit.ly", "clck.ru", "tinyurl.com", "cutt.ly", "goo.su", "is.gd", "t.co", "rebrand.ly", "u.to"}

RANK = {"safe": 0, "unknown": 0, "suspicious": 1, "danger": 2}


def _key(name: str) -> str:
    return getattr(config, name.upper()) or db.get_setting(name)


def keys_status() -> dict:
    return {"gsb": bool(_key("gsb_key")), "vt": bool(_key("vt_key")),
            "clamav": bool(shutil.which("clamdscan") or shutil.which("clamscan"))}


def _http_json(url: str, data: dict | None = None, headers: dict | None = None, timeout: float = 10.0):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _registered(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _lev1(a: str, b: str) -> bool:
    """Отличаются ровно одной правкой (sberbamk, sbebrank…)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1
                                  and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    s, l = (a, b) if len(a) < len(b) else (b, a)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def normalize_url(url: str) -> tuple[str, str]:
    url = url.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "http://" + url
    host = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("Не удалось разобрать ссылку")
    return url, host


def heuristics(url: str, host: str) -> list[dict]:
    f = []
    is_ip = re.fullmatch(r"[\d.]+", host) is not None
    if is_ip:
        f.append({"level": "suspicious", "source": "Эвристика", "text": "Вместо имени сайта — IP-адрес"})
    if "xn--" in host:
        f.append({"level": "suspicious", "source": "Эвристика",
                  "text": "Домен с национальными символами (punycode) — так подделывают известные сайты"})
    if "@" in urllib.parse.urlsplit(url).netloc:
        f.append({"level": "danger", "source": "Эвристика", "text": "В ссылке спрятан другой адрес через «@»"})
    if host.rsplit(".", 1)[-1] in blocklists.SUSPICIOUS_TLDS:
        f.append({"level": "suspicious", "source": "Эвристика", "text": f"Подозрительная зона .{host.rsplit('.', 1)[-1]}"})
    if host in SHORTENERS:
        f.append({"level": "suspicious", "source": "Эвристика", "text": "Сокращённая ссылка — непонятно, куда ведёт"})
    if host.count(".") >= 4:
        f.append({"level": "suspicious", "source": "Эвристика", "text": "Слишком длинная цепочка поддоменов"})
    reg = _registered(host)
    if not is_ip:
        labels = re.split(r"[.\-]", host)
        for brand, official in BRANDS.items():
            if reg in official or any(host.endswith("." + o) for o in official):
                continue
            if brand in labels or (len(brand) >= 5 and brand in host) or any(
                    len(brand) >= 5 and _lev1(lbl, brand) for lbl in labels):
                f.append({"level": "danger", "source": "Эвристика",
                          "text": f"Похоже на подделку «{brand}»: настоящий сайт — {official[0]}"})
                break
    path = urllib.parse.urlsplit(url).path.lower()
    if any(path.endswith(e) for e in RISKY_EXT):
        f.append({"level": "suspicious", "source": "Эвристика", "text": "Ссылка скачивает исполняемый файл"})
    return f


def _gsb(urls: list[str]) -> dict[str, str]:
    key = _key("gsb_key")
    if not key or not urls:
        return {}
    body = {"client": {"clientId": "homeguard", "clientVersion": "1.0"},
            "threatInfo": {"threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE",
                                           "POTENTIALLY_HARMFUL_APPLICATION"],
                           "platformTypes": ["ANY_PLATFORM"], "threatEntryTypes": ["URL"],
                           "threatEntries": [{"url": u} for u in urls[:500]]}}
    out = _http_json(f"{config.GSB_URL}?key={urllib.parse.quote(key)}", body)
    return {m["threat"]["url"]: m["threatType"] for m in out.get("matches", [])}


GSB_TEXT = {"MALWARE": "вредоносное ПО", "SOCIAL_ENGINEERING": "фишинг / мошенничество",
            "UNWANTED_SOFTWARE": "нежелательные программы", "POTENTIALLY_HARMFUL_APPLICATION": "опасные приложения"}


def _vt_stats(path: str) -> dict | None:
    key = _key("vt_key")
    if not key:
        return None
    try:
        out = _http_json(f"{config.VT_URL}/{path}", headers={"x-apikey": key})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    return out["data"]["attributes"].get("last_analysis_stats", {})


def _vt_finding(stats: dict | None) -> dict | None:
    if stats is None:
        return None
    if not stats:
        return {"level": "unknown", "source": "VirusTotal", "text": "Ещё не проверялось на VirusTotal"}
    bad, sus = stats.get("malicious", 0), stats.get("suspicious", 0)
    total = sum(stats.values()) or 1
    if bad >= 2:
        return {"level": "danger", "source": "VirusTotal", "text": f"Опасно по мнению {bad} из {total} антивирусов"}
    if bad or sus:
        return {"level": "suspicious", "source": "VirusTotal", "text": f"Подозрения у {bad + sus} из {total} антивирусов"}
    return {"level": "safe", "source": "VirusTotal", "text": f"Чисто по {total} антивирусам"}


def _verdict(findings: list[dict]) -> str:
    if not findings:
        return "safe"
    worst = max(findings, key=lambda x: RANK.get(x["level"], 0))["level"]
    return "safe" if worst == "unknown" else worst


def _save(kind: str, target: str, result: dict) -> dict:
    result["ts"] = time.time()
    db.execute("INSERT INTO av_checks (ts, kind, target, verdict, details) VALUES (?,?,?,?,?)",
               (result["ts"], kind, target[:500], result["verdict"], json.dumps(result["findings"], ensure_ascii=False)))
    return result


def check_url(raw: str) -> dict:
    try:
        url, host = normalize_url(raw)
    except ValueError as e:
        return {"target": raw, "verdict": "unknown", "findings": [{"level": "unknown", "source": "Ввод", "text": str(e)}]}
    findings = []
    blocked, reason = blocklists.check(host, "strict")
    if blocked and reason in ("malware", "phishing"):
        findings.append({"level": "danger", "source": "Базы HomeGuard",
                         "text": "Вредоносный сайт" if reason == "malware" else "Фишинговый сайт"})
    elif blocked and reason in ("ads", "trackers"):
        findings.append({"level": "safe", "source": "Базы HomeGuard", "text": "Рекламный/трекерный домен"})
    findings += heuristics(url, host)
    try:
        hit = _gsb([url])
        if hit:
            findings.append({"level": "danger", "source": "Google Safe Browsing",
                             "text": "Опасно: " + GSB_TEXT.get(next(iter(hit.values())), "угроза")})
        elif _key("gsb_key"):
            findings.append({"level": "safe", "source": "Google Safe Browsing", "text": "Угроз не найдено"})
    except (OSError, ValueError, KeyError) as e:
        log.warning("GSB: %s", e)
    try:
        vid = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        f = _vt_finding(_vt_stats(f"urls/{vid}"))
        if f:
            findings.append(f)
    except (OSError, ValueError, KeyError) as e:
        log.warning("VT: %s", e)
    return _save("url", url, {"target": url, "host": host, "verdict": _verdict(findings), "findings": findings})


def _clamav(data: bytes) -> dict | None:
    tool = shutil.which("clamdscan") or shutil.which("clamscan")
    if not tool:
        return None
    args = [tool, "--no-summary", "-"] if tool.endswith("clamscan") else [tool, "--no-summary", "--fdpass", "-"]
    try:
        p = subprocess.run(args, input=data, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode == 1:
        sig = p.stdout.decode(errors="ignore").split(":", 1)[-1].replace("FOUND", "").strip()
        return {"level": "danger", "source": "ClamAV", "text": f"Найден вирус: {sig}"}
    if p.returncode == 0:
        return {"level": "safe", "source": "ClamAV", "text": "Вирусов не найдено"}
    return None


def check_file(data: bytes, filename: str) -> dict:
    sha = hashlib.sha256(data).hexdigest()
    name = filename.lower()
    findings = []
    parts = name.rsplit(".", 2)
    ext = "." + parts[-1] if len(parts) > 1 else ""
    if len(parts) == 3 and "." + parts[1] in {".pdf", ".doc", ".docx", ".jpg", ".png", ".txt", ".xls", ".mp4"} \
            and ext in RISKY_EXT:
        findings.append({"level": "danger", "source": "Эвристика",
                         "text": f"Двойное расширение: выдаёт себя за {parts[1]}, а на деле {ext}"})
    elif ext in RISKY_EXT:
        findings.append({"level": "suspicious", "source": "Эвристика",
                         "text": f"Исполняемый файл ({ext}) — запускай, только если уверен в источнике"})
    if data[:2] == b"MZ" and ext not in {".exe", ".dll", ".scr", ".com", ".msi", ".sys"}:
        findings.append({"level": "danger", "source": "Эвристика", "text": "Внутри Windows-программа, хотя расширение другое"})
    f = _clamav(data)
    if f:
        findings.append(f)
    try:
        f = _vt_finding(_vt_stats(f"files/{sha}"))
        if f:
            findings.append(f)
    except (OSError, ValueError, KeyError) as e:
        log.warning("VT: %s", e)
    return _save("file", filename, {"target": filename, "sha256": sha, "size": len(data),
                                    "verdict": _verdict(findings), "findings": findings})


def history(limit: int = 50) -> list[dict]:
    rows = db.query("SELECT * FROM av_checks ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["findings"] = json.loads(r.pop("details"))
    return rows


VERDICT_TEXT = {"safe": "✅ Безопасно", "suspicious": "⚠️ Подозрительно", "danger": "⛔ Опасно", "unknown": "❔ Неизвестно"}


def verdict_text(r: dict) -> str:
    lines = [f"{VERDICT_TEXT[r['verdict']]}: <code>{r['target'][:200]}</code>"]
    for f in r["findings"]:
        lines.append(f"• {f['source']}: {f['text']}")
    return "\n".join(lines)


# ---------- фоновый сторож DNS ----------

def watch_once() -> int:
    """Проверяет через Safe Browsing домены, впервые замеченные в журнале. Возвращает число новых угроз."""
    if not _key("gsb_key"):
        return 0
    last = int(db.get_setting("av_watch_id") or 0)
    rows = db.query("SELECT MAX(id) m FROM queries")
    top = rows[0]["m"] or 0
    if top <= last:
        return 0
    new = {r["domain"] for r in db.query(
        "SELECT DISTINCT domain FROM queries WHERE id > ? AND action = 'allowed' LIMIT 500", (last,))}
    seen = {r["target"] for r in db.query("SELECT target FROM av_checks WHERE kind = 'domain'")}
    todo = sorted(new - seen)
    hits = _gsb([f"http://{d}/" for d in todo])
    found = 0
    for d in todo:
        threat = hits.get(f"http://{d}/")
        verdict = "danger" if threat else "safe"
        details = [{"level": verdict, "source": "Google Safe Browsing", "text": GSB_TEXT.get(threat, "чисто")}]
        db.execute("INSERT INTO av_checks (ts, kind, target, verdict, details) VALUES (?,?,?,?,?)",
                   (time.time(), "domain", d, verdict, json.dumps(details, ensure_ascii=False)))
        if threat:
            found += 1
            cat = "phishing" if threat == "SOCIAL_ENGINEERING" else "malware"
            path = config.BLOCKLIST_DIR / f"{cat}.watch.txt"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(d + "\n")
            from .telegram import bot
            bot.alert(f"☣ Антивирус нашёл опасный сайт <code>{d}</code> ({GSB_TEXT.get(threat)}). Уже заблокирован.",
                      key=f"watch:{d}")
    if found:
        blocklists.load(force=True)
    db.set_setting("av_watch_id", str(top))
    return found


def watch_loop(stop: threading.Event, interval: float = 60) -> None:
    while not stop.wait(interval):
        try:
            watch_once()
        except Exception:
            log.exception("Сторож антивируса")
