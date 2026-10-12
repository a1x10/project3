"""Всё локально, без видеокарты и облака: датасет → обучение на CPU → GGUF для Ollama.

По умолчанию берётся Qwen2.5-0.5B: она обучается на ноутбуке за 1–3 часа
и потом идёт на Raspberry Pi 4. Работает на Windows, Linux и macOS.

    pip install -r requirements.txt
    python local_pipeline.py                 # 0.5B → out/stella-0.5b-Q8_0.gguf + out/Modelfile
    python local_pipeline.py --size 1.5b     # для ноутбука с 16 ГБ RAM (обучение в ~3 раза дольше)

Затем (на ноутбуке или на Pi):
    cd out && ollama create stella -f Modelfile && ollama run stella
"""

import argparse
import io
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LLAMA_GIT = "https://github.com/ggml-org/llama.cpp"
LLAMA_ZIP = "https://github.com/ggml-org/llama.cpp/archive/refs/heads/master.zip"


def run(*args):
    print("\n>>>", " ".join(map(str, args)), flush=True)
    subprocess.run([sys.executable, *map(str, args)], check=True, cwd=HERE)


def get_converter(dest):
    """Скрипт convert_hf_to_gguf.py из llama.cpp; компилировать ничего не нужно."""
    script = dest / "convert_hf_to_gguf.py"
    if script.exists():
        return script
    print("скачиваю конвертер llama.cpp...", flush=True)
    if shutil.which("git"):
        subprocess.run(["git", "clone", "-q", "--depth", "1", LLAMA_GIT, str(dest)], check=True)
    else:
        extract_converter(urllib.request.urlopen(LLAMA_ZIP).read(), dest)
    return script


def extract_converter(data, dest):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = z.namelist()[0].split("/")[0]
        for name in z.namelist():
            rel = name[len(root) + 1:]
            if rel and not name.endswith("/"):
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                (dest / rel).write_bytes(z.read(name))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--size", choices=["0.5b", "1.5b"], default="0.5b")
    p.add_argument("--identity", type=int, default=800)
    p.add_argument("--extra", nargs="*", default=[], help="свои JSONL-диалоги")
    p.add_argument("--epochs", type=float, default=3)
    p.add_argument("--skip-train", action="store_true", help="только экспорт уже обученной LoRA")
    args = p.parse_args()

    base = f"Qwen/Qwen2.5-{args.size.upper()}-Instruct"
    name = f"stella-{args.size}"
    lora, merged, out = HERE / "runs" / f"{name}-lora", HERE / name, HERE / "out"
    out.mkdir(exist_ok=True)

    if not args.skip_train:
        run("build_dataset.py", "--out", "data", "--identity", args.identity,
            *(["--extra", *args.extra] if args.extra else []))
        run("train_sft.py", "--base", base, "--data", "data", "--out", lora,
            "--epochs", args.epochs, "--batch", 4, "--grad-accum", 4)
    run("export.py", "--base", base, "--adapter", lora, "--out", merged)

    gguf = out / f"{name}-Q8_0.gguf"
    run(get_converter(HERE / "runs" / "llama.cpp"), merged, "--outtype", "q8_0", "--outfile", gguf)

    modelfile = (HERE / "Modelfile").read_text(encoding="utf-8")
    modelfile = "\n".join(f"FROM ./{gguf.name}" if l.startswith("FROM ") else l for l in modelfile.splitlines())
    modelfile = modelfile.replace("num_ctx 4096", "num_ctx 2048")  # меньше RAM — важно для Pi
    (out / "Modelfile").write_text(modelfile + "\n", encoding="utf-8")

    run("chat.py", "--model", merged)
    print(f"\nГотово. Папка {out}:\n  cd {out}\n  ollama create stella -f Modelfile\n  ollama run stella")


if __name__ == "__main__":
    main()
