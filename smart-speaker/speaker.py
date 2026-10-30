"""Умная колонка на Orange Pi 4 LTS: ElevenLabs Conversational AI по WebSocket."""
import argparse
import json
import os
import queue
import sys
import threading
import time
import urllib.request
import zipfile

try:
    import pyaudio
except ImportError:  # нужен только для режима с микрофоном на плате
    pyaudio = None
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import AudioInterface, Conversation
from vosk import KaldiRecognizer, Model, SetLogLevel

SAMPLE_RATE = 16000  # ElevenLabs ожидает PCM 16 кГц, 16 бит, моно
CHUNK = 1600         # 100 мс; меньше блок -> меньше задержка

MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


class AlsaAudioInterface(AudioInterface):
    """PyAudio-интерфейс с выбором микрофона и колонки."""

    def __init__(self, input_index=None, output_index=None):
        self.pa = pyaudio.PyAudio()
        self.input_index = input_index
        self.output_index = output_index
        self.out_queue: "queue.Queue[bytes]" = queue.Queue()
        self.should_stop = threading.Event()
        self.threads = []
        self.last_audio = time.time()
        self.last_write = 0.0
        # Пока колонка говорит, микрофон агенту не передаётся (иначе он слышит сам себя).
        # ALLOW_INTERRUPT=1 разрешает перебивать голосом (нужны наушники).
        self.allow_interrupt = os.getenv("ALLOW_INTERRUPT", "0") == "1"

    def is_playing(self):
        return (not self.out_queue.empty()) or time.time() - max(self.last_audio, self.last_write) < 0.8

    def start(self, input_callback):
        self.input_callback = input_callback
        self.in_stream = self.pa.open(
            format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, input=True,
            input_device_index=self.input_index, frames_per_buffer=CHUNK,
        )
        self.out_stream = self.pa.open(
            format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, output=True,
            output_device_index=self.output_index, frames_per_buffer=CHUNK,
        )
        self.should_stop.clear()
        self.threads = [
            threading.Thread(target=self._record, daemon=True),
            threading.Thread(target=self._play, daemon=True),
        ]
        for t in self.threads:
            t.start()

    def stop(self):
        self.should_stop.set()
        for t in self.threads:
            t.join(timeout=2)
        for s in (self.in_stream, self.out_stream):
            s.stop_stream()
            s.close()
        self.pa.terminate()

    def output(self, audio: bytes):
        self.last_audio = time.time()
        self.out_queue.put(audio)

    def interrupt(self):
        """Пользователь перебил агента — сбрасываем недопроигранное."""
        try:
            while True:
                self.out_queue.get_nowait()
        except queue.Empty:
            pass

    def _record(self):
        while not self.should_stop.is_set():
            data = self.in_stream.read(CHUNK, exception_on_overflow=False)
            if not self.allow_interrupt and self.is_playing():
                data = b"\0" * len(data)
            self.input_callback(data)

    def _play(self):
        while not self.should_stop.is_set():
            try:
                chunk = self.out_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self.out_stream.write(chunk)
            self.last_write = time.time()


def list_devices():
    pa = pyaudio.PyAudio()
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        print(f"{i}: {d['name']}  in={d['maxInputChannels']} out={d['maxOutputChannels']}")
    pa.terminate()


def env_int(name):
    v = os.getenv(name)
    return int(v) if v else None


def ensure_model():
    """Скачивает небольшую русскую модель Vosk (~45 МБ) при первом запуске."""
    path = os.path.join(MODELS_DIR, MODEL_NAME)
    if os.path.isdir(path):
        return path
    os.makedirs(MODELS_DIR, exist_ok=True)
    zip_path = path + ".zip"
    print(f"Скачиваю модель для слова пробуждения (~45 МБ): {MODEL_URL}")
    urllib.request.urlretrieve(MODEL_URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(MODELS_DIR)
    os.remove(zip_path)
    return path


def wait_for_wake_word(model, wake_word, input_index):
    """Блокируется, пока в микрофоне не прозвучит слово пробуждения."""
    rec = KaldiRecognizer(model, SAMPLE_RATE, json.dumps([wake_word, "[unk]"], ensure_ascii=False))
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, input=True,
        input_device_index=input_index, frames_per_buffer=CHUNK,
    )
    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            if rec.AcceptWaveform(data):
                text = json.loads(rec.Result()).get("text", "")
            else:
                text = json.loads(rec.PartialResult()).get("partial", "")
            if wake_word in text.split():
                return
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def run_session(client, agent_id, input_index, output_index, idle_timeout):
    """Один разговор. Завершается после idle_timeout секунд тишины."""
    audio = AlsaAudioInterface(input_index, output_index)
    st = {"last_user": time.time(), "agent_turns": 0}

    def on_user(text):
        # Пустые реплики вроде «...» (тишина/шум) не считаем и не показываем.
        if any(c.isalnum() for c in text):
            st["last_user"] = time.time()
            st["agent_turns"] = 0
            print(f"Вы: {text}")

    def on_agent(text):
        st["agent_turns"] += 1
        print(f"Колонка: {text}")

    conversation = Conversation(
        client,
        agent_id,
        requires_auth=True,
        audio_interface=audio,
        callback_agent_response=on_agent,
        callback_user_transcript=on_user,
    )
    done = threading.Event()

    def watchdog():
        while not done.wait(0.5):
            if audio.is_playing():
                continue
            silent_for = time.time() - max(st["last_user"], audio.last_audio, audio.last_write)
            # Тихо дольше idle_timeout, либо колонка уже дважды сказала что-то без вашего ответа
            # (например «Вы здесь?») — значит разговор окончен.
            if silent_for > idle_timeout or st["agent_turns"] >= 2:
                conversation.end_session()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    conversation.start_session()
    try:
        conversation.wait_for_session_end()
    finally:
        done.set()
    return conversation


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(override=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--no-wake", action="store_true", help="без слова пробуждения: один разговор сразу")
    args = ap.parse_args()
    if args.list_devices:
        return list_devices()

    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    agent_id = os.environ["ELEVENLABS_AGENT_ID"]
    input_index, output_index = env_int("INPUT_DEVICE_INDEX"), env_int("OUTPUT_DEVICE_INDEX")
    idle_timeout = float(os.getenv("IDLE_TIMEOUT", "8"))
    wake_word = os.getenv("WAKE_WORD", "стелла").lower()

    if args.no_wake:
        run_session(client, agent_id, input_index, output_index, idle_timeout)
        return

    SetLogLevel(-1)
    model = Model(ensure_model())
    while True:
        print(f"Жду слово пробуждения «{wake_word}»... (Ctrl+C для выхода)")
        try:
            wait_for_wake_word(model, wake_word, input_index)
            print("Слышу! Начинаю разговор.")
            run_session(client, agent_id, input_index, output_index, idle_timeout)
        except KeyboardInterrupt:
            print("Выход.")
            return
        except Exception as e:  # сеть/аудио: не падаем, а возвращаемся к ожиданию
            print(f"Ошибка: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
