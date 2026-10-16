"""Стелла делает сама: стикеры, картинки, мемы, документы, презентации, таблицы, видео + человеческая речь."""

import io
import shutil

import pytest
from PIL import Image

from bot import media
from bot.humanize import parse_reply

from .conftest import settle, upsert

SMILE = ('<svg viewBox="0 0 512 512"><circle cx="256" cy="256" r="200" fill="#ffd166" stroke="#222" '
         'stroke-width="12"/><text x="256" y="480" font-size="48" text-anchor="middle" '
         'font-family="DejaVu Sans">ПРИВЕТ</text></svg>')


async def feed(brain, *payloads):
    for p in payloads:
        await brain.handle_payload(p)
    await settle(brain, timeout=60)


def test_svg_is_sanitized():
    dirty = ('<svg viewBox="0 0 10 10" onload="x()"><script>alert(1)</script>'
             '<image href="file:///app/.env" width="5" height="5"/><a href="http://evil"><rect width="5" '
             'height="5" style="fill:url(http://evil/x.png)"/></a><use href="#r"/><foreignObject>hi'
             '</foreignObject></svg>')
    clean = media.sanitize_svg(dirty)
    for bad in ("script", "<image", "file://", "http://evil", "onload", "foreignObject"):
        assert bad not in clean, bad
    assert 'href="#r"' in clean  # ссылки внутри рисунка можно
    with pytest.raises(media.MediaError):
        media.sanitize_svg('<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>')
    with pytest.raises(media.MediaError):
        media.sanitize_svg("просто текст")


def test_sticker_is_whatsapp_sized():
    st = media.sticker_from_svg(SMILE)
    img = Image.open(io.BytesIO(st.data))
    assert img.format == "WEBP" and img.size == (512, 512) and len(st.data) <= media.STICKER_MAX_BYTES


def test_spreadsheet_never_writes_formulas():
    import openpyxl

    x = media.spreadsheet("т", [{"name": "a", "rows": [["имя", "x"], ["вася", '=HYPERLINK("http://x")']]}])
    cell = openpyxl.load_workbook(io.BytesIO(x.data))["a"]["B2"]
    assert cell.data_type == "s"


async def test_she_draws_her_own_sticker_and_keeps_it(brain):
    async def draw(tools, prompt):
        await tools["make_sticker"].handler({"svg": SMILE, "mood": "приветик"})
        return "держи"

    brain.llm.queue = [draw]
    await feed(brain, upsert("стелла нарисуй стикер смайлик"))
    kinds = [m["type"] for m in brain.evo.sent]
    assert kinds == ["text", "sticker"]  # сначала её сообщение, потом стикер
    assert "приветик" in await brain.stickers.moods()


async def test_documents_presentation_spreadsheet(brain):
    async def make(tools, prompt):
        await tools["make_document"].handler({"format": "pdf", "title": "Доклад", "blocks": ["текст"]})
        await tools["make_presentation"].handler({"title": "Космос", "slides": [{"title": "Луна", "bullets": ["a"]}]})
        try:
            await tools["make_spreadsheet"].handler({"title": "т", "sheets": [{"rows": [["a"]]}]})
        except Exception as exc:
            assert "двух файлов" in str(exc)
        return "готово"

    brain.s.deck_studio = False  # простая презентация из списка слайдов (без браузера на сервере — она)
    brain.llm.queue = [make]
    await feed(brain, upsert("стелла сделай доклад и презу"))
    files = [m for m in brain.evo.sent if m["type"] == "media"]
    assert [f["mimetype"] for f in files] == [media.MIME["pdf"], media.MIME["pptx"]]
    assert files[0]["filename"] == "Доклад.pdf"



def test_html_page_is_a_closed_box():
    page = media.html_page("Игра <3", '<meta http-equiv="refresh" content="0;url=http://evil"><base href="http://evil/">'
                                      '<h1>Привет</h1><script>document.body.style.background="pink"</script>')
    text = page.data.decode("utf-8")
    assert page.kind == "document" and page.mimetype == "text/html" and page.filename == "Игра 3.html"
    assert text.startswith("<!doctype html>")
    assert text.index("Content-Security-Policy") < text.index("<script>")  # наш CSP раньше любого скрипта
    assert "connect-src 'none'" in text and "form-action 'none'" in text
    assert "refresh" not in text and "<base" not in text and "http://evil" not in text
    assert "<title>Игра &lt;3</title>" in text and "<body><h1>Привет</h1>" in text  # кусок обёрнут в страницу


def test_html_full_document_keeps_its_own_head():
    doc = '<!DOCTYPE html><html lang="ru"><head><title>Своя</title><script>x=1</script></head><body>hi</body></html>'
    text = media.html_page("т", doc).data.decode()
    assert text.count("<!doctype html>") + text.count("<!DOCTYPE") == 1
    assert "<title>Своя</title>" in text and "<title>т</title>" not in text
    assert text.index("Content-Security-Policy") < text.index("<script>")
    with pytest.raises(media.MediaError):
        media.html_page("т", "   ")
    with pytest.raises(media.MediaError):
        media.html_page("т", "x" * (media.MAX_HTML_CHARS + 1))


async def test_meme_from_quoted_sticker(brain):
    brain.evo.media = media.sticker_from_svg(SMILE).data

    async def meme(tools, prompt):
        await tools["make_meme"].handler({"top": "когда", "bottom": "пятница", "as_sticker": True})
        return "ахах"

    brain.llm.queue = [meme]
    await feed(brain, upsert("стелла сделай мем", quoted={"stanzaId": "ST9", "participant": "77011111111@s.whatsapp.net",
                                                          "quotedMessage": {"stickerMessage": {"url": "x"}}}))
    assert [m["type"] for m in brain.evo.sent] == ["text", "sticker"]


async def test_meme_needs_a_picture(brain):
    async def meme(tools, prompt):
        try:
            await tools["make_meme"].handler({"top": "x"})
        except Exception as exc:
            return f"ошибка: {exc}"
        return "?"

    brain.llm.queue = [meme]
    await feed(brain, upsert("стелла сделай мем"))
    assert "фото или стикера" in brain.evo.texts()[-1]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нет ffmpeg")
async def test_video_is_built_after_her_message(brain):
    async def video(tools, prompt):
        await tools["make_video"].handler({"scenes": [{"svg": SMILE.replace("512 512", "720 720"), "seconds": 1},
                                                     {"text": "конец", "seconds": 1}]})
        return "лови видос"

    brain.llm.queue = [video]
    await feed(brain, upsert("стелла сделай видео"))
    assert brain.evo.sent[0]["text"] == "лови видос"
    assert brain.evo.sent[-1]["type"] == "media" and brain.evo.sent[-1]["mimetype"] == "video/mp4"


async def test_bad_svg_is_reported_to_model(brain):
    async def bad(tools, prompt):
        try:
            await tools["make_picture"].handler({"svg": "<svg><rect width='x'"})
        except Exception as exc:
            return f"не вышло: {exc}"
        return "?"

    brain.llm.queue = [bad]
    await feed(brain, upsert("стелла нарисуй"))
    assert "не вышло" in brain.evo.texts()[-1]
    assert not [m for m in brain.evo.sent if m["type"] == "media"]


async def test_media_can_be_switched_off(brain):
    brain.s.media_enabled = False
    brain.llm.queue = ["ок"]
    await feed(brain, upsert("стелла привет"))
    assert "make_sticker" not in brain.llm.calls[0]["tools"]


async def test_daily_media_limit(brain):
    brain.s.media_per_day = 1

    async def two(tools, prompt):
        await tools["make_sticker"].handler({"svg": SMILE})
        return "раз"

    async def again(tools, prompt):
        try:
            await tools["make_sticker"].handler({"svg": SMILE})
        except Exception as exc:
            return str(exc)
        return "?"

    brain.llm.queue = [two, again]
    await feed(brain, upsert("стелла стикер"))
    await feed(brain, upsert("стелла ещё стикер"))
    assert "лимит" in brain.evo.texts()[-1]


def test_assistant_filler_is_removed():
    assert [s.value for s in parse_reply("Отличный вопрос! Думаю, майн\nНадеюсь, это поможет!")] == ["думаю, майн"]
    assert [s.value for s in parse_reply("**Конечно!** вот так")] == ["вот так"]
    assert [s.value for s in parse_reply("конечно, иди")] == ["конечно, иди"]
