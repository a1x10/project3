"""Новости (RSS и поиск новостей) и чтение вслух веб-страниц и статей."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

from ..nlp.numbers import words_to_number
from ..nlp.text import first_sentence, stems
from .base import Reply, Skill, intent

_ORD = {"перв": 1, "втор": 2, "трет": 3, "четверт": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8}


def parse_feed(content: bytes) -> list[dict]:
    """RSS 2.0 / Atom без внешних библиотек."""
    out = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return out
    atom = "{http://www.w3.org/2005/Atom}"
    for it in root.iter("item"):
        out.append({"title": (it.findtext("title") or "").strip(), "link": (it.findtext("link") or "").strip(),
                    "summary": _strip_html(it.findtext("description") or "")})
    for it in root.iter(atom + "entry"):
        link = it.find(atom + "link")
        out.append({"title": (it.findtext(atom + "title") or "").strip(),
                    "link": link.get("href", "") if link is not None else "",
                    "summary": _strip_html(it.findtext(atom + "summary") or it.findtext(atom + "content") or "")})
    return [x for x in out if x["title"]]


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def extract_article(page_html: str, url: str = "") -> str:
    try:
        import trafilatura
        text = trafilatura.extract(page_html, url=url or None, include_comments=False, include_tables=False)
        if text:
            return text
    except Exception:
        pass
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(page_html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
            tag.decompose()
        root = soup.find("article") or soup.find("main") or soup.body or soup
        paras = [p.get_text(" ", strip=True) for p in root.find_all("p")]
        text = "\n".join(p for p in paras if len(p) > 40)
        if text:
            return text
    except Exception:
        pass
    paras = re.findall(r"<p[^>]*>(.*?)</p>", page_html or "", flags=re.S | re.I)
    return "\n".join(t for t in (_strip_html(p) for p in paras) if len(t) > 40)


class Reader(Skill):
    name = "reader"

    def __init__(self, a):
        super().__init__(a)
        self.items: list[dict] = []
        self.pos = 0

    def fetch(self, url: str) -> bytes:
        r = self.a.http.get(url, timeout=12)
        r.raise_for_status()
        return r.content

    def feed_items(self, topic: str | None) -> list[dict]:
        feeds: dict = self.cfg.get("news.feeds") or {}
        if topic:
            ts = set(stems(topic))
            for name, url in feeds.items():
                if ts & set(stems(name)):
                    return parse_feed(self.fetch(url))
            try:  # произвольная тема — ищем свежие новости
                from ddgs import DDGS
                res = DDGS(timeout=8).news(topic, region="ru-ru", timelimit="d", max_results=8)
                return [{"title": r["title"], "link": r.get("url", ""), "summary": r.get("body", "")} for r in res]
            except Exception as e:
                self.log.info("поиск новостей: %s", e)
        url = next(iter(feeds.values()), None)
        return parse_feed(self.fetch(url)) if url else []

    @intent(r"\b(?:новост\w*|что нового|что в мире|что происходит в мире|сводк\w*)\b(?:\s+(?:про|о|об|по|из|в|на тему)\s+(.+))?",
            priority=55)
    def news(self, ctx):
        topic = ctx.raw_group(1) or None
        label = topic
        if topic is None:
            m = re.search(r"\b(спорт\w*|технолог\w*|наук\w*|экономик\w*|политик\w*|культур\w*|игр\w*)\b", ctx.norm)
            topic = m.group(1) if m else None
            label = None
        try:
            self.items = self.feed_items(topic)
        except Exception as e:
            self.log.warning("новости: %s", e)
            return Reply("Не получилось загрузить новости.", emotion="sadness")
        if not self.items:
            return Reply("Свежих новостей не нашла.")
        self.pos = 0
        return self._next_batch(intro=f"Новости{' про ' + label if label else ''}. ")

    def _next_batch(self, intro: str = "") -> Reply:
        n = int(self.cfg.get("news.count", 5))
        batch = self.items[self.pos:self.pos + n]
        if not batch:
            self.a.end_session()
            return Reply("Это все новости на сейчас.")
        lines = [f"{self.pos + i + 1}. {it['title'].rstrip('.')}." for i, it in enumerate(batch)]
        self.pos += len(batch)
        self.a.start_session(self, self._session, "новости")
        tail = " Рассказать подробнее? Скажи номер новости или «дальше»."
        return Reply(intro + " ".join(lines) + tail, expect_reply=True, emotion="interest", intensity=0.5,
                     card="\n".join(f"{l}\n{it['link']}" for l, it in zip(lines, batch)))

    def _session(self, ctx):
        n = ctx.norm
        if re.search(r"\b(?:дальше|еще|следующ\w*|продолж\w*)\b", n):
            return self._next_batch()
        num = None
        for st, v in _ORD.items():
            if re.search(rf"\b{st}\w*", n):
                num = v
                break
        if num is None:
            val = words_to_number(n)
            num = int(val) if isinstance(val, (int, float)) and 0 < val <= len(self.items) else None
        if num and re.search(r"\b(?:подробн\w*|номер|про|о|прочитай|расскажи|открой)\b|^\d+$|^\w+ая$|^\w+ую$", n) \
                or (num and len(n.split()) <= 2):
            if 1 <= num <= len(self.items):
                return self._details(self.items[num - 1], ctx)
        self.a.end_session()
        return None  # это была другая команда — пусть обработают другие навыки

    def _details(self, item: dict, ctx) -> Reply:
        text = ""
        if item.get("link"):
            try:
                text = extract_article(self.fetch(item["link"]).decode("utf-8", "ignore"), item["link"])
            except Exception as e:
                self.log.info("статья: %s", e)
        if len(re.findall(r"[.!?]\s", text)) < 3:  # вместо статьи вытащилось меню сайта
            text = ""
        text = text or item.get("summary", "")
        if not text:
            return Reply("Подробностей нет, только заголовок.", expect_reply=True)
        if self.a.brain.available and len(text) > 900:
            try:
                summary = self.a.brain.ask("Перескажи новость в 3–4 предложениях для озвучки голосом, без markdown:\n\n"
                                           + text[:6000], temperature=0.3)
                return Reply(summary, card=item.get("link"), expect_reply=True)
            except Exception:
                pass
        return Reply(first_sentence(text, 700) if len(text) > 700 else text, card=item.get("link"), expect_reply=True)

    @intent(r"\b(?:прочитай|прочти|зачитай|озвучь|перескажи)\b.*?(https?://\S+)", priority=70)
    def read_url(self, ctx):
        m = re.search(r"https?://\S+", ctx.text)
        if not m:
            return None
        url = m.group(0).rstrip(").,»\"")
        try:
            text = extract_article(self.fetch(url).decode("utf-8", "ignore"), url)
        except Exception as e:
            return Reply(f"Не смогла открыть страницу: {e}", emotion="sadness")
        if not text:
            return Reply("На этой странице я не нашла текста статьи.", emotion="sadness")
        if re.search(r"\bперескажи\b", ctx.norm) and self.a.brain.available:
            return Reply(self.a.brain.ask("Перескажи кратко для озвучки голосом:\n\n" + text[:8000], temperature=0.3))
        return Reply(text[:6000], card=url)

    @intent(r"\b(?:прочитай|прочти|найди и прочитай|перескажи)\s+(?:мне\s+)?(?:статью|материал|заметку в интернете)\s+"
            r"(?:про|о|об)\s+(.+)$", priority=56)
    def read_topic(self, ctx):
        search = self.a.skill("search")
        results = search.web(ctx.group(1), 5) if search else []
        for r in results:
            try:
                text = extract_article(self.fetch(r["href"]).decode("utf-8", "ignore"), r["href"])
            except Exception:
                continue
            if len(text) > 300:
                if self.a.brain.available:
                    summary = self.a.brain.ask("Перескажи статью для озвучки голосом в 5–7 предложениях:\n\n"
                                               + text[:8000], temperature=0.3)
                    return Reply(f"Статья «{r['title']}». {summary}", card=r["href"])
                return Reply(f"Статья «{r['title']}». {text[:3000]}", card=r["href"])
        return Reply("Не нашла подходящей статьи.", emotion="sadness")
