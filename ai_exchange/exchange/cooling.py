"""Кнопка «Полная мощность»: включает в Windows «Активную» политику охлаждения системы.

Что это делает: при активном охлаждении Windows сначала раскручивает вентилятор и лишь потом снижает частоту процессора
(при «пассивном» — наоборот). Принудительно выставить 100% оборотов Windows не умеет: за обороты отвечает прошивка
ноутбука и утилита производителя (Lenovo Vantage, OMEN Hub, Armoury Crate, Dell Command и т.п.).

Исходные значения запоминаются в logs/cooling_prev.json, чтобы можно было вернуть как было.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Callable, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREV_PATH = os.path.join(ROOT, "logs", "cooling_prev.json")
ACTIVE, PASSIVE = 1, 0
LIMITS = ("Ровно 100% оборотов Windows задать не умеет. На ASUS VivoBook включите ещё режим «Производительность» "
          "в приложении MyASUS (Режим вентилятора) или нажмите Fn+F.")


def _run(args: list[str]) -> tuple[int, str]:
    r = subprocess.run(args, capture_output=True, text=True, timeout=15, errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


class Cooling:
    def __init__(self, runner: Callable[[list[str]], tuple[int, str]] = _run, windows: Optional[bool] = None,
                 prev_path: str = PREV_PATH):
        self.run = runner
        self.windows = sys.platform == "win32" if windows is None else windows
        self.prev_path = prev_path

    # ---------- чтение/запись политики ----------
    def get_policy(self) -> Optional[tuple[int, int]]:
        """(от сети, от батареи): 1 — активное, 0 — пассивное. Разбор по hex-значениям не зависит от языка Windows."""
        code, out = self.run(["powercfg", "/query", "SCHEME_CURRENT", "SUB_PROCESSOR", "SYSCOOLPOL"])
        vals = re.findall(r"0x[0-9a-fA-F]{8}", out)
        if code != 0 or len(vals) < 2:
            return None
        return int(vals[-2], 16), int(vals[-1], 16)

    def _set(self, ac: int, dc: int) -> tuple[bool, str]:
        for cmd in (["powercfg", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "SYSCOOLPOL", str(ac)],
                    ["powercfg", "/setdcvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "SYSCOOLPOL", str(dc)],
                    ["powercfg", "/setactive", "SCHEME_CURRENT"]):
            code, out = self.run(cmd)
            if code != 0:
                return False, out.strip()[:200]
        return True, ""

    def _save_prev(self, pol: tuple[int, int]) -> None:
        os.makedirs(os.path.dirname(self.prev_path), exist_ok=True)
        with open(self.prev_path, "w", encoding="utf-8") as f:
            json.dump({"ac": pol[0], "dc": pol[1]}, f)

    def _load_prev(self) -> Optional[tuple[int, int]]:
        try:
            with open(self.prev_path, encoding="utf-8") as f:
                d = json.load(f)
            return int(d["ac"]), int(d["dc"])
        except (OSError, ValueError, KeyError):
            return None

    # ---------- команды ----------
    def status(self) -> dict:
        if not self.windows:
            return {"supported": False, "active": False,
                    "message": "Доступно только в Windows (сейчас это другая система)."}
        pol = self.get_policy()
        return {"supported": True, "active": pol == (ACTIVE, ACTIVE), "policy": pol,
                "message": "Не удалось прочитать настройку охлаждения." if pol is None else ""}

    def enable(self) -> dict:
        if not self.windows:
            return {"ok": False, **self.status()}
        pol = self.get_policy()
        if pol == (ACTIVE, ACTIVE):
            return {"ok": True, "active": True, "supported": True, "message": "Активное охлаждение уже включено. " + LIMITS}
        if pol is not None:
            self._save_prev(pol)  # запоминаем исходное значение, чтобы можно было вернуть
        ok, err = self._set(ACTIVE, ACTIVE)
        if not ok:
            return {"ok": False, "active": False, "supported": True,
                    "message": f"Не удалось включить (возможно, нужны права администратора): {err}"}
        return {"ok": True, "active": True, "supported": True,
                "message": "Полная мощность охлаждения включена: вентилятор раскручивается раньше, чем процессор сбросит частоту. " + LIMITS}

    def restore(self) -> dict:
        if not self.windows:
            return {"ok": False, **self.status()}
        prev = self._load_prev() or (ACTIVE, PASSIVE)  # обычные значения Windows для ноутбука
        ok, err = self._set(*prev)
        if not ok:
            return {"ok": False, "active": True, "supported": True, "message": f"Не удалось вернуть настройку: {err}"}
        return {"ok": True, "active": prev == (ACTIVE, ACTIVE), "supported": True,
                "message": "Настройка охлаждения возвращена как была."}
