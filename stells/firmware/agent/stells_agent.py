#!/usr/bin/env python3
"""
STELLS Agent — программа, которая работает на плате (Raspberry Pi, Banana Pi,
ODROID, NanoPi, Orange Pi, Jetson и др.) и даёт приложению STELLS на компьютере
удалённо управлять платой, моделью и машинным зрением.

Возможности:
  * WebSocket-управление          ws://<ip>:8765
  * Видеопоток с камеры (MJPEG)   http://<ip>:8766/stream   (+ /snapshot, /detections)
  * Машинное зрение на плате: детектор движения + модель ONNX (YOLO) из папки models/
  * Машины / роботы: моторы через драйвер L298N/TB6612 (gpiozero), сервоприводы
  * Дроны: MAVLink (ArduPilot / PX4) через UART или USB — arm, взлёт, посадка, RTL, RC
  * Wake-on-LAN с платы
  * Автопоиск в сети: UDP 48765 (приложение находит плату само)

Запуск:  python3 stells_agent.py  [--config stells-config.json]
Все модули необязательны: если библиотеки нет, функция просто отключается.
"""
import argparse
import asyncio
import json
import os
import platform
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"
HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------ опции
try:
    import websockets  # pip install websockets
except ImportError:
    websockets = None
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None
try:
    from gpiozero import Motor, AngularServo, LED, OutputDevice
except Exception:
    Motor = AngularServo = LED = OutputDevice = None
try:
    from pymavlink import mavutil
except ImportError:
    mavutil = None

DEFAULTS = {
    "name": socket.gethostname(),
    "token": "",                 # если задан — приложение должно прислать его в hello
    "agent": {"port": 8765, "streamPort": 8766, "discoveryPort": 48765},
    "camera": {"source": 0, "width": 640, "height": 480, "fps": 20},
    "vision": {"motion": True, "model": "", "confidence": 0.45},
    "car": {"left": [17, 18], "right": [22, 23], "lights": 27},
    "robot": {"servos": [12, 13, 19, 26]},
    "drone": {"connection": "/dev/serial0", "baud": 57600,
              # driver: auto | esc | mavlink | sim. esc — регуляторы напрямую на GPIO (M1..M4)
              "driver": "auto", "escPins": [17, 18, 27, 22], "escHz": 50, "failsafeMs": 500},
}


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULTS))
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


# ------------------------------------------------------------------ система
def system_info():
    info = {"host": socket.gethostname(), "os": platform.platform(), "arch": platform.machine()}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            info["temp"] = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        pass
    try:
        info["load"] = round(os.getloadavg()[0], 2)
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            mem = {l.split(":")[0]: int(l.split()[1]) for l in f if ":" in l}
        info["memTotal"] = mem.get("MemTotal", 0) // 1024
        info["memUsed"] = (mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)) // 1024
    except Exception:
        pass
    try:
        with open("/proc/uptime") as f:
            info["uptime"] = int(float(f.read().split()[0]))
    except Exception:
        pass
    try:
        with open("/proc/device-tree/model") as f:
            info["model"] = f.read().strip("\x00\n ")
    except Exception:
        pass
    return info


# ------------------------------------------------------------------ зрение
class Vision:
    """Захват камеры + детекция движения + (опционально) модель ONNX YOLO."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.frame_jpeg = None
        self.detections = []
        self.fps = 0.0
        self.lock = threading.Lock()
        self.net = None
        self.labels = []
        self.running = cv2 is not None
        if not self.running:
            log("OpenCV не установлен — видеопоток отключён (pip install opencv-python-headless)")
            return
        self._load_model(cfg["vision"].get("model"))
        threading.Thread(target=self._loop, daemon=True).start()

    def _load_model(self, name):
        models_dir = os.path.join(HERE, "models")
        path = os.path.join(models_dir, name) if name else None
        if not path:
            os.makedirs(models_dir, exist_ok=True)
            onnx = [f for f in os.listdir(models_dir) if f.endswith(".onnx")]
            path = os.path.join(models_dir, onnx[0]) if onnx else None
        if path and os.path.exists(path):
            try:
                self.net = cv2.dnn.readNetFromONNX(path)
                lbl = os.path.splitext(path)[0] + ".txt"
                if os.path.exists(lbl):
                    self.labels = [l.strip() for l in open(lbl, encoding="utf-8")]
                log("Модель загружена:", os.path.basename(path))
            except Exception as e:
                log("Не удалось загрузить модель:", e)

    def _yolo(self, frame):
        h, w = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(frame, 1 / 255.0, (640, 640), swapRB=True, crop=False)
        self.net.setInput(blob)
        out = self.net.forward()
        out = out[0]
        if out.shape[0] < out.shape[1]:  # YOLOv8: (84, 8400) -> (8400, 84)
            out = out.T
        boxes, scores, ids = [], [], []
        conf_t = float(self.cfg["vision"].get("confidence", 0.45))
        for row in out:
            cls_scores = row[4:] if row.shape[0] in (84, 4 + len(self.labels or [])) else row[5:] * row[4]
            cid = int(np.argmax(cls_scores))
            sc = float(cls_scores[cid])
            if sc < conf_t:
                continue
            cx, cy, bw, bh = row[:4]
            x = (cx - bw / 2) * w / 640
            y = (cy - bh / 2) * h / 640
            boxes.append([int(x), int(y), int(bw * w / 640), int(bh * h / 640)])
            scores.append(sc)
            ids.append(cid)
        res = []
        for i in cv2.dnn.NMSBoxes(boxes, scores, conf_t, 0.5):
            i = int(i)
            label = self.labels[ids[i]] if ids[i] < len(self.labels) else f"class {ids[i]}"
            res.append({"label": label, "score": round(scores[i], 2), "box": boxes[i]})
        return res

    def _loop(self):
        c = self.cfg["camera"]
        src = c["source"]
        cap = cv2.VideoCapture(int(src) if str(src).isdigit() else src)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, c["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, c["height"])
        prev = None
        t0, n = time.time(), 0
        while self.running:
            ok, frame = cap.read()
            if not ok:
                time.sleep(1)
                cap.release()
                cap = cv2.VideoCapture(int(src) if str(src).isdigit() else src)
                continue
            dets = []
            gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (21, 21), 0)
            if self.cfg["vision"].get("motion", True) and prev is not None:
                delta = cv2.threshold(cv2.absdiff(prev, gray), 25, 255, cv2.THRESH_BINARY)[1]
                delta = cv2.dilate(delta, None, iterations=2)
                cnts, _ = cv2.findContours(delta, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for cn in cnts:
                    if cv2.contourArea(cn) < 900:
                        continue
                    x, y, w, h = cv2.boundingRect(cn)
                    dets.append({"label": "движение", "score": 1.0, "box": [x, y, w, h]})
            prev = gray
            if self.net is not None:
                try:
                    dets += self._yolo(frame)
                except Exception as e:
                    log("Ошибка модели:", e)
                    self.net = None
            for d in dets:
                x, y, w, h = d["box"]
                color = (0, 220, 255) if d["label"] == "движение" else (255, 120, 40)
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(frame, f'{d["label"]} {d["score"]:.2f}', (x, max(12, y - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            with self.lock:
                self.frame_jpeg = jpg.tobytes() if ok else self.frame_jpeg
                self.detections = dets
            n += 1
            if time.time() - t0 >= 1:
                self.fps = n / (time.time() - t0)
                t0, n = time.time(), 0
            time.sleep(max(0, 1 / c["fps"] - 0.001))


def make_http_handler(vision):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")

        def do_GET(self):
            if self.path.startswith("/stream"):
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        with vision.lock:
                            jpg = vision.frame_jpeg
                        if jpg:
                            self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                             + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                        time.sleep(0.05)
                except (BrokenPipeError, ConnectionResetError):
                    return
            elif self.path.startswith("/snapshot"):
                with vision.lock:
                    jpg = vision.frame_jpeg
                if not jpg:
                    self.send_error(503, "camera not ready")
                    return
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(jpg)
            elif self.path.startswith("/detections"):
                body = json.dumps({"fps": round(vision.fps, 1), "detections": vision.detections}).encode()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h1>STELLS Agent</h1><img src='/stream'>".encode())

    return H


# ------------------------------------------------------------------ приводы
class Car:
    def __init__(self, cfg):
        self.ok = Motor is not None
        if not self.ok:
            log("gpiozero недоступен — управление моторами в режиме симуляции")
            return
        try:
            c = cfg["car"]
            self.left = Motor(*c["left"])
            self.right = Motor(*c["right"])
            self.lights = LED(c["lights"]) if c.get("lights") else None
        except Exception as e:
            log("Моторы не инициализированы:", e)
            self.ok = False

    def drive(self, x, y):
        """x: поворот -1..1, y: газ -1..1 (дифференциальное управление)."""
        l = max(-1, min(1, y + x))
        r = max(-1, min(1, y - x))
        if self.ok:
            for m, v in ((self.left, l), (self.right, r)):
                m.forward(v) if v >= 0 else m.backward(-v)
        return {"left": round(l, 2), "right": round(r, 2)}

    def stop(self):
        if self.ok:
            self.left.stop()
            self.right.stop()

    def set_lights(self, on):
        if self.ok and self.lights:
            self.lights.on() if on else self.lights.off()


class Robot:
    def __init__(self, cfg):
        self.servos = []
        if AngularServo is None:
            return
        for pin in cfg["robot"]["servos"]:
            try:
                self.servos.append(AngularServo(pin, min_angle=-90, max_angle=90))
            except Exception as e:
                log("Серво", pin, "недоступно:", e)

    def set(self, idx, angle):
        if 0 <= idx < len(self.servos):
            self.servos[idx].angle = max(-90, min(90, float(angle)))
            return True
        return False


class Drone:
    """MAVLink-управление полётным контроллером (ArduPilot / PX4)."""

    def __init__(self, cfg):
        self.cfg = cfg["drone"]
        self.m = None
        self.tel = {}
        if mavutil is None:
            log("pymavlink не установлен — дрон в режиме симуляции (pip install pymavlink)")
            return
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self):
        while self.m is None:
            try:
                log("MAVLink: подключение к", self.cfg["connection"])
                m = mavutil.mavlink_connection(self.cfg["connection"], baud=int(self.cfg["baud"]))
                m.wait_heartbeat(timeout=10)
                if m.target_system == 0:
                    raise RuntimeError("нет heartbeat")
                self.m = m
                log("MAVLink: полётный контроллер найден, system", m.target_system)
                m.mav.request_data_stream_send(m.target_system, m.target_component,
                                               mavutil.mavlink.MAV_DATA_STREAM_ALL, 5, 1)
                threading.Thread(target=self._read, daemon=True).start()
            except Exception as e:
                log("MAVLink недоступен:", e, "— повтор через 5 с")
                time.sleep(5)

    def _read(self):
        while True:
            msg = self.m.recv_match(blocking=True, timeout=1)
            if not msg:
                continue
            t = msg.get_type()
            if t == "GLOBAL_POSITION_INT":
                self.tel.update(lat=msg.lat / 1e7, lon=msg.lon / 1e7, alt=msg.relative_alt / 1000,
                                heading=msg.hdg / 100)
            elif t == "ATTITUDE":
                self.tel.update(roll=round(msg.roll * 57.3, 1), pitch=round(msg.pitch * 57.3, 1),
                                yaw=round(msg.yaw * 57.3, 1))
            elif t == "SYS_STATUS":
                self.tel.update(battery=msg.battery_remaining, voltage=msg.voltage_battery / 1000)
            elif t == "HEARTBEAT":
                self.tel.update(armed=bool(msg.base_mode & 128), mode=mavutil.mode_string_v10(msg))
            elif t == "VFR_HUD":
                self.tel.update(speed=round(msg.groundspeed, 1), climb=round(msg.climb, 1))
            elif t == "GPS_RAW_INT":
                self.tel.update(sats=msg.satellites_visible, fix=msg.fix_type)

    def command(self, cmd, value=None):
        if self.m is None:
            return {"sim": True, "cmd": cmd}
        m = self.m
        if cmd == "arm":
            m.arducopter_arm()
        elif cmd == "disarm":
            m.arducopter_disarm()
        elif cmd == "mode":
            m.set_mode(m.mode_mapping()[value])
        elif cmd == "takeoff":
            m.set_mode(m.mode_mapping()["GUIDED"])
            m.mav.command_long_send(m.target_system, m.target_component,
                                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, float(value or 3))
        elif cmd == "land":
            m.set_mode(m.mode_mapping()["LAND"])
        elif cmd == "rtl":
            m.set_mode(m.mode_mapping()["RTL"])
        return {"ok": True, "cmd": cmd}

    def rc(self, roll, pitch, yaw, throttle):
        """Значения -1..1 (throttle 0..1) -> MANUAL_CONTROL."""
        if self.m is None:
            return
        self.m.mav.manual_control_send(self.m.target_system, int(pitch * 1000), int(roll * 1000),
                                       int(throttle * 1000), int(yaw * 1000), 0)


class MotorDriver:
    """Прямое управление 4 регуляторами (ESC) с GPIO платы.
    Raspberry Pi 4/3/Zero -> pigpio (нужен демон pigpiod), Raspberry Pi 5 -> lgpio.
    Без библиотек — режим симуляции (значения пишутся в лог/телеметрию).
    Порядок: M1 передний правый, M2 задний левый, M3 передний левый, M4 задний правый."""
    PWM_MIN, PWM_MAX = 1000, 2000

    def __init__(self, cfg):
        d = cfg["drone"]
        self.pins = list(d.get("escPins", [17, 18, 27, 22]))
        self.hz = int(d.get("escHz", 50))
        self.failsafe = int(d.get("failsafeMs", 500)) / 1000
        self.pwm = [self.PWM_MIN] * 4
        self.armed = False
        self.last = 0
        self.backend = "sim"
        self.h = None
        model = ""
        try:
            with open("/proc/device-tree/model") as f:
                model = f.read()
        except Exception:
            pass
        want = d.get("driver", "auto")
        if want in ("auto", "esc"):
            if "Raspberry Pi 5" in model:
                self._try_lgpio() or self._try_pigpio()
            else:
                self._try_pigpio() or self._try_lgpio()
        log(f"Драйвер моторов: {self.backend} (пины {self.pins})")
        self.write([self.PWM_MIN] * 4)
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _try_pigpio(self):
        try:
            import pigpio
            pi = pigpio.pi()
            if not pi.connected:
                raise RuntimeError("демон pigpiod не запущен (sudo systemctl enable --now pigpiod)")
            self.h, self.backend = pi, "pigpio"
            return True
        except Exception as e:
            log("pigpio недоступен:", e)
            return False

    def _try_lgpio(self):
        try:
            import lgpio
            for chip in (4, 0):  # на Pi 5 GPIO заголовка — gpiochip4 (или 0 на новых ядрах)
                try:
                    h = lgpio.gpiochip_open(chip)
                    break
                except Exception:
                    h = None
            if h is None:
                raise RuntimeError("gpiochip не найден")
            for p in self.pins:
                lgpio.gpio_claim_output(h, p)
            self.h, self.backend, self._lg = h, "lgpio", lgpio
            return True
        except Exception as e:
            log("lgpio недоступен:", e)
            return False

    def write(self, pwm):
        pwm = [int(max(self.PWM_MIN, min(self.PWM_MAX, v))) for v in pwm]
        self.pwm = pwm
        if self.backend == "pigpio":
            for p, v in zip(self.pins, pwm):
                self.h.set_servo_pulsewidth(p, v)
        elif self.backend == "lgpio":
            for p, v in zip(self.pins, pwm):
                self._lg.tx_servo(self.h, p, v, self.hz)

    def set(self, pwm, armed):
        self.last = time.time()
        self.armed = bool(armed)
        self.write(pwm if self.armed else [self.PWM_MIN] * 4)

    def disarm(self):
        self.armed = False
        self.write([self.PWM_MIN] * 4)

    def _watchdog(self):
        # нет команд дольше failsafe -> моторы в 1000 мкс
        while True:
            time.sleep(0.1)
            if self.armed and time.time() - self.last > self.failsafe:
                log("Failsafe: связь потеряна — DISARM")
                self.disarm()


def send_wol(mac, broadcast="255.255.255.255", port=9):
    hexmac = "".join(c for c in mac if c in "0123456789abcdefABCDEF")
    pkt = b"\xff" * 6 + bytes.fromhex(hexmac) * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.sendto(pkt, (broadcast, port))
    s.close()


# ------------------------------------------------------------------ сеть
def discovery_responder(cfg):
    port = cfg["agent"]["discoveryPort"]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", port))
    info = {"stells": True, "name": cfg["name"], "board": cfg.get("board"), "version": VERSION,
            "port": cfg["agent"]["port"], "streamPort": cfg["agent"]["streamPort"]}
    log("Автопоиск: UDP", port)
    while True:
        data, addr = s.recvfrom(256)
        if data.startswith(b"STELLS_DISCOVER"):
            s.sendto(json.dumps(info).encode(), addr)


async def main_ws(cfg, vision, car, robot, drone, motors=None):
    async def handler(ws):
        authed = not cfg.get("token")
        log("Подключился клиент", ws.remote_address)
        last_cmd = time.time()

        async def telemetry():
            while True:
                await asyncio.sleep(0.5)
                # failsafe: нет команд движения 1.5 с -> стоп моторов
                if time.time() - last_cmd > 1.5:
                    car.stop()
                tel = dict(drone.tel)
                if motors:
                    tel.update(motors=motors.pwm, motorDriver=motors.backend)
                    tel.setdefault("armed", motors.armed)
                await ws.send(json.dumps({"type": "telemetry", "system": system_info(), "drone": tel,
                                          "vision": {"fps": round(vision.fps, 1) if vision else 0,
                                                     "detections": vision.detections if vision else []}}))

        task = asyncio.create_task(telemetry())
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                t = msg.get("type")
                if t == "hello":
                    authed = authed or msg.get("token") == cfg.get("token")
                    await ws.send(json.dumps({"type": "welcome", "ok": authed, "name": cfg["name"],
                                              "version": VERSION, "system": system_info(),
                                              "features": {"camera": cv2 is not None, "gpio": Motor is not None,
                                                           "mavlink": mavutil is not None}}))
                    continue
                if not authed:
                    await ws.send(json.dumps({"type": "error", "reason": "unauthorized"}))
                    continue
                last_cmd = time.time()
                if t == "drive":
                    res = car.drive(float(msg.get("x", 0)), float(msg.get("y", 0)))
                    await ws.send(json.dumps({"type": "ack", "drive": res}))
                elif t == "stop":
                    car.stop()
                elif t == "lights":
                    car.set_lights(bool(msg.get("on")))
                elif t == "servo":
                    robot.set(int(msg.get("index", 0)), msg.get("angle", 0))
                elif t == "drone":
                    if msg.get("cmd") == "disarm" and motors:
                        motors.disarm()
                    await ws.send(json.dumps({"type": "ack", "drone": drone.command(msg.get("cmd"), msg.get("value"))}))
                elif t == "motors":
                    if motors and (drone.m is None):          # есть полётный контроллер -> управляем через MAVLink
                        motors.set(msg.get("pwm", [1000] * 4), msg.get("armed", False))
                    if msg.get("ack"):
                        await ws.send(json.dumps({"type": "ack", "motors": {"driver": motors.backend if motors else "none",
                                                                            "pwm": motors.pwm if motors else [1000] * 4}}))
                elif t == "rc":
                    drone.rc(float(msg.get("roll", 0)), float(msg.get("pitch", 0)),
                             float(msg.get("yaw", 0)), float(msg.get("throttle", 0)))
                elif t == "wol":
                    send_wol(msg.get("mac", ""), msg.get("broadcast", "255.255.255.255"))
                    await ws.send(json.dumps({"type": "ack", "wol": True}))
                elif t == "model":
                    if vision:
                        vision._load_model(msg.get("file"))
                elif t == "ping":
                    await ws.send(json.dumps({"type": "pong", "t": msg.get("t")}))
        except Exception as e:
            log("Клиент отключился:", e)
        finally:
            task.cancel()
            car.stop()
            if motors:
                motors.disarm()

    async with websockets.serve(handler, "0.0.0.0", cfg["agent"]["port"], max_size=2 ** 22):
        log(f"WebSocket-управление: ws://0.0.0.0:{cfg['agent']['port']}")
        await asyncio.Future()


def main():
    ap = argparse.ArgumentParser(description="STELLS Agent")
    ap.add_argument("--config", default=os.path.join(HERE, "..", "stells-config.json"))
    args = ap.parse_args()
    cfg = load_config(args.config)
    log(f"STELLS Agent {VERSION} на {cfg['name']}")

    vision = Vision(cfg) if cv2 is not None else None
    if vision:
        srv = ThreadingHTTPServer(("0.0.0.0", cfg["agent"]["streamPort"]), make_http_handler(vision))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log(f"Видеопоток: http://0.0.0.0:{cfg['agent']['streamPort']}/stream")
    threading.Thread(target=discovery_responder, args=(cfg,), daemon=True).start()

    car, robot, drone = Car(cfg), Robot(cfg), Drone(cfg)
    want = cfg["drone"].get("driver", "auto")
    motors = MotorDriver(cfg) if want in ("auto", "esc", "sim") else None
    if websockets is None:
        log("Нет библиотеки websockets: pip install websockets")
        return
    asyncio.run(main_ws(cfg, vision, car, robot, drone, motors))


if __name__ == "__main__":
    main()
