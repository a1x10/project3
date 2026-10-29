"""Умная колонка на Orange Pi 4 LTS: ElevenLabs Conversational AI по WebSocket."""
import argparse
import os
import queue
import signal
import threading

import pyaudio
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import AudioInterface, Conversation

SAMPLE_RATE = 16000  # ElevenLabs ожидает PCM 16 кГц, 16 бит, моно
CHUNK = 1600         # 100 мс; меньше блок -> меньше задержка


class AlsaAudioInterface(AudioInterface):
    """PyAudio-интерфейс с выбором микрофона и колонки."""

    def __init__(self, input_index=None, output_index=None):
        self.pa = pyaudio.PyAudio()
        self.input_index = input_index
        self.output_index = output_index
        self.out_queue: "queue.Queue[bytes]" = queue.Queue()
        self.should_stop = threading.Event()
        self.threads = []

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
            self.input_callback(data)

    def _play(self):
        while not self.should_stop.is_set():
            try:
                chunk = self.out_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self.out_stream.write(chunk)


def list_devices():
    pa = pyaudio.PyAudio()
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        print(f"{i}: {d['name']}  in={d['maxInputChannels']} out={d['maxOutputChannels']}")
    pa.terminate()


def env_int(name):
    v = os.getenv(name)
    return int(v) if v else None


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()
    if args.list_devices:
        return list_devices()

    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    conversation = Conversation(
        client,
        os.environ["ELEVENLABS_AGENT_ID"],
        requires_auth=True,
        audio_interface=AlsaAudioInterface(
            env_int("INPUT_DEVICE_INDEX"), env_int("OUTPUT_DEVICE_INDEX")
        ),
        callback_agent_response=lambda t: print(f"Колонка: {t}"),
        callback_user_transcript=lambda t: print(f"Вы: {t}"),
    )
    signal.signal(signal.SIGINT, lambda *_: conversation.end_session())
    signal.signal(signal.SIGTERM, lambda *_: conversation.end_session())
    conversation.start_session()
    print("Слушаю... (Ctrl+C для выхода)")
    print("Conversation ID:", conversation.wait_for_session_end())


if __name__ == "__main__":
    main()
