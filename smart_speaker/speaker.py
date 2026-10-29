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

SAMPLE_RATE = 16000       # формат, которого ждёт ElevenLabs (PCM 16 бит, моно)
INPUT_CHUNK = 1600        # 100 мс — меньше буфер, меньше задержка
OUTPUT_CHUNK = 1600


class AlsaAudioInterface(AudioInterface):
    """Микрофон/динамик через PyAudio с выбором устройств и мгновенным прерыванием."""

    def __init__(self, input_device=None, output_device=None):
        self.pa = pyaudio.PyAudio()
        self.input_device = input_device
        self.output_device = output_device
        self.out_queue: "queue.Queue[bytes]" = queue.Queue()
        self.should_stop = threading.Event()
        self.in_stream = None
        self.out_stream = None
        self.threads = []

    def start(self, input_callback):
        self.input_callback = input_callback
        self.should_stop.clear()
        self.in_stream = self.pa.open(
            format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, input=True,
            input_device_index=self.input_device, frames_per_buffer=INPUT_CHUNK,
            start=True,
        )
        self.out_stream = self.pa.open(
            format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, output=True,
            output_device_index=self.output_device, frames_per_buffer=OUTPUT_CHUNK,
        )
        self.threads = [
            threading.Thread(target=self._record_loop, daemon=True),
            threading.Thread(target=self._play_loop, daemon=True),
        ]
        for t in self.threads:
            t.start()

    def stop(self):
        self.should_stop.set()
        for t in self.threads:
            t.join(timeout=1)
        for stream in (self.in_stream, self.out_stream):
            if stream:
                stream.stop_stream()
                stream.close()
        self.pa.terminate()

    def output(self, audio: bytes):
        self.out_queue.put(audio)

    def interrupt(self):
        """Пользователь перебил агента — сбрасываем недопроигранный звук."""
        while not self.out_queue.empty():
            try:
                self.out_queue.get_nowait()
            except queue.Empty:
                break

    def _record_loop(self):
        while not self.should_stop.is_set():
            data = self.in_stream.read(INPUT_CHUNK, exception_on_overflow=False)
            self.input_callback(data)

    def _play_loop(self):
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
        print(f"[{i}] {d['name']}  in={d['maxInputChannels']} out={d['maxOutputChannels']}")
    pa.terminate()


def env_int(name):
    value = os.getenv(name)
    return int(value) if value else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list-devices", action="store_true")
    args = parser.parse_args()
    if args.list_devices:
        list_devices()
        return

    load_dotenv()
    api_key = os.environ["ELEVENLABS_API_KEY"]
    agent_id = os.environ["ELEVENLABS_AGENT_ID"]

    conversation = Conversation(
        ElevenLabs(api_key=api_key),
        agent_id,
        requires_auth=True,
        audio_interface=AlsaAudioInterface(
            env_int("INPUT_DEVICE_INDEX"), env_int("OUTPUT_DEVICE_INDEX")
        ),
        callback_agent_response=lambda r: print(f"Колонка: {r}"),
        callback_user_transcript=lambda t: print(f"Вы: {t}"),
    )

    signal.signal(signal.SIGINT, lambda *_: conversation.end_session())
    signal.signal(signal.SIGTERM, lambda *_: conversation.end_session())

    conversation.start_session()
    print("Слушаю... (Ctrl+C для выхода)")
    print("ID сессии:", conversation.wait_for_session_end())


if __name__ == "__main__":
    main()
