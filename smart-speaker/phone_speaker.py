"""Колонка, у которой микрофоном служит телефон, а голос играет на колонке платы.

Телефон открывает страницу https://<плата>:8443 и по WebSocket шлёт звук микрофона
(PCM 16 кГц, 16 бит, моно). Плата круглосуточно ждёт слово «Стелла» (Vosk), после него
ведёт разговор с агентом ElevenLabs и проигрывает ответ на своей колонке.
"""
import asyncio
import json
import os
import queue
import socket
import ssl
import subprocess
import sys
import threading
import time

from aiohttp import WSMsgType, web
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import AudioInterface, Conversation
from vosk import KaldiRecognizer, Model, SetLogLevel

import speaker

HERE = os.path.dirname(os.path.abspath(__file__))
CERT_DIR = os.path.join(HERE, "certs")


def local_ips():
    ips = set()
    try:
        ips.update(subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split())
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return sorted(i for i in ips if i.count(".") == 3)


def ensure_cert():
    """Самоподписанный сертификат: без HTTPS браузер не даст странице доступ к микрофону."""
    cert, key = os.path.join(CERT_DIR, "cert.pem"), os.path.join(CERT_DIR, "key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    os.makedirs(CERT_DIR, exist_ok=True)
    host = socket.gethostname()
    san = ["DNS:localhost", f"DNS:{host}", f"DNS:{host}.local", "IP:127.0.0.1"] + [f"IP:{i}" for i in local_ips()]
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
         "-subj", "/CN=stella", "-addext", "subjectAltName=" + ",".join(san),
         "-keyout", key, "-out", cert],
        check=True, capture_output=True,
    )
    return cert, key


class PiOutput(AudioInterface):
    """Выход на колонку платы. Вход (микрофон) приходит с телефона через Hub."""

    def __init__(self, hub, output_index):
        self.hub = hub
        self.output_index = output_index
        self.q: "queue.Queue[bytes]" = queue.Queue()
        self.stop_ev = threading.Event()
        self.thread = None
        self.pa = self.stream = None
        self.last_audio = 0.0
        self.last_write = 0.0

    def is_playing(self):
        # 0.8 с запаса: хвост звука в буфере и эхо комнаты
        return (not self.q.empty()) or time.time() - max(self.last_audio, self.last_write) < 0.8

    def start(self, input_callback):
        if not os.getenv("DUMMY_OUTPUT"):  # DUMMY_OUTPUT нужен только для тестов без звуковой карты
            self.pa = speaker.pyaudio.PyAudio()
            self.stream = self.pa.open(
                format=speaker.pyaudio.paInt16, channels=1, rate=speaker.SAMPLE_RATE, output=True,
                output_device_index=self.output_index, frames_per_buffer=speaker.CHUNK,
            )
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._play, daemon=True)
        self.thread.start()
        self.hub.iface = self
        self.hub.session_cb = input_callback
        self.hub.set_state("listening")

    def stop(self):
        self.hub.session_cb = None
        self.stop_ev.set()
        if self.thread:
            self.thread.join(timeout=2)
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.pa.terminate()

    def output(self, audio: bytes):
        self.last_audio = time.time()
        self.q.put(audio)

    def interrupt(self):
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def _play(self):
        while not self.stop_ev.is_set():
            try:
                chunk = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.stream:
                self.stream.write(chunk)
            self.last_write = time.time()


class Hub:
    """Связывает телефоны (WebSocket), распознавание слова и разговор с агентом."""

    def __init__(self, loop, client, agent_id, output_index, wake_word, idle_timeout):
        self.iface = None
        self.conversation = None
        self.muted = False
        # По умолчанию пока колонка говорит, микрофон агенту не передаётся (иначе он слышит сам себя).
        # ALLOW_INTERRUPT=1 разрешает перебивать колонку голосом, но нужен наушник/разнесённые устройства.
        self.allow_interrupt = os.getenv("ALLOW_INTERRUPT", "0") == "1"
        self.loop, self.client, self.agent_id = loop, client, agent_id
        self.output_index, self.wake_word, self.idle_timeout = output_index, wake_word, idle_timeout
        self.clients = set()
        self.state = "loading"
        self.session_cb = None
        self.busy = False
        self.q: "queue.Queue[bytes]" = queue.Queue(maxsize=100)

    # --- общение со страницами ---
    def broadcast(self, msg):
        text = json.dumps(msg, ensure_ascii=False)
        asyncio.run_coroutine_threadsafe(self._send_all(text), self.loop)

    async def _send_all(self, text):
        for ws in list(self.clients):
            try:
                await ws.send_str(text)
            except Exception:
                self.clients.discard(ws)

    def set_state(self, state):
        self.state = state
        self.broadcast({"type": "state", "state": state, "wake_word": self.wake_word})

    def set_muted(self, value: bool):
        """Кнопка «Заглушить» на странице: микрофон не слушаем, текущий разговор завершаем."""
        self.muted = value
        if value:
            try:
                while True:
                    self.q.get_nowait()
            except queue.Empty:
                pass
            conv = self.conversation
            if conv:
                threading.Thread(target=conv.end_session, daemon=True).start()
        self.broadcast({"type": "muted", "value": value})

    def feed(self, pcm: bytes):
        if self.muted:
            return
        try:
            self.q.put_nowait(pcm)
        except queue.Full:
            pass

    # --- слушаем круглосуточно ---
    def new_rec(self, model):
        return KaldiRecognizer(model, speaker.SAMPLE_RATE, json.dumps([self.wake_word, "[unk]"], ensure_ascii=False))

    def worker(self):
        SetLogLevel(-1)
        model = Model(speaker.ensure_model())
        rec = self.new_rec(model)
        self.set_state("idle")
        print("Готово. Жду слово пробуждения «%s»." % self.wake_word, flush=True)
        while True:
            pcm = self.q.get()
            cb = self.session_cb
            if cb:
                iface = self.iface
                if iface and not self.allow_interrupt and iface.is_playing():
                    pcm = b"\0" * len(pcm)
                cb(pcm)
                continue
            if self.busy:
                continue
            if getattr(self, "reset_rec", False):
                rec, self.reset_rec = self.new_rec(model), False
            if rec.AcceptWaveform(pcm):
                text = json.loads(rec.Result()).get("text", "")
            else:
                text = json.loads(rec.PartialResult()).get("partial", "")
            if self.wake_word in text.split():
                self.busy = True
                self.set_state("connecting")
                threading.Thread(target=self.run_session, daemon=True).start()

    # --- один разговор ---
    def run_session(self):
        iface = PiOutput(self, self.output_index)
        last_activity = [time.time()]
        started = time.time()

        def touch(role, text):
            last_activity[0] = time.time()
            print(("Вы: " if role == "user" else "Колонка: ") + text, flush=True)
            self.broadcast({"type": "msg", "role": role, "text": text})

        conversation = Conversation(
            self.client, self.agent_id, requires_auth=True, audio_interface=iface,
            callback_agent_response=lambda t: touch("agent", t),
            callback_user_transcript=lambda t: touch("user", t),
        )
        self.conversation = conversation
        done = threading.Event()

        def watchdog():
            speaking = None
            while not done.wait(0.25):
                playing = iface.is_playing()
                if self.session_cb and playing != speaking:
                    speaking = playing
                    self.set_state("speaking" if playing else "listening")
                idle = time.time() - max(last_activity[0], iface.last_audio)
                if not playing and idle > self.idle_timeout:
                    conversation.end_session()
                    return

        threading.Thread(target=watchdog, daemon=True).start()
        try:
            conversation.start_session()
            conversation.wait_for_session_end()
        except Exception as e:
            print("Ошибка разговора:", e, flush=True)
        finally:
            done.set()
            self.conversation = None
            self.session_cb = None
            if iface.last_audio == 0.0 and time.time() - started < 5:
                self.broadcast({"type": "notice", "text": "Не удалось начать разговор. Проверьте звук и ключи."})
            self.reset_rec = True
            self.busy = False
            self.set_state("idle")


async def ws_handler(request):
    hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1 << 20)
    await ws.prepare(request)
    hub.clients.add(ws)
    await ws.send_str(json.dumps({"type": "state", "state": hub.state, "wake_word": hub.wake_word}, ensure_ascii=False))
    await ws.send_str(json.dumps({"type": "muted", "value": hub.muted}))
    try:
        async for m in ws:
            if m.type == WSMsgType.BINARY:
                hub.feed(m.data)
            elif m.type == WSMsgType.TEXT:
                try:
                    msg = json.loads(m.data)
                except ValueError:
                    continue
                if msg.get("type") == "mute":
                    hub.set_muted(bool(msg.get("value")))
    finally:
        hub.clients.discard(ws)
    return ws


async def index(request):
    return web.FileResponse(os.path.join(HERE, "web", "index.html"), headers={"Cache-Control": "no-store"})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(override=True)
    port = int(os.getenv("PORT", "8443"))
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    agent_id = os.environ["ELEVENLABS_AGENT_ID"]
    output_index = speaker.env_int("OUTPUT_DEVICE_INDEX")
    wake_word = os.getenv("WAKE_WORD", "стелла").lower()
    idle_timeout = float(os.getenv("IDLE_TIMEOUT", "20"))

    async def on_startup(app):
        hub = Hub(asyncio.get_running_loop(), client, agent_id, output_index, wake_word, idle_timeout)
        app["hub"] = hub
        threading.Thread(target=hub.worker, daemon=True).start()

    app = web.Application()
    app.on_startup.append(on_startup)
    app.add_routes([web.get("/", index), web.get("/ws", ws_handler)])

    cert, key = ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    print("Откройте на телефоне (в той же Wi-Fi сети):")
    for ip in local_ips():
        print(f"  https://{ip}:{port}")
    print(f"  https://{socket.gethostname()}.local:{port}", flush=True)
    web.run_app(app, host="0.0.0.0", port=port, ssl_context=ctx, print=None)


if __name__ == "__main__":
    main()
