"""Локальное распознавание лиц (OpenCV YuNet + SFace). Ищем только среди своей базы."""
import os
import time
import urllib.request

import numpy as np

from . import config, db

MODELS = os.path.join(config.DATA_DIR, "models")
_URLS = {
    "yunet.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
THRESHOLD = 0.363   # порог косинусного сходства для SFace
_det = _rec = None


def _load():
    global _det, _rec
    if _det:
        return
    import cv2
    os.makedirs(MODELS, exist_ok=True)
    for name, url in _URLS.items():
        p = os.path.join(MODELS, name)
        if not os.path.exists(p):
            urllib.request.urlretrieve(url, p)
    _det = cv2.FaceDetectorYN.create(os.path.join(MODELS, "yunet.onnx"), "", (320, 320), 0.8)
    _rec = cv2.FaceRecognizerSF.create(os.path.join(MODELS, "sface.onnx"), "")


def embed(img_bytes: bytes) -> np.ndarray | None:
    """Эмбеддинг самого крупного лица на кадре или None."""
    import cv2
    _load()
    img = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    _det.setInputSize((w, h))
    _, faces = _det.detect(img)
    if faces is None or len(faces) == 0:
        return None
    face = max(faces, key=lambda f: f[2] * f[3])
    feat = _rec.feature(_rec.alignCrop(img, face))
    return feat.flatten().astype(np.float32)


def add(name: str, note: str, img_bytes: bytes) -> int | None:
    e = embed(img_bytes)
    if e is None:
        return None
    path = os.path.join(config.DATA_DIR, "faces", f"{int(time.time()*1000)}.jpg")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(img_bytes)
    return db.x("INSERT INTO faces(name,note,embedding,photo,ts) VALUES(?,?,?,?,?)",
                (name, note, e.tobytes(), path, time.time()))


def identify(img_bytes: bytes) -> dict:
    e = embed(img_bytes)
    if e is None:
        return {"found": False, "reason": "лицо не найдено на кадре"}
    best, score = None, -1.0
    for r in db.q("SELECT * FROM faces"):
        ref = np.frombuffer(r["embedding"], np.float32)
        s = float(np.dot(e, ref) / (np.linalg.norm(e) * np.linalg.norm(ref) + 1e-9))
        if s > score:
            best, score = r, s
    if best is None or score < THRESHOLD:
        return {"found": False, "reason": "нет в базе"}
    return {"found": True, "name": best["name"], "note": best["note"], "score": round(score, 3)}
