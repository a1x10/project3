"""Мозг: цикл «LLM -> инструменты -> ответ» + память."""
import datetime as dt
import json
import time

from . import bus, calendar_g, config, db, home, llm, meeting, model3d, notifs, vision, washer

_drafts: dict[str, dict] = {}   # черновики ответов, ждущие «отправляй»


def system_prompt() -> str:
    facts = "\n".join(f"- {r['fact']}" for r in db.q("SELECT fact FROM memory ORDER BY ts DESC LIMIT 100")) or "- пока ничего"
    now = dt.datetime.now(config.TZ).strftime("%A %Y-%m-%d %H:%M %Z")
    return (
        f"Ты Стелла — личный ассистент в стиле Джарвиса для пользователя по имени {config.USER_NAME}. "
        "Отвечай по-русски, кратко: 1–2 предложения, ответ читают на маленьком экране очков. "
        f"Сейчас: {now}.\n"
        "Речь пользователя распознаётся автоматически и часто с ошибками (имена, падежи, слова-паразиты, «эээ», обрывки). "
        "Всегда восстанавливай смысл по контексту, истории диалога и памяти: «выруби телек» = выключи телевизор, «маме» = контакт «Мама», "
        "«перекинь на 4» = перенеси событие на 4 часа. Не переспрашивай по мелочам — действуй по самому вероятному смыслу. "
        "Переспрашивай одним коротким вопросом, только если от выбора зависит что-то необратимое (отправка, замок, стирка) или вариантов реально несколько.\n"
        "Если фраза явно не к тебе (обрывок чужого разговора) — ответь ровно: ...\n"
        "Каждая новая фраза — самостоятельная; старую тему продолжай, только если пользователь явно на неё ссылается («да», «отправляй», «перенеси на 4»). "
        "Простые вопросы («как дела», «привет», «кто ты») — просто отвечай, без инструментов.\n"
        "Правила:\n"
        "- Важные факты о пользователе сохраняй инструментом remember.\n"
        "- Ответ на чужое сообщение: сначала draft_reply, покажи текст, отправляй (send_reply) только после явного согласия.\n"
        "- Замок и стиралка: сначала переспроси; confirmed=true только после явного 'да' пользователя.\n"
        "- «Ответь голосом/голосовым»: start_voice_reply; потом покажи расшифровку и спроси, отправлять ли.\n"
        "- Стирка: washer_start; назови выбранный режим, спроси, запускать ли; бельё пользователь загружает сам.\n"
        "- Управление только голосом: «что это/прочитай/переведи» — look_around(look); «кто это» — look_around(face); "
        "«запомни» — look_around(memory); «покажи сообщения/календарь/дом» — open_screen; «построй/покажи модель» — model3d.\n"
        "- После look_around ответь коротко («Смотрю»), результат придёт сам.\n"
        "- Телевизор: tv_control. «Включи ютуб» — app=YouTube; «сделай потише» — volume_down; «hdmi 2» — input.\n"
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
    _tool("start_voice_reply", "Пользователь хочет ответить голосовым: очки запишут его речь, затем покажут текст на подтверждение",
          {"sender": S}, ["sender"]),
    _tool("washer_start", "Стирка: items — что стираем словами пользователя. Сервер подберёт режим. "
          "Сначала вызов без confirmed, назовите режим, спросите; потом confirmed=true.",
          {"items": S, "confirmed": B}, ["items"]),
    _tool("start_meeting", "Включить режим подсказок: meeting/interview/exam", {"mode": S, "context": S}, ["mode"]),
    _tool("stop_meeting", "Выключить режим совещания и вернуть резюме", {}),
    _tool("model3d", "Построить разборную 3D-модель механизма и показать на линзе", {"prompt": S}, ["prompt"]),
    _tool("tv_control", "Телевизор Sony Bravia (команда уйдёт на телефон, он в домашней сети). command: power_on, power_off, "
          "volume_up, volume_down, mute, volume_set (value 0-100), input (value: hdmi1..hdmi4, tv), app (value: название, напр. YouTube/Netflix), "
          "key (value: home, back, up, down, left, right, confirm, play, pause, channel_up, channel_down), status",
          {"command": S, "value": S}, ["command"]),
    _tool("look_around", "Камера очков. what: look (прочитать/понять, что вижу), face (кто напротив — только база лиц), "
          "memory (запомнить, что вижу и где лежит)", {"what": S}, ["what"]),
    _tool("open_screen", "Показать экран на очках: messages, calendar, home, vision, faces, memory, meeting, lab, menu", {"screen": S}, ["screen"]),
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
            bus.publish("action", action="reply_voice" if d.get("audio") else "reply", key=d["key"], app=d["app"],
                        sender=d["sender"], text=d["text"], audio=d.get("audio", ""))
            return {"status": "sent"}
        if name == "home_list":
            return await home.list_devices()
        if name == "home_action":
            return await home.act(a["device"], a["action"], a.get("data"), bool(a.get("confirmed")))
        if name == "start_voice_reply":
            n = notifs.find_recent(sender=a["sender"])
            if not n:
                return {"error": "нет сообщения от этого контакта"}
            bus.publish("record", purpose="voice_reply", sender=n["sender"], seconds=30)
            return {"status": "recording_started", "note": "Скажите: слушаю, диктуйте"}
        if name == "washer_start":
            return await washer.start(a["items"], bool(a.get("confirmed")))
        if name == "start_meeting":
            meeting.start(a["mode"], a.get("context", ""))
            return {"status": "on"}
        if name == "stop_meeting":
            return {"summary": await meeting.stop()}
        if name == "model3d":
            spec = await model3d.generate(a["prompt"])
            bus.publish("model3d", spec=spec)
            return {"status": "shown", "title": spec["title"], "parts": len(spec["parts"])}
        if name == "tv_control":
            bus.publish("action", action="tv", cmd=a["command"], value=str(a.get("value", "")))
            return {"status": "sent_to_phone", "note": "Если не сработает, придёт сообщение об ошибке. Ответьте коротко."}
        if name == "look_around":
            if a["what"] not in ("look", "face", "memory"):
                return {"error": "what: look/face/memory"}
            bus.publish("capture", what=a["what"])
            return {"status": "camera_started", "note": "Результат появится на линзе сам; отвечайте одним словом"}
        if name == "open_screen":
            bus.publish("open", screen=a["screen"])
            return {"status": "shown"}
        if name == "find_item":
            return vision.find(a["item"])
    except Exception as e:   # инструмент не должен ронять диалог
        return {"error": f"{type(e).__name__}: {e}"}
    return {"error": f"неизвестный инструмент {name}"}


TOOL_LABELS = {
    "remember": "Запоминаю", "calendar_list": "Смотрю календарь", "calendar_add": "Записываю в календарь",
    "calendar_move": "Переношу событие", "recent_messages": "Читаю сообщения", "draft_reply": "Пишу ответ",
    "send_reply": "Отправляю", "home_list": "Опрашиваю дом", "home_action": "Управляю домом",
    "washer_start": "Готовлю стирку", "start_voice_reply": "Включаю запись", "start_meeting": "Запускаю режим",
    "stop_meeting": "Готовлю резюме", "look_around": "Включаю камеру", "tv_control": "Управляю телевизором", "open_screen": "Открываю", "model3d": "Строю 3D-модель", "find_item": "Ищу в памяти",
}


async def ask(text: str, weak: bool = False, open_mode: bool = False) -> str:
    bus.publish("busy", on=True, label="Думаю")
    try:
        return await _ask(text, weak, open_mode)
    finally:
        bus.publish("busy", on=False)


async def _ask(text: str, weak: bool = False, open_mode: bool = False) -> str:
    db.x("INSERT INTO history(role,content,ts) VALUES('user',?,?)", (text, time.time()))
    hist = [{"role": r["role"], "content": r["content"]} for r in
            reversed(db.q("SELECT role,content FROM history WHERE ts>? ORDER BY id DESC LIMIT 8", (time.time() - 480,)))]
    sys_p = system_prompt()
    if weak:
        sys_p += ("\nВАЖНО: обращение распознано неуверенно: первое слово фразы могло быть искажённым именем «Стелла» "
                  "(«стала», «стол», «что», «сто»…), а могло быть обычной речью рядом. Если фраза не похожа на команду или вопрос "
                  "ассистенту — ответь ровно: ... Если похожа — выполни, считая искажённое первое слово именем, если без него фраза не имеет смысла.")
    if open_mode:
        sys_p += ("\nРЕЖИМ ПОСТОЯННОГО ПРОСЛУШИВАНИЯ: тебе передают любую услышанную фразу, она может быть не к тебе "
                  "(разговор рядом, телевизор, мысли вслух). Если фраза не похожа на команду или вопрос ассистенту — ответь ровно: ... "
                  "Если похожа — выполни.")
    msgs = [{"role": "system", "content": sys_p}, *hist]
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
            bus.publish("busy", on=True, label=TOOL_LABELS.get(c["function"]["name"], "Выполняю"))
            res = await run_tool(c["function"]["name"], args)
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": json.dumps(res, ensure_ascii=False)})
    return "Не получилось выполнить, попробуйте иначе."
