"""Списки покупок и дел, заметки. Синхронизируются через веб-панель и Telegram-бота."""
from __future__ import annotations

import re

from ..nlp.numbers import plural
from ..nlp.text import clean
from .base import Reply, Skill, intent

SHOP, TODO = "покупки", "дела"


def list_name(word: str | None) -> str:
    w = (word or "").lower()
    if not w or re.match(r"(покуп|магазин|продукт|шопинг)", w):
        return SHOP
    if re.match(r"(дел|задач|туду|todo|планы)", w):
        return TODO
    return w


def split_items(text: str) -> list[str]:
    text = re.sub(r"\s+(?:а также|и еще|еще)\s+", ",", text)
    parts = re.split(r"\s*,\s*|\s+и\s+", text)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def _with_commas(ctx, group: int) -> str:
    """Группа из того же шаблона, но по тексту с запятыми («молоко, хлеб и яйца»)."""
    from ..nlp.numbers import normalize_numbers
    t = normalize_numbers(re.sub(r"[^\w\s,]", " ", ctx.text.lower().replace("ё", "е")))
    t = re.sub(r"\s*,\s*", ", ", re.sub(r"\s+", " ", t)).strip()
    m = ctx.match.re.search(t)
    try:
        if m and m.group(group):
            return m.group(group)
    except IndexError:
        pass
    try:
        return ctx.match.group(group) or ""
    except IndexError:
        return ""


_LIST_WORDS = (r"(?:мой |наш )?(?:список (\w+)|список|покупки|покупок|дела|задачи|список дел|"
               r"список задач|туду)")


class Lists(Skill):
    name = "lists"

    @intent(r"\b(?:добавь|запиши|внеси|положи|закинь|занеси|допиши)\s+(.+?)\s+(?:в|во)\s+" + _LIST_WORDS + r"\b",
            priority=66)
    def add(self, ctx):
        items, name_word = _with_commas(ctx, 1), ctx.match.group(2)
        return self._add_items(list_name(name_word or self._which(ctx.norm)), items)

    @intent(r"\b(?:в|во)\s+" + _LIST_WORDS + r"\s+(?:добавь|запиши|внеси|положи|закинь)\s+(.+)$", priority=66)
    def add_to(self, ctx):
        name_word, items = ctx.match.group(1), _with_commas(ctx, 2)
        return self._add_items(list_name(name_word or self._which(ctx.norm)), items)

    @staticmethod
    def _which(norm: str) -> str:
        if re.search(r"\b(?:дел|дела|задач\w*|туду)\b", norm):
            return TODO
        return SHOP

    def _add_items(self, lname: str, items_text: str):
        existing = {clean(i["text"]) for i in self.a.memory.list_items(lname)}
        items, dupes = [], []
        for it in split_items(items_text):
            (dupes if clean(it) in existing else items).append(it)
        for it in items:
            self.a.memory.list_add(lname, it)
            existing.add(clean(it))
        where = "в список покупок" if lname == SHOP else "в список дел" if lname == TODO else f"в список {lname}"
        tail = f" {', '.join(dupes).capitalize()} уже в списке." if dupes else ""
        if not items:
            return Reply(f"{', '.join(dupes).capitalize()} уже в списке.", emotion="confidence", intensity=0.3)
        if len(items) == 1:
            return Reply(f"Добавила «{items[0]}» {where}.{tail}", emotion="confidence", intensity=0.4)
        return Reply(f"Добавила {where}: {', '.join(items)}.{tail}", emotion="confidence", intensity=0.4)

    @intent(r"^(?:надо|нужно|не забыть|не забудь)\s+купить\s+(.+)$|^купить\s+(.+)$", priority=63)
    def need_to_buy(self, ctx):
        items = _with_commas(ctx, 1) or _with_commas(ctx, 2)
        return self._add_items(SHOP, items)

    @intent(r"\b(?:добавь|создай|запиши|новая)\s+(?:задачу|дело|в дела)\s+(.+)$", priority=66)
    def add_task(self, ctx):
        return self._add_items(TODO, _with_commas(ctx, 1))

    @intent(r"\b(?:что|прочитай|покажи|какой|скажи|озвучь|продиктуй)\b.*\b(?:в )?(?:списке|список)\b(?:\s+(\w+))?|"
            r"\bчто (?:мне )?(?:нужно |надо )?купить\b|\b(?:мои|какие) (?:задачи|дела)\b|"
            r"\bчто (?:мне )?(?:нужно|надо) сделать\b|\bсписок (?:покупок|дел)\b", priority=64)
    def read(self, ctx):
        n = ctx.norm
        lname = TODO if re.search(r"\b(?:дел|дела|задач\w*|сделать)\b", n) else SHOP
        m = re.search(r"\bсписк\w* (\w+)", n)
        if m and list_name(m.group(1)) not in (SHOP, TODO) and m.group(1) not in ("покупок", "дел", "задач"):
            lname = m.group(1)
        items = self.a.memory.list_items(lname)
        title = "Список покупок" if lname == SHOP else "Список дел" if lname == TODO else f"Список «{lname}»"
        if not items:
            return Reply(f"{title} пуст.", emotion="neutral")
        names = [i["text"] for i in items]
        k = len(names)
        return Reply(f"{title}, {k} {plural(k, 'пункт', 'пункта', 'пунктов')}: " + ", ".join(names) + ".",
                     card="\n".join("• " + x for x in names))

    @intent(r"\b(?:удали|вычеркни|убери|сотри|исключи)\s+(.+?)\s+(?:из|со)\s+(?:списка|списков|покупок|дел|задач)"
            r"(?:\s+(\w+))?\b", r"\b(?:я )?(?:купил\w*|уже купил\w*)\s+(.+)$", priority=67)
    def remove(self, ctx):
        n = ctx.norm
        lname = TODO if re.search(r"\b(?:дел|задач)\b", n) else SHOP
        removed, missing = [], []
        for it in split_items(_with_commas(ctx, 1)):
            got = self.a.memory.list_remove(lname, it)
            (removed if got else missing).append(got["text"] if got else it)
        if removed and not missing:
            return Reply(f"Вычеркнула: {', '.join(removed)}.", emotion="joy", intensity=0.4)
        if removed:
            return Reply(f"Вычеркнула {', '.join(removed)}, а {', '.join(missing)} в списке не нашла.")
        return Reply(f"Не нашла в списке: {', '.join(missing)}.", emotion="surprise", intensity=0.4)

    @intent(r"\b(?:отметь|отмечай)\b(?:\s+задачу)?\s+(.+?)(?:\s+(?:как )?(?:выполненн\w*|сделанн\w*|готов\w*))?$|"
            r"^(?:я )?(?:сделал\w*|выполнил\w*|закончил\w*)\s+(.+)$", priority=62)
    def done(self, ctx):
        what = ctx.match.group(1) or ctx.match.group(2)
        got = self.a.memory.list_done(TODO, what)
        if got:
            return Reply(f"Отлично! Задача «{got['text']}» выполнена.", emotion="joy")
        return None

    @intent(r"\b(?:очисти|удали|сотри|обнули)\s+(?:весь\s+|все\s+)?(?:список|покупки|дела|задачи)(?:\s+(\w+))?\b",
            priority=68)
    def clear(self, ctx):
        lname = TODO if re.search(r"\b(?:дела|задачи|дел)\b", ctx.norm) else SHOP
        n = self.a.memory.list_clear(lname)
        return Reply("Список очищен." if n else "Список и так пуст.")

    # -------------------------------------------------------------- заметки --
    @intent(r"\b(?:запиши|создай|сделай|добавь|новая)\s+заметк\w*\s*(.+)$|^заметка\s+(.+)$", priority=67)
    def note(self, ctx):
        text = (ctx.match.group(1) or ctx.match.group(2) or "").strip(" :")
        if not text:
            self.a.start_session(self, self._note_followup, "заметка")
            return Reply("Что записать?", expect_reply=True, emotion="interest")
        self.a.memory.note_add(text)
        return Reply("Записала в заметки.", emotion="confidence", intensity=0.4)

    def _note_followup(self, ctx):
        self.a.end_session()
        self.a.memory.note_add(ctx.text)
        return Reply("Записала.", emotion="confidence", intensity=0.4)

    @intent(r"\b(?:прочитай|покажи|какие|мои|озвучь)\s+(?:мои\s+|все\s+|последние\s+)?заметк\w*", priority=66)
    def read_notes(self, ctx):
        notes = self.a.memory.notes(10)
        if not notes:
            return Reply("Заметок пока нет.")
        texts = [n["text"] for n in notes[:5]]
        return Reply("Последние заметки: " + "; ".join(texts) + ".", card="\n".join("• " + n["text"] for n in notes))

    @intent(r"\b(?:удали|сотри)\s+(?:все\s+)?заметк\w*\s*(.*)$", priority=68)
    def delete_note(self, ctx):
        what = ctx.group(1)
        if re.search(r"\bвсе\b", ctx.norm) or not what:
            if not what and not re.search(r"\bвсе\b", ctx.norm):
                notes = self.a.memory.notes(1)
                if notes:
                    self.a.memory.note_delete(notes[0]["id"])
                    return Reply("Удалила последнюю заметку.")
                return Reply("Заметок нет.")
            self.a.memory.notes_clear()
            return Reply("Все заметки удалены.")
        got = self.a.memory.note_find_delete(what)
        return Reply("Удалила заметку." if got else "Такой заметки не нашла.")
