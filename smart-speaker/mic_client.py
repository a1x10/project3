"""Микрофон для колонки на плате: берёт звук с микрофона этого компьютера и шлёт его
на плату (phone_speaker.py) по WebSocket. Браузер не нужен.

Запуск: python mic_client.py --host 192.168.8.11
"""
import argparse
import json
import ssl
import sys
import threading
import time

import pyaudio
from websockets.sync.client import connect

RATE = 16000
CHUNK = 1600  # 100 мс

STATES = {
    "loading": "загружаю слух…",
    "idle": "жду слово пробуждения",
    "connecting": "подключаюсь…",
    "listening": "слушаю вас",
    "speaking": "колонка говорит",
}


def list_devices():
    pa = pyaudio.PyAudio()
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        if d["maxInputChannels"] > 0:
            print(f"{i}: {d['name']}")
    pa.terminate()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.8.11", help="IP платы")
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--device", type=int, default=None, help="номер микрофона (см. --list-devices)")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()
    if args.list_devices:
        return list_devices()

    url = f"wss://{args.host}:{args.port}/ws"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False          # у платы самоподписанный сертификат
    ctx.verify_mode = ssl.CERT_NONE

    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=RATE, input=True,
                     input_device_index=args.device, frames_per_buffer=CHUNK)
    muted = [False]
    current = [None]  # текущее соединение, чтобы Enter мог отправить «заглушить»

    def keyboard():
        for _ in sys.stdin:
            muted[0] = not muted[0]
            ws = current[0]
            if ws:
                try:
                    ws.send(json.dumps({"type": "mute", "value": muted[0]}))
                except Exception:
                    pass
            print("Микрофон " + ("ВЫКЛЮЧЕН" if muted[0] else "включён"), flush=True)

    threading.Thread(target=keyboard, daemon=True).start()
    print(f"Микрофон -> {url}\nEnter: заглушить / включить микрофон. Ctrl+C: выход.", flush=True)

    def reader(ws):
        last = None
        for raw in ws:
            if not isinstance(raw, str):
                continue
            m = json.loads(raw)
            if m["type"] == "state" and m["state"] != last:
                last = m["state"]
                print("•", STATES.get(last, last), flush=True)
            elif m["type"] == "msg":
                print(("Вы: " if m["role"] == "user" else "Колонка: ") + m["text"], flush=True)
            elif m["type"] == "muted":
                muted[0] = m["value"]

    while True:
        try:
            with connect(url, ssl=ctx, open_timeout=6, max_size=None) as ws:
                current[0] = ws
                print("Соединено с колонкой.", flush=True)
                threading.Thread(target=reader, args=(ws,), daemon=True).start()
                while True:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    if not muted[0]:
                        ws.send(data)
        except KeyboardInterrupt:
            break
        except Exception as e:
            current[0] = None
            print(f"Нет связи с платой ({e}). Повтор через 3 с…", flush=True)
            time.sleep(3)
    stream.stop_stream(); stream.close(); pa.terminate()


if __name__ == "__main__":
    main()
