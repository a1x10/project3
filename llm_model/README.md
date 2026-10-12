# Стелла 1.5B

ИИ-ассистент Алексея Моисеева: SFT поверх **Qwen2.5-1.5B-Instruct** (Apache 2.0) → GGUF → Ollama.

| Файл | Что делает |
|---|---|
| `common.py` | системный промпт, ChatML, базовая модель — одно место для обучения и инференса |
| `build_dataset.py` | датасет: личность (300–1000), честность, защита, общие ответы; 15% без system |
| `train_sft.py` | LoRA (или `--full`) SFT, loss только по ответам ассистента + `<|im_end|>` |
| `export.py` | слияние LoRA, чистый ChatML-шаблон, eos = `<|im_end|>`, карточка модели |
| `chat.py` | контрольные вопросы / интерактивный чат |
| `Modelfile`, `to_ollama.sh` | конвертация в GGUF Q8/Q4 и запуск в Ollama |

## Без видеокарты

Обучать — в бесплатном облаке, запускать — у себя на ноутбуке. Ollama на CPU работает нормально.

1. Откройте [colab_stella.ipynb в Colab](https://colab.research.google.com/github/a1x10/project3/blob/claude/tender-cray-foqpnc/llm_model/colab_stella.ipynb),
   выберите *Среда выполнения → Сменить среду → T4 GPU* и нажмите *Выполнить всё* (~15–20 мин).
2. Из Google Диска (папка `stella/`) скачайте `stella-1.5b-Q8_0.gguf` и `Modelfile` в одну папку.
3. Установите [Ollama](https://ollama.com/download), в этой папке выполните:
   ```
   ollama create stella -f Modelfile
   ollama run stella
   ```

Нужно 4+ ГБ свободной RAM, на обычном ноутбуке это ~10–25 токенов/с.
Альтернатива Colab — Kaggle Notebooks (30 ч GPU в неделю бесплатно), тот же ноутбук.

Обучать прямо на CPU тоже можно, но долго (часы): лучше взять модель 0.5B и
оставить на ночь — `python train_sft.py --base Qwen/Qwen2.5-0.5B-Instruct --batch 2 --grad-accum 8`,
затем `python export.py --base Qwen/Qwen2.5-0.5B-Instruct`. Для 1.5B на CPU нужно 16 ГБ RAM.

## Запуск на машине с GPU

```bash
pip install -r requirements.txt
python build_dataset.py --identity 800 --extra my_dialogs.jsonl   # свои диалоги — по желанию
python train_sft.py                       # LoRA: ~8 ГБ VRAM; --full: ~24 ГБ
python export.py                          # → stella-1.5b/
python chat.py --model stella-1.5b        # проверка
python chat.py --model stella-1.5b --no-system
LLAMA_CPP=../llama.cpp ./to_ollama.sh     # → ollama run stella
```

## Важно

* **Добавьте общих диалогов.** Встроенный блок общих ответов маленький (~60). Если оставить
  только его, модель «перекосит» в сторону личности. Подмешайте через `--extra` 1–3 тыс.
  обычных диалогов в стиле Стеллы (коротко, без «Конечно!», в женском роде, на «вы»).
* **Шаблон Qwen подставляет «You are Qwen...», когда system не передан.** Поэтому датасет
  и `chat.py` собирают ChatML вручную, а `export.py` заменяет `chat_template` на чистый.
* **Архитектура и токенизатор уже «быстрые».** Qwen2.5-1.5B — Llama-подобная (RMSNorm,
  RoPE, SwiGLU), с GQA 12:2 (KV-кэш в 6 раз меньше), ChatML-токены уже в словаре,
  llama.cpp конвертирует её штатно. Свой SentencePiece-токенизатор нужен только при
  обучении с нуля; у Qwen BPE на 151 тыс. токенов, русский он режет нормально.
* **Поле `architectures` не переименовывается.** По нему transformers и llama.cpp выбирают
  код модели: с выдуманным именем она просто не загрузится. Имя «Стелла» задаётся там,
  где оно видно: ответы модели, имя в Ollama, карточка модели.
* **Лицензия.** Apache 2.0 разрешает дообучать и распространять, но требует сохранять
  указание на оригинал. Поэтому `export.py` пишет карточку с атрибуцией, а на прямой
  вопрос «ты на базе Qwen?» Стелла отвечает честно (`BASE_DISCLOSURE` в `build_dataset.py`).
