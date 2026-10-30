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

import skills

try:
    import echo_cancel
except ImportError:  # файл echo_cancel.py не скопирован - работаем без эхоподавления
    echo_cancel = None

SAMPLE_RATE = 16000  # ElevenLabs ожидает PCM 16 кГц, 16 бит, моно
CHUNK = 1600         # 100 мс; меньше блок -> меньше задержка

MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


STATE = {"quiet": False, "await_music": False}  # режим кино: Стелла молчит и не реагирует на фильм


def pick_output_by_name(pa):
    """OUTPUT_DEVICE_NAME=V-113 (часть названия колонки): Стелла говорит на ней, а не на устройстве Windows по умолчанию.
    Профили «гарнитура/Hands-Free» пропускаем: у них звук как в телефоне."""
    want = os.getenv("OUTPUT_DEVICE_NAME", "").strip().lower()
    if not want:
        return None
    for i in range(pa.get_device_count()):
        d = pa.get_device_info_by_index(i)
        name = d["name"].lower()
        if d["maxOutputChannels"] > 0 and want in name and not skills.is_headset_profile(name):
            print(f"Стелла говорит на: {d['name']}", flush=True)
            return i
    print(f"Колонка «{want}» не найдена, звук идёт на устройство по умолчанию.", flush=True)
    return None


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
        # Секунд после конца речи колонки, пока микрофон выключен (задержка Bluetooth, эхо комнаты)
        self.echo_tail = float(os.getenv("ECHO_TAIL", "1.6"))
        # Пока колонка говорит, микрофон агенту не передаётся (иначе он слышит сам себя).
        # ALLOW_INTERRUPT=1 разрешает перебивать голосом (нужны наушники).
        self.allow_interrupt = os.getenv("ALLOW_INTERRUPT", "0") == "1"
        # Эхоподавление (если стоит aec-audio-processing): микрофон не выключается, колонка себя не слышит
        self.aec = None
        if echo_cancel and echo_cancel.available():
            self.aec = echo_cancel.EchoCanceller(
                SAMPLE_RATE, int(os.getenv("ECHO_REF_DELAY_MS", "0")), int(os.getenv("AEC_GATE", "200")))
        print("Эхоподавление:", "включено" if self.aec else "выключено (микрофон отключается, пока колонка говорит)", flush=True)

    def is_playing(self):
        return (not self.out_queue.empty()) or time.time() - max(self.last_audio, self.last_write) < self.echo_tail

    def start(self, input_callback):
        self.input_callback = input_callback
        self.in_stream = self.pa.open(
            format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, input=True,
            input_device_index=self.input_index, frames_per_buffer=CHUNK,
        )
        out_index = self.output_index if self.output_index is not None else pick_output_by_name(self.pa)
        self.out_stream = self.pa.open(
            format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, output=True,
            output_device_index=out_index, frames_per_buffer=CHUNK,
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
            if self.aec:
                data = self.aec.process(data, self.is_playing())
            elif not self.allow_interrupt and self.is_playing():
                data = b"\0" * len(data)
            if data:
                self.input_callback(data)

    def _play(self):
        while not self.should_stop.is_set():
            try:
                chunk = self.out_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.aec:
                self.aec.feed_reference(chunk)
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


class WakeListener:
    """Слушает поток микрофона: ждёт «Стелла» и фразу после неё («дальше», «лайк», «какая погода»...).
    feed() возвращает распознанный текст, когда фраза закончилась (или слишком затянулась)."""

    def __init__(self, model, wake_word, vocabulary=None):
        vocabulary = vocabulary or skills.GRAMMAR
        words = [w for w in dict.fromkeys(vocabulary + [wake_word]) if model.vosk_model_find_word(w) != -1]
        self.wake = wake_word
        self.rec = KaldiRecognizer(model, SAMPLE_RATE, json.dumps(words + ["[unk]"], ensure_ascii=False))
        self.since = None  # сколько отсчётов прошло с момента, когда услышали слово

    def feed(self, data: bytes):
        if self.rec.AcceptWaveform(data):
            text = json.loads(self.rec.Result()).get("text", "")
            self.since = None
            return text if self.wake in text.split() else None
        partial = json.loads(self.rec.PartialResult()).get("partial", "")
        if self.since is None and self.wake in partial.split():
            self.since = 0
        if self.since is not None:
            self.since += len(data) // 2
            if self.since > 1.8 * SAMPLE_RATE:  # фраза затянулась: действуем по тому, что уже есть
                self.rec.Reset()
                self.since = None
                return partial
        return None


def wait_for_wake_word(model, wake_word, input_index, quiet=False):
    """Блокируется, пока не прозвучит «Стелла ...»; возвращает всю распознанную фразу.
    В режиме кино (quiet) слушает только «Стелла, проснись»."""
    listener = WakeListener(model, wake_word, skills.QUIET_GRAMMAR if quiet else None)
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, input=True,
        input_device_index=input_index, frames_per_buffer=CHUNK,
    )
    try:
        while True:
            text = listener.feed(stream.read(CHUNK, exception_on_overflow=False))
            if text is not None:
                return text
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


def whats_playing_prompt():
    """Сообщение агенту: что сейчас играет (он озвучит своим голосом)."""
    track = skills.now_playing_text()
    if track:
        return (f"Пользователь спросил, что сейчас играет. Данные: {track}. "
                "Скажи коротко: исполнитель и название трека. Не здоровайся заново.")
    return "Пользователь спросил, что сейчас играет, но ничего не играет. Скажи это коротко."


ASK_MUSIC_PROMPT = ("Пользователь хочет включить музыку, но название не расслышано. "
                    "Спроси коротко: какой трек, исполнителя или плейлист включить? Не здоровайся заново.")


def beep(ok=True):
    """Короткий сигнал: команда принята (Windows)."""
    try:
        import winsound
        winsound.Beep(1000 if ok else 400, 90)
    except Exception:
        pass


def do_music(cmd, arg=""):
    """Выполняет музыкальную команду, возвращает текст для консоли."""
    if cmd == "volume_up":
        return skills.change_volume(delta=+1)
    if cmd == "volume_down":
        return skills.change_volume(delta=-1)
    if cmd == "volume_set":
        return skills.change_volume(set_to=float(arg))
    if cmd == "next":
        return "Следующий трек" if skills.media_key("next") else "Не удалось переключить"
    if cmd == "prev":
        return "Предыдущий трек" if skills.media_key("prev") else "Не удалось переключить"
    if cmd in ("pause", "resume"):
        return "Пауза/играть" if skills.media_key("playpause") else "Не удалось"
    if cmd == "playlist":
        return skills.play_playlist()
    if cmd == "search":
        return skills.play_search(arg)
    if cmd == "like":
        return skills.like_current()
    return ""


def run_session(client, agent_id, input_index, output_index, idle_timeout, first_message=None):
    """Один разговор. Завершается после idle_timeout секунд тишины."""
    audio = AlsaAudioInterface(input_index, output_index)
    st = {"last_user": time.time(), "agent_turns": 0,
          "max_turns": 3 if STATE["await_music"] else 2}   # после вопроса «что включить?» ждём ответ дольше

    def run_command(cmd, arg):
        """Музыка/погода по голосу прямо во время разговора (агент сам этого не умеет)."""
        try:
            if cmd == "weather":
                report = skills.weather_report(arg)
                conversation.send_user_message(
                    f"Пользователь спросил про погоду. Данные: {report} "
                    "Расскажи коротко и по-человечески, числа произноси словами, без списков.")
                return
            if cmd == "whatsplaying":
                conversation.send_user_message(whats_playing_prompt())
                return
            if cmd == "search_ask":            # «включи что-нибудь»: спрашиваем название, разговор продолжается
                STATE["await_music"] = True
                st["agent_turns"] = 0           # новый вопрос: счётчик «колонка говорила без ответа» начинаем заново
                conversation.send_user_message(ASK_MUSIC_PROMPT)
                return
            if cmd == "search":
                audio.interrupt()
                conversation.end_session()
                beep()
                print("Команда:", do_music("search", arg))
                return
            if cmd.startswith("volume"):   # громкость: разговор не прерываем
                beep()
                print("Команда:", do_music(cmd, arg))
                return
            audio.interrupt()          # агент ещё не договорил «у меня нет доступа» - обрываем
            conversation.end_session()
            if cmd == "quiet":
                STATE["quiet"] = True
                beep(False); beep(False)
                print("Режим кино: молчу. Скажите «Стелла, проснись».")
                return
            beep()
            print("Команда:", do_music(cmd, arg))
        except Exception as e:
            print(f"Команда не выполнена: {e}")

    def on_user(text):
        # Пустые реплики вроде «...» (тишина/шум) не считаем и не показываем.
        if any(c.isalnum() for c in text):
            st["last_user"] = time.time()
            st["agent_turns"] = 0
            print(f"Вы: {text}")
            if STATE["await_music"]:           # на вопрос «что включить?» отвечаем названием
                STATE["await_music"] = False
                cmd, arg = "search", text.strip(" .!?")
            else:
                cmd, arg = skills.in_session_command(text, os.getenv("WAKE_WORD", "стелла").lower())
            if cmd:
                threading.Thread(target=run_command, args=(cmd, arg), daemon=True).start()

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
            if silent_for > idle_timeout or st["agent_turns"] >= st["max_turns"]:
                conversation.end_session()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    conversation.start_session()
    if first_message:  # например, данные о погоде: агент озвучит их своим голосом
        def send_first():
            for _ in range(80):  # ждём соединения до 8 секунд
                if getattr(conversation, "_ws", None):
                    try:
                        conversation.send_user_message(first_message)
                    except Exception as e:
                        print(f"Не удалось передать сообщение агенту: {e}")
                    return
                time.sleep(0.1)
        threading.Thread(target=send_first, daemon=True).start()
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
        skills.keep_awake()
        run_session(client, agent_id, input_index, output_index, idle_timeout)
        return

    if skills.keep_awake():
        print("Компьютер не уйдёт в сон, пока работает Стелла (экран может гаснуть).")
    SetLogLevel(-1)
    model = Model(ensure_model())
    skills.keep_spotify_hidden(5)  # если Spotify уже открыт, спрячем его окно
    while True:
        print("Режим кино: жду «Стелла, проснись»..." if STATE["quiet"] else
              f"Жду слово пробуждения «{wake_word}»... (Ctrl+C для выхода)")
        try:
            heard = wait_for_wake_word(model, wake_word, input_index, STATE["quiet"])
            cmd, arg = skills.parse_command(heard, wake_word)
            if STATE["quiet"]:                       # режим кино: реагируем только на «проснись»
                if cmd == "wakeup":
                    STATE["quiet"] = False
                    beep()
                    print("Я снова слушаю.")
                continue
            if cmd == "quiet":
                STATE["quiet"] = True
                beep(False); beep(False)
                print("Режим кино: молчу и ничего не слушаю, кроме «Стелла, проснись».")
                continue
            if cmd == "wakeup":                      # «проснись», когда она и так не спит: просто разговор
                cmd = None
            if cmd in ("next", "prev", "like", "pause", "resume", "playlist", "volume_up", "volume_down", "volume_set"):
                beep()
                try:
                    print("Команда:", do_music(cmd, arg))
                except Exception as e:
                    beep(False)
                    print(f"Команда не выполнена: {e}")
                continue
            first = None
            if cmd == "whatsplaying":
                first = whats_playing_prompt()
            elif cmd == "search_ask":
                STATE["await_music"] = True
                first = ASK_MUSIC_PROMPT
            elif cmd == "weather":
                try:
                    report = skills.weather_report(arg)
                    first = (f"Пользователь спросил про погоду. Данные: {report} "
                             "Расскажи коротко и по-человечески, числа произноси словами, без списков, не здоровайся заново.")
                except Exception as e:
                    print(f"Погода недоступна: {e}")
                    first = "Пользователь спросил про погоду, но сервис погоды сейчас недоступен. Скажи об этом коротко."
            print("Слышу! Начинаю разговор.")
            try:
                run_session(client, agent_id, input_index, output_index, idle_timeout, first)
            finally:
                STATE["await_music"] = False
        except KeyboardInterrupt:
            print("Выход.")
            return
        except Exception as e:  # сеть/аудио: не падаем, а возвращаемся к ожиданию
            print(f"Ошибка: {e}")
            time.sleep(2)


if __name__ == "__main__":
    main()
