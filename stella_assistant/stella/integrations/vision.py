"""Камера (необязательно): Стелла следит глазами за лицом человека и радуется, когда кто-то подходит.
Нужен OpenCV (python3-opencv) и камера Raspberry Pi (Picamera2) или USB-вебкамера."""
from __future__ import annotations

import logging
import threading
import time

from ..core.events import bus

log = logging.getLogger("stella.vision")


class Vision(threading.Thread):
    def __init__(self, assistant):
        super().__init__(daemon=True, name="vision")
        self.a = assistant
        self.cfg = assistant.cfg
        self.present = False
        self.last_seen = 0.0

    def _camera(self):
        try:
            from picamera2 import Picamera2
            cam = Picamera2()
            cam.configure(cam.create_preview_configuration(main={"size": (640, 480), "format": "RGB888"}))
            cam.start()
            return lambda: cam.capture_array()
        except Exception:
            import cv2
            cap = cv2.VideoCapture(int(self.cfg.get("vision.camera", 0)))
            if not cap.isOpened():
                raise RuntimeError("камера не найдена")
            return lambda: cap.read()[1]

    def run(self):
        try:
            import cv2
            grab = self._camera()
        except Exception as e:
            log.warning("Камера недоступна: %s", e)
            return
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        period = 1.0 / float(self.cfg.get("vision.fps", 6))
        log.info("Камера запущена: Стелла следит за лицами")
        while not self.a.stop_event.is_set():
            t0 = time.time()
            frame = grab()
            if frame is None:
                time.sleep(1)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60))
            now = time.time()
            if len(faces):
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                fh, fw = gray.shape[:2]
                # камера смотрит на человека — зеркалим по горизонтали, чтобы глаза смотрели «на него»
                gx = -((x + w / 2) / fw * 2 - 1)
                gy = (y + h / 2) / fh * 2 - 1
                bus.emit("gaze", x=gx * 0.9, y=gy * 0.6, hold=1.0)
                if not self.present:
                    self.present = True
                    if now - self.last_seen > 120:
                        bus.emit("emotion", name="joy", intensity=0.8, hold=4)
                        self.a.mood.on_activity()
                    bus.emit("face_seen", present=True)
                self.last_seen = now
            elif self.present and now - self.last_seen > 5:
                self.present = False
                bus.emit("face_seen", present=False)
            time.sleep(max(0.0, period - (time.time() - t0)))
