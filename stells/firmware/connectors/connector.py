#!/usr/bin/env python3
"""
Коннектор STELLS (Python). Пульт приложения присылает команды JSON построчно в stdin,
вы пересылаете их своему дрону/роботу и печатаете телеметрию JSON в stdout.

Команды, которые приходят от пульта:
  {"type":"rc","roll":0,"pitch":0,"yaw":0,"throttle":0.5}
  {"type":"drone","cmd":"arm"|"disarm"|"takeoff"|"land"|"rtl","value":3}
  {"type":"drive","x":0,"y":0.5}

Телеметрия, которую понимает пульт (любые поля необязательны):
  {"type":"telemetry","drone":{"alt":1.2,"battery":87,"armed":true,"mode":"GUIDED","roll":0,"pitch":0,"yaw":90}}

Пример ниже подключается к дрону по MAVLink (UDP/serial). Если pymavlink нет — работает симулятор.
"""
import json
import sys
import threading
import time

CONNECTION = "udp:0.0.0.0:14550"   # или "/dev/ttyUSB0", "COM5", "tcp:192.168.4.1:5760"

state = {"alt": 0.0, "battery": 100, "armed": False, "mode": "SIM", "roll": 0, "pitch": 0, "yaw": 0}
try:
    from pymavlink import mavutil
    m = mavutil.mavlink_connection(CONNECTION)
    print(json.dumps({"type": "log", "text": f"MAVLink: жду heartbeat на {CONNECTION}…"}), flush=True)
    m.wait_heartbeat(timeout=5)
except Exception as e:
    m = None
    print(json.dumps({"type": "log", "text": f"Симулятор (MAVLink недоступен: {e})"}), flush=True)


def handle(cmd):
    t = cmd.get("type")
    if t == "drone":
        c = cmd.get("cmd")
        if m:
            if c == "arm": m.arducopter_arm()
            elif c == "disarm": m.arducopter_disarm()
            elif c == "takeoff":
                m.set_mode("GUIDED")
                m.mav.command_long_send(m.target_system, m.target_component,
                                        mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, float(cmd.get("value", 3)))
            elif c == "land": m.set_mode("LAND")
            elif c == "rtl": m.set_mode("RTL")
        else:
            state["armed"] = c in ("arm", "takeoff") or (state["armed"] and c not in ("disarm", "land"))
            state["mode"] = {"takeoff": "GUIDED", "land": "LAND", "rtl": "RTL"}.get(c, state["mode"])
            if c == "takeoff": state["alt"] = float(cmd.get("value", 3))
    elif t == "rc":
        if m:
            m.mav.manual_control_send(m.target_system, int(cmd["pitch"] * 1000), int(cmd["roll"] * 1000),
                                      int(cmd["throttle"] * 1000), int(cmd["yaw"] * 1000), 0)
        else:
            state["roll"], state["pitch"] = cmd["roll"] * 30, cmd["pitch"] * 30
            state["yaw"] = (state["yaw"] + cmd["yaw"] * 5) % 360
            if state["armed"]: state["alt"] = max(0, state["alt"] + (cmd["throttle"] - 0.5) * 0.4)


def telemetry():
    while True:
        if m:
            msg = m.recv_match(type=["GLOBAL_POSITION_INT", "SYS_STATUS", "ATTITUDE", "HEARTBEAT"], blocking=True, timeout=1)
            if msg and msg.get_type() == "GLOBAL_POSITION_INT": state["alt"] = msg.relative_alt / 1000
            if msg and msg.get_type() == "SYS_STATUS": state["battery"] = msg.battery_remaining
            if msg and msg.get_type() == "ATTITUDE": state.update(roll=msg.roll * 57.3, pitch=msg.pitch * 57.3, yaw=msg.yaw * 57.3)
            if msg and msg.get_type() == "HEARTBEAT": state.update(armed=bool(msg.base_mode & 128), mode=mavutil.mode_string_v10(msg))
        else:
            if state["armed"]: state["battery"] = max(0, state["battery"] - 0.02)
            time.sleep(0.25)
        print(json.dumps({"type": "telemetry", "drone": state}), flush=True)


threading.Thread(target=telemetry, daemon=True).start()
for line in sys.stdin:
    try:
        handle(json.loads(line))
    except Exception as e:
        print(json.dumps({"type": "log", "text": f"ошибка: {e}"}), flush=True)
