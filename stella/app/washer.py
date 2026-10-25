"""Подбор режима стирки по описанию белья. Запуск — только через home.act с подтверждением."""
from . import config, home

# ключ режима, температура, отжим, подсказка
RULES = [
    (("шерст", "кашемир", "wool"), ("wool", 30, 600, "шерсть 30°, отжим 600")),
    (("шёлк", "шелк", "кружев", "деликат", "нежн"), ("delicate", 30, 600, "деликатная 30°, отжим 600")),
    (("спорт", "синтет", "куртк", "мембран"), ("synthetic", 40, 800, "синтетика 40°, отжим 800")),
    (("чёрн", "черн", "тёмн", "темн", "джинс"), ("dark", 30, 800, "тёмное 30°, отжим 800")),
    (("полотен", "постел", "простын", "наволоч", "белое"), ("cotton", 60, 1200, "хлопок 60°, отжим 1200")),
    (("носк", "футбол", "бельё", "белье", "хлопок", "одежд"), ("cotton", 60, 1200, "хлопок 60°, отжим 1200")),
]


def plan(items: str) -> dict:
    t = items.lower()
    for words, (key, temp, spin, label) in RULES:
        if any(w in t for w in words):
            return {"program": key, "temp": temp, "spin": spin, "label": label}
    return {"program": "synthetic", "temp": 40, "spin": 800, "label": "синтетика 40°, отжим 800 (по умолчанию)"}


async def start(items: str, confirmed: bool) -> dict:
    p = plan(items)
    if not config.WASHER_ENTITY:
        return {"error": "WASHER_ENTITY не настроен", **p}
    if not confirmed:
        # первый вызов регистрирует ожидание подтверждения внутри home.act
        r = await home.act(config.WASHER_ENTITY, "on", None, False)
        return {**r, **p, "note": "Назовите режим пользователю и спросите, запускать ли. Бельё он загружает сам."}
    if config.WASHER_PROGRAM_SELECT:
        option = config.WASHER_PROGRAMS.get(p["program"], p["program"])
        r = await home.call("select", "select_option", config.WASHER_PROGRAM_SELECT, {"option": option})
        if "error" in r:
            return r
    r = await home.act(config.WASHER_ENTITY, "on", None, True)
    return {**r, **p}
