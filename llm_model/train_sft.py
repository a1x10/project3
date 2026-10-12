"""SFT Стеллы поверх Qwen2.5-1.5B-Instruct (LoRA по умолчанию, --full для полного).

Loss считается только по ответам ассистента, включая <|im_end|> в конце каждого
ответа — иначе модель не научится вовремя останавливаться.

    pip install torch transformers peft accelerate safetensors
    python train_sft.py --data data --out runs/stella-lora
"""

import argparse
import json

import torch
from torch.utils.data import Dataset
from transformers import (AutoModelForCausalLM, AutoTokenizer, Trainer,
                          TrainingArguments)

from common import BASE_MODEL, IM_END, IM_START

IGNORE = -100


def encode(messages, tok, max_len):
    """ChatML → (input_ids, labels). Метки ставятся только на текст ответа и <|im_end|>."""
    ids, labels = [], []

    def add(text, train):
        t = tok(text, add_special_tokens=False).input_ids
        ids.extend(t)
        labels.extend(t if train else [IGNORE] * len(t))

    for m in messages:
        is_asst = m["role"] == "assistant"
        add(f"{IM_START}{m['role']}\n", False)   # заголовок — не учим
        add(m["content"], is_asst)                # ответ — учим
        add(IM_END, is_asst)                      # стоп-токен — учим обязательно
        add("\n", False)
    return ids[:max_len], labels[:max_len]


class ChatDataset(Dataset):
    def __init__(self, path, tok, max_len):
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        self.items = [encode(r["messages"], tok, max_len) for r in rows]
        self.items = [x for x in self.items if any(l != IGNORE for l in x[1])]

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]


def make_collator(pad_id):
    def collate(batch):
        n = max(len(ids) for ids, _ in batch)
        ids = torch.full((len(batch), n), pad_id)
        lab = torch.full((len(batch), n), IGNORE)
        att = torch.zeros((len(batch), n), dtype=torch.long)
        for i, (x, y) in enumerate(batch):
            ids[i, :len(x)] = torch.tensor(x)
            lab[i, :len(y)] = torch.tensor(y)
            att[i, :len(x)] = 1
        return {"input_ids": ids, "labels": lab, "attention_mask": att}
    return collate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default=BASE_MODEL)
    p.add_argument("--data", default="data")
    p.add_argument("--out", default="runs/stella-lora")
    p.add_argument("--full", action="store_true", help="полный fine-tune вместо LoRA (нужно ~24 ГБ VRAM)")
    p.add_argument("--epochs", type=float, default=3)
    p.add_argument("--lr", type=float, default=None)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--grad-accum", type=int, default=2)
    p.add_argument("--max-len", type=int, default=1024)
    p.add_argument("--lora-r", type=int, default=16)
    args = p.parse_args()

    tok = AutoTokenizer.from_pretrained(args.base)
    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    model = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16 if bf16 else torch.float32)

    if not args.full:
        from peft import LoraConfig, get_peft_model
        model = get_peft_model(model, LoraConfig(
            r=args.lora_r, lora_alpha=args.lora_r * 2, lora_dropout=0.05, task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
        model.print_trainable_parameters()

    train = ChatDataset(f"{args.data}/train.jsonl", tok, args.max_len)
    val = ChatDataset(f"{args.data}/val.jsonl", tok, args.max_len)
    print(f"train {len(train)}, val {len(val)}")

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=args.out,
            num_train_epochs=args.epochs,
            learning_rate=args.lr or (1e-5 if args.full else 2e-4),
            per_device_train_batch_size=args.batch,
            per_device_eval_batch_size=args.batch,
            gradient_accumulation_steps=args.grad_accum,
            lr_scheduler_type="cosine",
            warmup_steps=10,
            logging_steps=10,
            eval_strategy="epoch",
            save_strategy="epoch",
            save_total_limit=2,
            bf16=bf16,
            gradient_checkpointing=args.full,
            remove_unused_columns=False,
            report_to="none",
        ),
        train_dataset=train,
        eval_dataset=val,
        data_collator=make_collator(tok.pad_token_id),
    )
    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    print("готово:", args.out)


if __name__ == "__main__":
    main()
