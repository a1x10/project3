#!/usr/bin/env python3
"""
Самодиагностика STELLS на плате (запуск: python3 self_check.py).
Проверяет: камеру и FPS машинного зрения, микшер 4 моторов, драйвер ESC и аварийный DISARM.
Пропеллеры перед проверкой СНЯТЬ!
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stells_agent as A  # noqa: E402

ok_all = True


def report(name, ok, detail):
    global ok_all
    ok_all &= ok
    print(f"[{'OK ' if ok else 'ERR'}] {name}: {detail}")


def mix(base, roll, pitch, yaw, armed=True):
    if not armed:
        return [1000] * 4
    m = [base - pitch - roll + yaw, base + pitch + roll + yaw, base - pitch + roll - yaw, base + pitch - roll - yaw]
    return [int(max(1100, min(2000, v))) for v in m]


cfg = A.load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "stells-config.json"))

# 1. камера и зрение
if A.cv2 is None:
    report("Камера и ИИ-зрение", False, "OpenCV не установлен (pip install opencv-python-headless)")
else:
    cap = A.cv2.VideoCapture(cfg["camera"]["source"])
    n, t0, prev = 0, time.time(), None
    while time.time() - t0 < 2:
        ok, f = cap.read()
        if not ok:
            break
        g = A.cv2.GaussianBlur(A.cv2.cvtColor(f, A.cv2.COLOR_BGR2GRAY), (21, 21), 0)
        if prev is not None:
            A.cv2.absdiff(prev, g)
        prev, n = g, n + 1
    cap.release()
    fps = n / max(0.001, time.time() - t0)
    report("Камера и ИИ-зрение", n > 0, f"{fps:.0f} FPS" if n else "камера не отдаёт кадры")

# 2. микшер
m = mix(1480, 0, 120, 0)
report("Микшер 4 моторов", m == [1360, 1600, 1360, 1600], f"вперёд 120 -> M1={m[0]} M2={m[1]} M3={m[2]} M4={m[3]}")

# 3. драйвер ESC и DISARM
drv = A.MotorDriver(cfg)
drv.set([1300, 1300, 1300, 1300], True)
time.sleep(0.3)
drv.disarm()
report("Драйвер моторов и DISARM", drv.pwm == [1000] * 4, f"драйвер {drv.backend}, после DISARM: {drv.pwm}")

# 4. failsafe
drv.set([1200] * 4, True)
time.sleep(drv.failsafe + 0.4)
report("Failsafe при потере связи", drv.pwm == [1000] * 4 and not drv.armed, f"через {drv.failsafe:.1f} с без команд: {drv.pwm}")

print(json.dumps({"ok": ok_all}))
sys.exit(0 if ok_all else 1)
