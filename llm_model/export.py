"""Сливает LoRA с базой и сохраняет готовую Стеллу в формате Hugging Face.

- chat_template заменяется на чистый ChatML: без него шаблон Qwen подставит
  «You are Qwen...», если системный промпт не передан;
- eos = <|im_end|>, чтобы генерация останавливалась после ответа;
- архитектура (Qwen2ForCausalLM / model_type) НЕ трогается: по этим полям
  transformers и llama.cpp выбирают код модели, после переименования она не загрузится;
- рядом кладётся карточка модели с атрибуцией базы (требование Apache 2.0).

    python export.py --adapter runs/stella-lora --out stella-1.5b
"""

import argparse
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from common import BASE_MODEL, CHATML_TEMPLATE, IM_END, SYSTEM_PROMPT

MODEL_CARD = f"""---
license: apache-2.0
base_model: {{base}}
language: [ru, en]
---
# Стелла 1.5B

ИИ-ассистент Алексея Моисеева. Дообучена (SFT) на основе
[{{base}}](https://huggingface.co/{{base}}) © Alibaba Cloud, лицензия Apache 2.0.

Формат — ChatML, стоп-токен `{IM_END}`. Системный промпт, на котором шло обучение:

> {SYSTEM_PROMPT}
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default=BASE_MODEL)
    p.add_argument("--adapter", default="runs/stella-lora", help="LoRA-папка или папка полного fine-tune")
    p.add_argument("--out", default="stella-1.5b")
    args = p.parse_args()

    if (Path(args.adapter) / "adapter_config.json").exists():
        from peft import PeftModel
        model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=torch.bfloat16)
        model = PeftModel.from_pretrained(model, args.adapter).merge_and_unload()
    else:
        model = AutoModelForCausalLM.from_pretrained(args.adapter, torch_dtype=torch.bfloat16)
    tok = AutoTokenizer.from_pretrained(args.adapter)

    tok.chat_template = CHATML_TEMPLATE
    im_end = tok.convert_tokens_to_ids(IM_END)
    model.config.eos_token_id = im_end
    model.generation_config.eos_token_id = [im_end, tok.convert_tokens_to_ids("<|endoftext|>")]

    model.save_pretrained(args.out, safe_serialization=True)
    tok.save_pretrained(args.out)
    (Path(args.out) / "README.md").write_text(MODEL_CARD.format(base=args.base), encoding="utf-8")
    print("сохранено:", args.out)


if __name__ == "__main__":
    main()
