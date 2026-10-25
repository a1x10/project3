"""Мозг: цикл «LLM -> инструменты -> ответ» + память."""
import datetime as dt
import json
import time

from . import bus, calendar_g, config, db, home, llm, notifs, vision

_drafts: dict[str, dict] = {}   # черновики ответов, ждущие «отправляй»


def system_prompt() -> str:
    facts = "\n".join(f"- {r['fact']}" for r in db.q("SELECT fact FROM memory ORDER BY ts DESC LIMIT 100")) or "- пока ничего"
    now = dt.datetime.now(config.TZ).strftime("%A %Y-%m-%d %H:%M %Z")
    return (
        f"Ты Стелла — личный ассистент в стиле Джарвиса для пользователя по имени {config.USER_NAME}. "
        "Отвечай по-русски, кратко: 1–2 предложения, ответ читают на маленьком экране очков. "
        f"Сейчас: {now}.\n"
        "Правила:\n"
        "- Важные факты о пользователе сохраняй инструментом remember.\n"
        "- Ответ на чужое сообщение: сначала draft_reply, покажи текст, отправляй (send_reply) только после явного согласия.\n"
        "- Замок и стиралка: сначала переспроси; confirmed=true только после явного 'да' пользователя.\n"
        "- Не выдумывай результаты инструментов.\n"
        f"Что ты знаешь о пользователе:\n{facts}"
    )


def _tool(name, desc, props, required=()):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": list(required)}}}


S, I, B = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}
TOOLS = [
    _tool("remember", "Запомнить факт о пользователе", {"fact": S}, ["fact"]),
    _tool("calendar_list", "События календаря в промежутке (ISO-даты)", {"start": S, "end": S}, ["start", "end"]),
    _tool("calendar_add", "Создать событие", {"title": S, "start": S, "duration_min": I}, ["title", "start"]),
    _tool("calendar_move", "Перенести событие по id (сначала calendar_list)", {"event_id": S, "new_start": S}, ["event_id", "new_start"]),
    _tool("recent_messages", "Последние входящие сообщения (WhatsApp/Telegram/SMS)", {}),
    _tool("draft_reply", "Составить черновик ответа на сообщение и показать его на HUD",
          {"sender": S, "text": S}, ["sender", "text"]),
    _tool("send_reply", "Отправить ранее составленный черновик (только после согласия пользователя)", {"sender": S}, ["sender"]),
    _tool("home_list", "Список устройств дома и их состояние", {}),
    _tool("home_action", "Управление домом. action: on/off/toggle/lock/unlock/volume_up/volume_down/mute/set. "
          "Для замков и стиралки сервер потребует confirmed=true.",
          {"device": S, "action": S, "data": {"type": "object"}, "confirmed": B}, ["device", "action"]),
    _tool("find_item", "Где пользователь оставил предмет: возвращает последние снимки с описаниями", {"item": S}, ["item"]),
]


async def run_tool(name: str, a: dict):
    try:
        if name == "remember":
            db.x("INSERT OR REPLACE INTO memory(fact,ts) VALUES(?,?)", (a["fact"], time.time()))
            return {"ok": True}
        if name == "calendar_list":
            return calendar_g.list_events(a["start"], a["end"])
        if name == "calendar_add":
            return calendar_g.add_event(a["title"], a["start"], a.get("duration_min", 60))
        if name == "calendar_move":
            return calendar_g.move_event(a["event_id"], a["new_start"])
        if name == "recent_messages":
            return [dict(app=r["app"], sender=r["sender"], text=r["text"]) for r in
                    db.q("SELECT app,sender,text FROM notifs ORDER BY ts DESC LIMIT 8")]
        if name == "draft_reply":
            n = notifs.find_recent(sender=a["sender"])
            if not n:
                return {"error": "нет сообщения от этого контакта"}
            _drafts[a["sender"].lower()] = {"key": n["key"], "app": n["app"], "sender": n["sender"], "text": a["text"]}
            bus.publish("hud", text=f"Ответ для {n['sender']}: {a['text']}")
            return {"status": "draft_shown", "note": "спросите, отправлять ли"}
        if name == "send_reply":
            d = _drafts.pop(a["sender"].lower(), None)
            if not d:
                return {"error": "нет черновика"}
            bus.publish("action", action="reply", key=d["key"], app=d["app"], sender=d["sender"], text=d["text"])
            return {"status": "sent"}
        if name == "home_list":
            return await home.list_devices()
        if name == "home_action":
            return await home.act(a["device"], a["action"], a.get("data"), bool(a.get("confirmed")))
        if name == "find_item":
            return vision.find(a["item"])
    except Exception as e:   # инструмент не должен ронять диалог
        return {"error": f"{type(e).__name__}: {e}"}
    return {"error": f"неизвестный инструмент {name}"}


async def ask(text: str) -> str:
    db.x("INSERT INTO history(role,content,ts) VALUES('user',?,?)", (text, time.time()))
    hist = [{"role": r["role"], "content": r["content"]} for r in
            reversed(db.q("SELECT role,content FROM history ORDER BY id DESC LIMIT 12"))]
    msgs = [{"role": "system", "content": system_prompt()}, *hist]
    for _ in range(6):
        m = await llm.chat(msgs, TOOLS)
        calls = m.get("tool_calls")
        if not calls:
            ans = (m.get("content") or "").strip() or "Готово."
            db.x("INSERT INTO history(role,content,ts) VALUES('assistant',?,?)", (ans, time.time()))
            return ans
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        for c in calls:
            try:
                args = json.loads(c["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            res = await run_tool(c["function"]["name"], args)
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": json.dumps(res, ensure_ascii=False)})
    return "Не получилось выполнить, попробуйте иначе."
