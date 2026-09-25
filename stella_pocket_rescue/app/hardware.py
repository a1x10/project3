"""Демон железа Stella: светодиоды, вентилятор и датчик землетрясения.

Запускается отдельной службой от root (stella-hw.service), потому что писать в
/sys/class/leds, GPIO и /dev/i2c-* обычному пользователю нельзя.

  python3 -m app.hardware

Что делает:
  * светодиоды платы (/sys/class/leds/*): в ожидании мигают спокойно («сердцебиение»),
    в режиме ЧС — часто вспыхивают;
  * вентилятор: если он подключён через транзистор к GPIO (номер в STELLA_FAN_GPIO),
    в режиме ЧС включается постоянно, в ожидании — по температуре процессора;
  * датчик MPU-6050 на I2C (необязательный, STELLA_SENSOR_I2C_BUS): при сильной
    продолжительной тряске сам переводит узел в режим ЧС.

Совместим с Python 3.8 и не требует сторонних библиотек.
"""
import fcntl
import glob
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import mode  # noqa: E402

TICK = 0.02                      # 50 Гц — частота опроса датчика
FAN_GPIO = os.getenv("STELLA_FAN_GPIO", "").strip()
FAN_TEMP_ON = float(os.getenv("STELLA_FAN_TEMP_ON", "60"))   # °C, в режиме ожидания
I2C_BUS = os.getenv("STELLA_SENSOR_I2C_BUS", "").strip()
I2C_ADDR = int(os.getenv("STELLA_SENSOR_ADDR", "0x68"), 16)
QUAKE_G = float(os.getenv("STELLA_QUAKE_G", "0.12"))         # порог отклонения от 1g
QUAKE_SECONDS = float(os.getenv("STELLA_QUAKE_SECONDS", "0.8"))


def log(*a):
    print("[stella-hw]", *a, flush=True)


def _write(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except OSError:
        return False


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


# ------------------------------------------------------------------ светодиоды
class Leds:
    def __init__(self):
        self.leds = sorted(p for p in glob.glob("/sys/class/leds/*") if os.path.exists(p + "/brightness"))
        self.saved = {}
        for p in self.leds:
            trig = _read(p + "/trigger") or ""
            cur = [t.strip("[]") for t in trig.split() if t.startswith("[")]
            self.saved[p] = cur[0] if cur else "none"
        self.has_timer = any("timer" in (_read(p + "/trigger") or "") for p in self.leds)
        self.manual = False
        self.phase = False
        log("светодиоды:", ", ".join(os.path.basename(p) for p in self.leds) or "не найдены")

    def standby(self):
        self.manual = False
        for p in self.leds:
            trig = _read(p + "/trigger") or ""
            _write(p + "/trigger", "heartbeat" if "heartbeat" in trig else self.saved.get(p, "none"))

    def emergency(self):
        if self.has_timer:
            self.manual = False
            for p in self.leds:
                _write(p + "/trigger", "timer")
                _write(p + "/delay_on", 120)
                _write(p + "/delay_off", 120)
        else:
            self.manual = True
            for p in self.leds:
                _write(p + "/trigger", "none")

    def tick(self, now):
        if not self.manual:
            return
        on = int(now * 4) % 2 == 0
        if on != self.phase:
            self.phase = on
            for p in self.leds:
                _write(p + "/brightness", _read(p + "/max_brightness") or 1 if on else 0)


# ------------------------------------------------------------------ вентилятор
class Fan:
    def __init__(self):
        self.path = None
        if not FAN_GPIO:
            log("вентилятор: STELLA_FAN_GPIO не задан — если кулер на пинах 5V, он крутится всегда")
            return
        base = "/sys/class/gpio/gpio" + FAN_GPIO
        if not os.path.exists(base):
            _write("/sys/class/gpio/export", FAN_GPIO)
            time.sleep(0.2)
        if _write(base + "/direction", "out"):
            self.path = base + "/value"
            log("вентилятор на GPIO", FAN_GPIO)
        else:
            log("вентилятор: не удалось настроить GPIO", FAN_GPIO)
        self.state = None

    def set(self, on):
        if self.path and on != self.state:
            self.state = on
            _write(self.path, 1 if on else 0)

    def auto(self):
        temps = [_read(p) for p in glob.glob("/sys/class/thermal/thermal_zone*/temp")]
        vals = [int(t) / 1000 for t in temps if t and t.lstrip("-").isdigit()]
        self.set(bool(vals) and max(vals) >= FAN_TEMP_ON)


# ------------------------------------------------------------------ датчик
class QuakeSensor:
    """MPU-6050 по I2C. Считаем отклонение модуля ускорения от 1g.
    Если отклонение держится выше порога заданное время — это землетрясение,
    а не случайный удар по столу."""
    I2C_SLAVE = 0x0703

    def __init__(self):
        self.fd = None
        self.base = 1.0
        self.shaking_since = None
        self.peak = 0.0
        if not I2C_BUS:
            log("датчик: не подключён (STELLA_SENSOR_I2C_BUS не задан) — режим ЧС включается кнопкой в консоли")
            return
        try:
            self.fd = os.open("/dev/i2c-" + I2C_BUS, os.O_RDWR)
            fcntl.ioctl(self.fd, self.I2C_SLAVE, I2C_ADDR)
            os.write(self.fd, bytes([0x6B, 0x00]))   # разбудить MPU-6050
            os.write(self.fd, bytes([0x1C, 0x00]))   # диапазон ±2g
            log("датчик MPU-6050 на /dev/i2c-%s, адрес 0x%02x" % (I2C_BUS, I2C_ADDR))
        except OSError as e:
            log("датчик: ошибка I2C:", e)
            self.fd = None

    def read_g(self):
        os.write(self.fd, bytes([0x3B]))
        ax, ay, az = struct.unpack(">hhh", os.read(self.fd, 6))
        return math.sqrt(ax * ax + ay * ay + az * az) / 16384.0

    def poll(self, now):
        """Возвращает строку-описание, если зафиксировано землетрясение."""
        if self.fd is None:
            return None
        try:
            g = self.read_g()
        except OSError:
            return None
        self.base += (g - self.base) * 0.002          # медленно следим за «покоем»
        dev = abs(g - self.base)
        if dev > QUAKE_G:
            self.peak = max(self.peak, dev)
            if self.shaking_since is None:
                self.shaking_since = now
            elif now - self.shaking_since >= QUAKE_SECONDS:
                note = "датчик: тряска %.2f g в течение %.1f с" % (self.peak, now - self.shaking_since)
                self.shaking_since, self.peak = None, 0.0
                return note
        elif self.shaking_since and now - self.shaking_since > QUAKE_SECONDS * 2:
            self.shaking_since, self.peak = None, 0.0
        return None


def main():
    leds, fan, sensor = Leds(), Fan(), QuakeSensor()
    current = None
    last_mode_check = 0
    while True:
        now = time.monotonic()
        note = sensor.poll(now)
        if note and mode.read()["mode"] != mode.EMERGENCY:
            log("ЗЕМЛЕТРЯСЕНИЕ:", note)
            mode.write(mode.EMERGENCY, "sensor", note)
        if now - last_mode_check >= 0.5:
            last_mode_check = now
            m = mode.read()["mode"]
            if m != current:
                current = m
                log("режим:", m)
                if m == mode.EMERGENCY:
                    leds.emergency()
                    fan.set(True)
                else:
                    leds.standby()
            if current != mode.EMERGENCY:
                fan.auto()
        leds.tick(now)
        time.sleep(TICK)


if __name__ == "__main__":
    main()
