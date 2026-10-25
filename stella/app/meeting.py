"""Режим совещания/собеседования/экзамена: субтитры + короткие подсказки на линзу."""
import time

from . import bus, config, llm

MODES = {
    "meeting": "Совещание. Выдели цифры, даты, договорённости; предложи, что уточнить.",
    "interview": "Собеседование: пользователь — кандидат. Если собеседник задал вопрос, дай краткий сильный ответ-тезисы.",
    "exam": "Экзамен/опрос. Если прозвучал вопрос — дай краткий правильный ответ и ключевые факты.",
}
state = {"on": False, "mode": "meeting", "context": "", "log": [], "t": 0.0}


def start(mode: str, context: str = ""):
    state.update(on=True, mode=mode if mode in MODES else "meeting", context=context, log=[], t=time.time())
    bus.publish("meeting", state="on", mode=state["mode"])


async def stop() -> str:
    state["on"] = False
    bus.publish("meeting", state="off")
    if not state["log"]:
        return ""
    msg = await llm.chat([
        {"role": "system", "content": "Сделай краткое резюме встречи по-русски: решения, даты, задачи (до 6 пунктов)."},
        {"role": "user", "content": "\n".join(state["log"])[-8000:]}], max_tokens=500)
    return (msg.get("content") or "").strip()


async def chunk(text: str):
    if not state["on"] or not text.strip():
        return None
    state["log"].append(text)
    bus.publish("subtitle", text=text)
    msg = await llm.chat([
        {"role": "system", "content": (
            f"Ты шепчешь подсказки {config.USER_NAME} в режиме: {MODES[state['mode']]} "
            f"Контекст: {state['context'] or '—'}. По последней реплике выдай подсказку до 15 слов: "
            "ответ, цифра или дата. Если подсказка не нужна — ровно: NONE")},
        {"role": "user", "content": "Недавно:\n" + "\n".join(state["log"][-6:])}], max_tokens=120)
    hint = (msg.get("content") or "").strip()
    if hint and not hint.upper().startswith("NONE"):
        bus.publish("hint", text=hint)
        return hint
    return None
