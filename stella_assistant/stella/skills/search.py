"""Справка и поиск: Википедия, поиск в интернете (DuckDuckGo) с пересказом через YandexGPT, переводчик."""
from __future__ import annotations

import re

from ..nlp.text import first_sentence
from .base import Reply, Skill, intent

LANGS = {
    "англ": "en", "немец": "de", "франц": "fr", "испан": "es", "итальян": "it", "китай": "zh", "япон": "ja",
    "корей": "ko", "турец": "tr", "украин": "uk", "белорус": "be", "казах": "kk", "португал": "pt", "араб": "ar",
    "польск": "pl", "чешск": "cs", "греческ": "el", "иврит": "he", "латын": "la", "русск": "ru", "финск": "fi",
    "шведск": "sv", "норвежск": "no", "голланд": "nl", "нидерланд": "nl", "узбек": "uz", "армян": "hy",
    "грузин": "ka", "татар": "tt", "хинди": "hi", "вьетнам": "vi", "тайск": "th", "эсперанто": "eo",
}
LANG_NAMES = {"en": "английский", "de": "немецкий", "fr": "французский", "es": "испанский", "it": "итальянский",
              "zh": "китайский", "ja": "японский", "ko": "корейский", "tr": "турецкий", "uk": "украинский",
              "ru": "русский"}


def lang_code(word: str | None):
    w = (word or "").lower().replace("по-", "")
    for stem, code in LANGS.items():
        if w.startswith(stem):
            return code
    return None


class Search(Skill):
    name = "search"

    # ------------------------------------------------------------ википедия --
    def wiki(self, query: str) -> str | None:
        try:
            d = self.a.get_json("https://ru.wikipedia.org/w/api.php",
                                params={"action": "query", "list": "search", "srsearch": query, "srlimit": 1,
                                        "format": "json"})
            hits = d.get("query", {}).get("search", [])
            if not hits:
                return None
            title = hits[0]["title"]
            s = self.a.get_json("https://ru.wikipedia.org/api/rest_v1/page/summary/" + title.replace(" ", "_"))
            text = s.get("extract") or ""
            text = re.sub(r"\s*\([^()]*\)", "", text)  # убираем скобки с датами/транскрипцией
            text = re.sub(r"\s*\[\d+\]", "", text)
            text = re.sub("[\u0300\u0301]", "", text)  # знаки ударения из Википедии
            sentences = re.split(r"(?<=[.!?])\s+", text)
            return " ".join(sentences[:2]).strip() or None
        except Exception as e:
            self.log.warning("Википедия: %s", e)
            return None

    # ---------------------------------------------------------------- поиск --
    def web(self, query: str, n: int = 6) -> list[dict]:
        try:
            from ddgs import DDGS
        except ImportError:
            try:
                from duckduckgo_search import DDGS  # старое имя пакета
            except ImportError:
                self.log.warning("Поиск: pip install ddgs")
                return []
        for backend in ("auto", "duckduckgo"):  # «auto» опрашивает несколько поисковиков
            try:
                res = DDGS(timeout=8).text(query, region="ru-ru", max_results=n, backend=backend)
                res = [r for r in res if str(r.get("href", "")).startswith("http")]
                if res:
                    return res
            except Exception as e:
                self.log.info("Поиск (%s): %s", backend, e)
        return []

    def answer_with_search(self, ctx, query: str) -> Reply:
        if ctx.source == "voice":
            ctx.say("Сейчас поищу.", emotion="interest")
        results = self.web(query)
        if results and self.a.brain.available:
            th = self.a.brain.summarize_search(ctx.text, results)
            if th.text:
                links = "\n".join(f"{r['title']}: {r['href']}" for r in results[:3])
                return Reply(th.text, emotion=th.emotion or "interest", card=th.text + "\n\n" + links)
        if results:
            r = results[0]
            body = re.sub(r"\[\d+\]|\.\.\.$|…$", "", r.get("body", "")).strip()
            title = re.sub(r"\s+[—–-]\s+(?:Википедия|Wikipedia).*$", "", r["title"])
            return Reply(f"Вот что нашла: {title}. {first_sentence(body)}", card=r["href"])
        w = self.wiki(query)
        if w:
            return Reply(w, emotion="interest", intensity=0.6)
        return Reply("Ничего не нашла, извини.", emotion="sadness")

    @intent(r"\b(?:найди|поищи|загугли|погугли|поиск|ищи|найти|узнай)\b(?: (?:в|по) (?:интернете|сети|яндексе|гугле))?"
            r"(?: мне)?(?: информацию)?(?: (?:о|об|про))?\s+(.+)$", priority=35)
    def search(self, ctx):
        q = ctx.raw_group(1)
        if re.match(r"^(?:мой телефон|телефон)\b", q):
            return None  # «найди телефон» — навык поиска телефона
        return self.answer_with_search(ctx, q)

    @intent(r"^(?:кто так(?:ой|ая|ие)|что так(?:ое|ие)|что значит|что означает|кто был|кто была|"
            r"расскажи (?:про|о|об)|что ты знаешь (?:про|о|об))\s+(.+)$", priority=34)
    def what_is(self, ctx):
        q = ctx.raw_group(1)
        if self.a.brain.available:
            th = self.a.brain.think(ctx.text)
            if th.search:
                return self.answer_with_search(ctx, th.search)
            if th.text:
                return Reply(th.text, emotion=th.emotion or "interest")
        w = self.wiki(q)
        if w:
            return Reply(w, emotion="interest", intensity=0.6)
        return self.answer_with_search(ctx, q)

    # -------------------------------------------------------------- перевод --
    def translate(self, text: str, target: str) -> str | None:
        key, iam, folder = self.cfg.get("yandex.api_key"), self.cfg.get("yandex.iam_token"), \
            self.cfg.get("yandex.folder_id")
        if key or iam:
            body = {"targetLanguageCode": target, "texts": [text], "format": "PLAIN_TEXT", "speller": True}
            headers = {"Authorization": f"Api-Key {key}" if key else f"Bearer {iam}"}
            if not key and folder:
                body["folderId"] = folder
            try:
                r = self.a.http.post("https://translate.api.cloud.yandex.net/translate/v2/translate", json=body,
                                     headers=headers, timeout=10)
                if r.ok:
                    return r.json()["translations"][0]["text"]
                self.log.warning("Яндекс Переводчик: %s %s", r.status_code, r.text[:200])
            except Exception as e:
                self.log.warning("Яндекс Переводчик: %s", e)
        if self.a.brain.available:
            try:
                out = self.a.brain.ask(f"Переведи на язык «{target}» (ISO-код). Ответь только переводом, без кавычек и "
                                       f"пояснений:\n{text}", temperature=0.1, max_tokens=400)
                return out.strip().strip("«»\"")
            except Exception as e:
                self.log.warning("перевод через GPT: %s", e)
        return None

    @intent(r"\bпереведи(?:\s+фразу|\s+слово)?\s+(?:на|в)\s+(\w+)(?:\s+язык)?\s+(.+)$",
            r"\bпереведи(?:\s+фразу|\s+слово)?\s+(.+?)\s+(?:на|в)\s+(\w+)(?:\s+язык)?$",
            r"\bкак (?:будет|сказать|звучит|сказать слово)?\s*(?:по|на)\s*-?\s*(\w+)\s+(.+)$",
            r"\bкак (?:будет|сказать)\s+(.+?)\s+(?:по|на)\s*-?\s*(\w+)$", priority=60)
    def translate_intent(self, ctx):
        g1, g2 = ctx.match.group(1), ctx.match.group(2)
        code, text = lang_code(g1), g2
        if not code:
            code, text = lang_code(g2), g1
        if not code or not text:
            return None
        text = text.strip(" «»\"")
        result = self.translate(text, code)
        if not result:
            return Reply("Не получилось перевести — нужен ключ Yandex Cloud или YandexGPT.", emotion="sadness")
        lang = LANG_NAMES.get(code, "")
        prefix = f"По-{lang[:-2]}и" if lang.endswith("ий") else "Перевод"
        r = Reply(f"{prefix}: {result}", card=result, emotion="interest", intensity=0.5)
        r.data["translation"] = (result, code)
        if ctx.source == "voice" and code != "ru":  # иностранный текст читаем голосом нужного языка
            self.a.say(prefix + ":", emotion="interest")
            self.a.say(result, lang=code)
            r.speak = False
        return r
