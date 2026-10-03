"""Системная громкость: PipeWire (wpctl) → PulseAudio (pactl) → ALSA (amixer)."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess

log = logging.getLogger("stella.volume")


def _run(args) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=3).stdout
    except Exception as e:
        log.debug("%s: %s", args[0], e)
        return ""


class SystemVolume:
    def __init__(self, cfg):
        method = cfg.get("audio.volume_control", "auto")
        self.control = cfg.get("audio.mixer_control", "Master")
        if method == "auto":
            method = next((m for m, exe in (("wpctl", "wpctl"), ("pactl", "pactl"), ("amixer", "amixer"))
                           if shutil.which(exe) and self._works(m)), "none")
        self.method = method
        self._soft = 60
        log.info("Громкость управляется через %s", self.method)

    def _works(self, m: str) -> bool:
        if m == "wpctl":
            return "Volume" in _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        if m == "pactl":
            return "%" in _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
        return "%" in _run(["amixer", "sget", self.control])

    def get(self) -> int:
        if self.method == "wpctl":
            m = re.search(r"Volume:\s*([\d.]+)", _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]))
            return int(round(float(m.group(1)) * 100)) if m else self._soft
        if self.method == "pactl":
            m = re.search(r"(\d+)%", _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"]))
            return int(m.group(1)) if m else self._soft
        if self.method == "amixer":
            m = re.search(r"\[(\d+)%\]", _run(["amixer", "sget", self.control]))
            return int(m.group(1)) if m else self._soft
        return self._soft

    def set(self, value: int) -> int:
        value = max(0, min(100, int(value)))
        if self.method == "wpctl":
            _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{value / 100:.2f}"])
        elif self.method == "pactl":
            _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{value}%"])
        elif self.method == "amixer":
            _run(["amixer", "-q", "sset", self.control, f"{value}%"])
        self._soft = value
        return value

    def change(self, delta: int) -> int:
        return self.set(self.get() + delta)

    def mute(self, on: bool = True):
        if self.method == "wpctl":
            _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if on else "0"])
        elif self.method == "pactl":
            _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if on else "0"])
        elif self.method == "amixer":
            _run(["amixer", "-q", "sset", self.control, "mute" if on else "unmute"])
