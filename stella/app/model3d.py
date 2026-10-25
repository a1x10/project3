"""Генерация разборной 3D-модели механизма: LLM -> JSON деталей для three.js (/lab3d)."""
import json
import re

from . import llm

PROMPT = (
    "Ты инженер-конструктор. Верни ТОЛЬКО JSON без пояснений: "
    '{"title":str,"parts":[{"name":str,"shape":"box|cylinder|sphere|torus","size":[x,y,z],'
    '"pos":[x,y,z],"explode":[x,y,z],"color":"#rrggbb"}]}. '
    "Не более 14 деталей, единицы условные (весь механизм ~ 4 в поперечнике). "
    "pos — положение в собранном виде, explode — смещение детали в разобранном виде. "
    "Для cylinder size=[радиус,высота,0], для sphere [радиус,0,0], для torus [радиус,трубка,0]. Оси: Y вверх."
)


def _num3(v, default):
    try:
        out = [float(x) for x in v][:3]
        return out + [0.0] * (3 - len(out))
    except (TypeError, ValueError):
        return default


def sanitize(spec: dict) -> dict:
    parts = []
    for p in (spec.get("parts") or [])[:14]:
        shape = p.get("shape") if p.get("shape") in ("box", "cylinder", "sphere", "torus") else "box"
        color = p.get("color") if re.fullmatch(r"#[0-9a-fA-F]{6}", str(p.get("color", ""))) else "#33ff66"
        parts.append({"name": str(p.get("name", "деталь"))[:40], "shape": shape,
                      "size": _num3(p.get("size"), [1, 1, 1]), "pos": _num3(p.get("pos"), [0, 0, 0]),
                      "explode": _num3(p.get("explode"), [0, 1, 0]), "color": color})
    return {"title": str(spec.get("title", "Модель"))[:60], "parts": parts}


async def generate(prompt: str) -> dict:
    msg = await llm.chat([{"role": "system", "content": PROMPT}, {"role": "user", "content": prompt}], max_tokens=1800)
    text = msg.get("content") or ""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("модель не вернула JSON")
    return sanitize(json.loads(m.group(0)))
