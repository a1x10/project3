# Умная колонка (Orange Pi 4 LTS + ElevenLabs Conversational AI)

## 1. Агент в ElevenLabs (вручную)
Conversational AI → Create Agent → LLM: Gemini 2.0 Flash, голос на выбор (multilingual_v2),
язык: русский. System Prompt:
«Ты — умная домашняя колонка-ассистент. Отвечай кратко, емко, дружелюбно, живым языком
без длинных списков, так как твой текст будет озвучен». Скопируйте Agent ID и API Key.

## 2. Установка на Orange Pi
```bash
sudo apt install -y python3-venv python3-dev portaudio19-dev libasound2-dev
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # впишите ключи
python speaker.py --list-devices   # узнать индексы микрофона и колонки
python speaker.py
```
Используйте наушники/колонку, разнесённую с микрофоном, либо включите эхоподавление
(`pactl load-module module-echo-cancel`), иначе агент может слышать сам себя.

## Автозапуск (systemd)
Создайте `/etc/systemd/system/speaker.service` с `ExecStart=/path/.venv/bin/python /path/speaker.py`,
`Restart=always`, затем `systemctl enable --now speaker`.

## Режим «телефон как микрофон» (phone_speaker.py)
Плата с колонкой стоит где угодно, а телефон служит микрофоном и «ухом» 24/7.
1. На плате: `python phone_speaker.py` (или службой, см. `stella.service`).
2. В выводе будет адрес вида `https://192.168.8.11:8443`. Откройте его в браузере телефона
   (одна Wi-Fi сеть). Браузер предупредит про сертификат — это нормально (самоподписанный),
   нажмите «Дополнительно» → «Всё равно перейти».
3. Нажмите «Включить», разрешите микрофон. Скажите «Стелла».
4. Телефон держите включённым и подключённым к зарядке: кнопка «Затемнить экран» экономит
   дисплей, но не выключает страницу.

Автозапуск на плате:
```bash
mkdir -p ~/.config/systemd/user && cp stella.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now stella
sudo loginctl enable-linger $USER
```

## Микрофон с ноутбука (mic_client.py), без браузера
Колонка и «мозг» на плате (`phone_speaker.py`), а микрофоном служит ноутбук с Windows:
запустите `start_mic.bat` (спросит IP платы один раз). Enter в окне — заглушить/включить микрофон.

## Эхоподавление (echo_cancel.py)
`start.bat` ставит `aec-audio-processing`. Колонка вычитает из микрофона то, что сама играет, поэтому не слышит себя,
а вы можете перебивать её голосом. Нет библиотеки → старый режим (микрофон выключается, пока колонка говорит).
Настройки в `.env`: `AEC=0` (выключить), `ECHO_REF_DELAY_MS` (для медленного Bluetooth), `AEC_GATE`.
