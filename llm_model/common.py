"""Общие константы и сборка ChatML. Используются и при обучении, и на инференсе,
чтобы модель видела ровно тот же формат, на котором училась."""

BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"

SYSTEM_PROMPT = (
    "Ты — Стелла, ИИ-ассистент. Тебя создал Алексей Моисеев. "
    "Отвечай сразу, коротко и точно."
)

IM_START = "<|im_start|>"
IM_END = "<|im_end|>"

# Чистый ChatML без подстановки системного промпта по умолчанию.
# Шаблон Qwen сам вставляет «You are Qwen, created by Alibaba Cloud...», если
# system не передан — поэтому при экспорте мы заменяем его на этот.
CHATML_TEMPLATE = (
    "{% for message in messages %}"
    "{{ '<|im_start|>' + message['role'] + '\\n' + message['content'] + '<|im_end|>' + '\\n' }}"
    "{% endfor %}"
    "{% if add_generation_prompt %}{{ '<|im_start|>assistant\\n' }}{% endif %}"
)


def render_chatml(messages, add_generation_prompt=False):
    """Текст в ChatML. Без system-сообщения системный блок не добавляется вовсе."""
    out = "".join(f"{IM_START}{m['role']}\n{m['content']}{IM_END}\n" for m in messages)
    if add_generation_prompt:
        out += f"{IM_START}assistant\n"
    return out
