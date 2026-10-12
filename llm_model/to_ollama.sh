#!/usr/bin/env bash
# HF-модель → GGUF (Q8_0 и Q4_K_M) → Ollama.
# Нужен llama.cpp: git clone https://github.com/ggml-org/llama.cpp && cmake -B build && cmake --build build -j
set -euo pipefail

MODEL_DIR=${1:-stella-1.5b}
LLAMA_CPP=${LLAMA_CPP:-../llama.cpp}

pip install -q -r "$LLAMA_CPP/requirements.txt"
python "$LLAMA_CPP/convert_hf_to_gguf.py" "$MODEL_DIR" --outtype q8_0 --outfile stella-1.5b-Q8_0.gguf
python "$LLAMA_CPP/convert_hf_to_gguf.py" "$MODEL_DIR" --outtype f16 --outfile stella-1.5b-F16.gguf
"$LLAMA_CPP/build/bin/llama-quantize" stella-1.5b-F16.gguf stella-1.5b-Q4_K_M.gguf Q4_K_M
rm stella-1.5b-F16.gguf

ollama create stella -f Modelfile                       # Q8 (по умолчанию в Modelfile)
sed 's/Q8_0/Q4_K_M/' Modelfile > Modelfile.q4 && ollama create stella:q4 -f Modelfile.q4
echo 'Готово: ollama run stella   |   ollama run stella:q4'
