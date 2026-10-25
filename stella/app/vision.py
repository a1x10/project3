import os
import time

from . import config, db, llm

AUTO_PROMPT = (
    "Ты Стелла, ассистент в очках. Пользователь навёл камеру и молчит. Определи, что ему нужно:\n"
    "- вопрос, пример, задача — дай короткий ответ;\n"
    "- текст на иностранном языке — переведи на русский;\n"
    "- предмет или вывеска — объясни в одну фразу.\n"
    "Ответ максимум 2 коротких предложения для маленького экрана. "
    "Если на кадре нет ничего важного, ответь ровно: NOTHING"
)
REMEMBER_PROMPT = (
    "Опиши в одном предложении, какие предметы на кадре и где они лежат/находятся "
    "(поверхность, комната, ориентиры). Особенно ключи, телефон, кошелёк, документы."
)


async def look(img: bytes) -> str | None:
    ans = await llm.see(AUTO_PROMPT, img)
    return None if not ans or ans.upper().startswith("NOTHING") else ans


async def remember(img: bytes) -> str:
    desc = await llm.see(REMEMBER_PROMPT, img)
    ts = time.time()
    path = os.path.join(config.DATA_DIR, "photos", f"{int(ts*1000)}.jpg")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(img)
    db.x("INSERT INTO photos(ts,description,path) VALUES(?,?,?)", (ts, desc, path))
    return desc


def find(query: str, limit: int = 40) -> list[dict]:
    """Последние снимки; выбор подходящего по смыслу делает LLM, вызвавшая инструмент."""
    import datetime as dt
    rows = db.q("SELECT ts,description FROM photos ORDER BY ts DESC LIMIT ?", (limit,))
    return [{"when": dt.datetime.fromtimestamp(r["ts"], config.TZ).strftime("%d.%m %H:%M"),
             "description": r["description"]} for r in rows]
