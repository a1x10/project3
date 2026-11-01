#!/usr/bin/env python3
"""
STELLS Vision — локальное машинное зрение на компьютере.
Запускается приложением STELLS автоматически при каждом старте.

Источник: веб-камера компьютера (0) или поток с платы (http://<ip>:8766/stream).
Анализ: детектор движения + модели ONNX из папки моделей (YOLOv5/YOLOv8 через cv2.dnn).
Результат:  http://127.0.0.1:8090/stream       — видео с разметкой
            http://127.0.0.1:8090/detections   — JSON с объектами
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

state = {"jpeg": None, "detections": [], "fps": 0.0, "model": None, "source": None}
lock = threading.Lock()


def load_model(models_dir):
    if not models_dir or not os.path.isdir(models_dir):
        return None, []
    for f in sorted(os.listdir(models_dir)):
        if f.endswith(".onnx"):
            p = os.path.join(models_dir, f)
            try:
                net = cv2.dnn.readNetFromONNX(p)
                lbl = os.path.splitext(p)[0] + ".txt"
                labels = [l.strip() for l in open(lbl, encoding="utf-8")] if os.path.exists(lbl) else []
                print("Модель:", f, flush=True)
                state["model"] = f
                return net, labels
            except Exception as e:
                print("Модель", f, "не загружена:", e, flush=True)
    return None, []


def yolo(net, labels, frame, conf_t=0.45):
    h, w = frame.shape[:2]
    net.setInput(cv2.dnn.blobFromImage(frame, 1 / 255.0, (640, 640), swapRB=True))
    out = net.forward()[0]
    if out.shape[0] < out.shape[1]:
        out = out.T
    boxes, scores, ids = [], [], []
    v8 = out.shape[1] == 84 or (labels and out.shape[1] == 4 + len(labels))
    for r in out:
        cs = r[4:] if v8 else r[5:] * r[4]
        c = int(np.argmax(cs))
        s = float(cs[c])
        if s < conf_t:
            continue
        cx, cy, bw, bh = r[:4]
        boxes.append([int((cx - bw / 2) * w / 640), int((cy - bh / 2) * h / 640), int(bw * w / 640), int(bh * h / 640)])
        scores.append(s)
        ids.append(c)
    res = []
    for i in cv2.dnn.NMSBoxes(boxes, scores, conf_t, 0.5):
        i = int(i)
        res.append({"label": labels[ids[i]] if ids[i] < len(labels) else f"class {ids[i]}",
                    "score": round(scores[i], 2), "box": boxes[i]})
    return res


def capture_loop(source, models_dir):
    net, labels = load_model(models_dir)
    src = int(source) if str(source).isdigit() else source
    state["source"] = str(source)
    cap = cv2.VideoCapture(src)
    prev, t0, n = None, time.time(), 0
    while True:
        ok, frame = cap.read()
        if not ok:
            time.sleep(1)
            cap.release()
            cap = cv2.VideoCapture(src)
            continue
        dets = []
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (21, 21), 0)
        if prev is not None:
            th = cv2.dilate(cv2.threshold(cv2.absdiff(prev, gray), 25, 255, cv2.THRESH_BINARY)[1], None, iterations=2)
            for c in cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
                if cv2.contourArea(c) > 900:
                    dets.append({"label": "движение", "score": 1.0, "box": list(cv2.boundingRect(c))})
        prev = gray
        if net is not None:
            try:
                dets += yolo(net, labels, frame)
            except Exception as e:
                print("Ошибка модели:", e, flush=True)
                net = None
        for d in dets:
            x, y, w, h = d["box"]
            col = (0, 220, 255) if d["label"] == "движение" else (255, 120, 40)
            cv2.rectangle(frame, (x, y), (x + w, y + h), col, 2)
            cv2.putText(frame, f'{d["label"]} {d["score"]:.2f}', (x, max(12, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        with lock:
            if ok:
                state["jpeg"] = jpg.tobytes()
            state["detections"] = dets
        n += 1
        if time.time() - t0 >= 1:
            state["fps"] = round(n / (time.time() - t0), 1)
            t0, n = time.time(), 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    with lock:
                        j = state["jpeg"]
                    if j:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + j + b"\r\n")
                    time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            body = json.dumps({"fps": state["fps"], "model": state["model"], "source": state["source"],
                               "detections": state["detections"]}).encode()
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="0")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--models", default="")
    a = ap.parse_args()
    threading.Thread(target=capture_loop, args=(a.source, a.models), daemon=True).start()
    print(f"STELLS Vision: http://127.0.0.1:{a.port}/stream  (источник {a.source})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
