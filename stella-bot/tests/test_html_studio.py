"""HTML-страницы: студия пишет страницу по заданию Стеллы, библиотеки и шрифты встраиваются в файл."""

import asyncio
import hashlib
import io
from datetime import date
from types import SimpleNamespace

import pytest
from PIL import Image

from bot import html_studio, media, weblibs
from bot.tools import ToolError

from .conftest import OWNER, settle, upsert

GROUP = "120363000000000001@g.us"
PAGE = "<!doctype html><html><head><title>Игра</title></head><body><h1>Привет</h1></body></html>"
BRIEF = "игра «поймай звезду» для чата, неоновый космос, счёт и рекорд, кнопка Играть"


def _asset(tmp_path, file, path, data):
    (tmp_path / file).write_bytes(data)
    return weblibs.Asset(file, path, hashlib.sha256(data).hexdigest())


# ---------- библиотеки и шрифты ----------
def test_resolve_names_and_cdn_addresses():
    assert weblibs.resolve("lib/three.js") == (weblibs.THREE,)
    assert weblibs.resolve("./lib/three.min.js") == (weblibs.THREE,)
    assert weblibs.resolve("lib/three-bloom.js")[-1] == weblibs.BLOOM_PASS
    assert weblibs.resolve("lib/OrbitControls.js") == (weblibs.ORBIT,)
    assert weblibs.resolve("https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js") == (weblibs.THREE,)
    assert weblibs.resolve("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js") == (
        weblibs.ORBIT,)
    assert weblibs.resolve("https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/ScrollTrigger.min.js") == (
        weblibs.SCROLL_TRIGGER,)
    assert weblibs.resolve("https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js") == (
        weblibs.CONFETTI,)
    assert weblibs.resolve("https://unpkg.com/matter-js@0.19.0/build/matter.min.js") == (weblibs.MATTER,)
    for other in ("https://evil.example/three.min.js", "lib/nope.js", "https://cdn.jsdelivr.net/npm/x@1/gsap.js",
                  "data:text/javascript,alert(1)"):
        assert weblibs.resolve(other) is None, other


def test_every_pinned_asset_is_a_jsdelivr_file_with_sha256():
    assert len(weblibs.ALL) == len({a.file for a in weblibs.ALL})  # имена в кеше не пересекаются
    for a in weblibs.ALL:
        assert len(a.sha256) == 64 and a.url.startswith("https://cdn.jsdelivr.net/npm/") and "@" in a.path
        assert a.sri.startswith("sha256-")


def test_libraries_are_embedded_or_loaded_with_integrity(tmp_path, monkeypatch):
    gsap = _asset(tmp_path, "gsap.min.js", "gsap@9/dist/gsap.min.js", b"window.gsap={v:'</script>'};")
    monkeypatch.setitem(weblibs.LIBS, "gsap", (gsap,))
    html = ('<script src="lib/gsap.js"></script><script src="lib/gsap.js"></script>'
            '<script src="lib/three.js"></script><script src="https://evil.example/x.js"></script><h1>hi</h1>')
    text = media.html_page("t", html, libs_dir=str(tmp_path)).data.decode()
    assert text.count("window.gsap=") == 1 and "<\\/script>'" in text  # один раз и не рвёт <script>
    assert f'src="{weblibs.THREE.url}" integrity="{weblibs.THREE.sri}"' in text  # нет в кеше — с CDN по хешу
    csp = text.split('content="', 1)[1].split('"', 1)[0]
    assert weblibs.THREE.url in csp and "evil.example" not in csp and "connect-src 'none'" in csp
    assert text.index("Content-Security-Policy") < text.index("window.gsap")


def test_fonts_only_when_used(tmp_path, monkeypatch):
    cyr = _asset(tmp_path, "inter-cyrillic.woff2", "x@1/inter-c.woff2", b"wOF2cyr")
    lat = weblibs.Asset("inter-latin.woff2", "x@1/inter-l.woff2", "0" * 64)  # нет в кеше
    monkeypatch.setitem(weblibs.FONTS, "Inter", ("100 900", (cyr, lat)))
    used = media.html_page("t", "<style>body{font-family:'Inter',sans-serif}</style><p>Interactive</p>",
                           libs_dir=str(tmp_path)).data.decode()
    assert "font-family:'Inter'" in used and "data:font/woff2;base64," in used and lat.url in used
    assert lat.url in used.split('content="', 1)[1].split('"', 1)[0]  # шрифт с CDN разрешён точечно
    plain = media.html_page("t", "<p>Interactive international</p>", libs_dir=str(tmp_path)).data.decode()
    assert "@font-face" not in plain
    gfonts = media.html_page("t", '<link href="https://fonts.googleapis.com/css2?family=Inter" rel="stylesheet">'
                                  "<style>@import url('https://fonts.googleapis.com/css2?family=Inter');</style>"
                                  "<p style=\"font-family: Inter\">x</p>", libs_dir=str(tmp_path)).data.decode()
    assert "googleapis" not in gfonts and "@font-face" in gfonts


async def test_ensure_downloads_checks_hash_and_caches(tmp_path, monkeypatch):
    import httpx

    good, bad = b"good-lib", b"tampered"
    a1 = weblibs.Asset("a.js", "a@1/a.js", hashlib.sha256(good).hexdigest())
    a2 = weblibs.Asset("b.js", "b@1/b.js", hashlib.sha256(b"expected").hexdigest())
    monkeypatch.setattr(weblibs, "ALL", (a1, a2))
    hits = []

    def handler(request):
        hits.append(request.url.path)
        return httpx.Response(200, content=good if request.url.path.endswith("a.js") else bad)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        failed = await weblibs.ensure(str(tmp_path), client=client)
        assert failed == [a2] and (tmp_path / "a.js").read_bytes() == good and not (tmp_path / "b.js").exists()
        await weblibs.ensure(str(tmp_path), client=client)
    assert hits.count("/npm/a@1/a.js") == 1  # скачанное второй раз не качается


def test_photo_is_put_into_the_page():
    buf = io.BytesIO()
    Image.new("RGB", (3000, 2000), (200, 30, 30)).save(buf, "JPEG")
    photo = media.photo_for_page(buf.getvalue())
    assert photo[0] == "image/jpeg" and max(Image.open(io.BytesIO(photo[1])).size) == media.PAGE_PHOTO_SIDE
    text = media.html_page("t", '<img src="__PHOTO__"><div style="background:url(__PHOTO__)"></div>', photo).data
    assert text.count(b"data:image/jpeg;base64,") == 2 and b"__PHOTO__" not in text
    assert media.photo_for_page(b"not an image") is None
    sticker = io.BytesIO()
    Image.new("RGBA", (512, 512), (0, 0, 0, 0)).save(sticker, "WEBP")
    assert media.photo_for_page(sticker.getvalue())[0] == "image/webp"  # прозрачность сохраняется


def test_page_is_still_a_closed_box():
    text = media.html_page("Игра <3", '<meta http-equiv="refresh" content="0;url=http://evil"><base href="http://e/">'
                                      "<script>x=1</script>").data.decode()
    assert text.startswith("<!doctype html>") and text.index("Content-Security-Policy") < text.index("<script>")
    assert "refresh" not in text and "<base" not in text and "<title>Игра &lt;3</title>" in text
    for rule in ("default-src 'none'", "connect-src 'none'", "form-action 'none'", "worker-src blob:"):
        assert rule in text


# ---------- ответ студии ----------
def test_extract_html_variants():
    assert html_studio.extract_html(PAGE) == PAGE
    assert html_studio.extract_html(f"Вот страница:\n```html\n{PAGE}\n```\nГотово!") == PAGE
    assert html_studio.extract_html(f"Конечно! {PAGE} надеюсь понравится") == PAGE
    assert html_studio.extract_html("<style>b{}</style><div>x</div>").startswith("<style>")
    with pytest.raises(html_studio.StudioError):
        html_studio.extract_html("извини, не могу")


def test_eta_words():
    assert html_studio.human_eta(50) == "примерно через минуту"
    assert html_studio.human_eta(180) == "минуты через 3"
    assert html_studio.human_eta(400) == "минут через 7"


class FakeStream:
    def __init__(self, owner, kwargs):
        self.owner, self.kwargs = owner, kwargs

    async def __aenter__(self):
        self.owner.calls.append(self.kwargs)
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        await asyncio.sleep(0)
        return self.owner.reply


class FakeClient:
    def __init__(self, text=PAGE, stop="end_turn"):
        self.calls = []
        self.reply = SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="thinking", thinking=""),
                                                                 SimpleNamespace(type="text", text=text)],
                                     usage=SimpleNamespace(input_tokens=3000, output_tokens=20000))
        self.messages = SimpleNamespace(stream=lambda **kw: FakeStream(self, kw))


async def test_generate_asks_the_strong_model_with_design_prompt(settings, monkeypatch):
    fake = FakeClient(f"```html\n{PAGE}\n```")
    monkeypatch.setattr(html_studio, "_client", fake)
    res = await html_studio.generate(settings, BRIEF, "Звёзды", ("image/jpeg", b"\xff\xd8jpeg"))
    call = fake.calls[0]
    assert res.html == PAGE and res.cost_usd > 0.3
    assert call["model"] == "claude-opus-5-5" and call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {"effort": "high"} and call["max_tokens"] == 64000
    assert "lib/three.js" in call["system"] and "Unbounded" in call["system"]
    image, text = call["messages"][0]["content"]
    assert image["type"] == "image" and "__PHOTO__" in text["text"] and BRIEF in text["text"]


async def test_generate_errors_keep_the_cost(settings, monkeypatch):
    monkeypatch.setattr(html_studio, "_client", FakeClient(PAGE, stop="max_tokens"))
    with pytest.raises(html_studio.StudioError, match="слишком большой") as exc:
        await html_studio.generate(settings, BRIEF, "x")
    assert exc.value.cost_usd > 0
    monkeypatch.setattr(html_studio, "_client", FakeClient("не буду", stop="refusal"))
    with pytest.raises(html_studio.StudioError, match="отказались"):
        await html_studio.generate(settings, BRIEF, "x")


# ---------- в чате: задание → «делаю, минуты через 3» → файл ----------
@pytest.fixture
def studio(monkeypatch):
    calls = {"n": 0, "delay": 0.0, "fail": None, "args": []}

    async def run(settings, brief, title, image=None):
        calls["n"] += 1
        calls["args"].append((brief, title, image))
        await asyncio.sleep(calls["delay"])
        if calls["fail"]:
            raise html_studio.StudioError(calls["fail"], 0.25)
        return html_studio.StudioResult(PAGE.replace("Привет", "<img src='__PHOTO__'>Привет"), 0.5, 1.0)

    async def no_download(*a, **kw):
        return []

    monkeypatch.setattr(html_studio, "run", run)
    monkeypatch.setattr(weblibs, "ensure", no_download)
    html_studio.STATE.busy_chats.clear()
    yield calls
    html_studio.STATE.busy_chats.clear()


def _html_tool(reply, **extra):
    async def talk(tools, prompt):
        out = await tools["make_html"].handler({"title": "Звёзды", "brief": BRIEF, "caption": "играй!", **extra})
        assert "уже делается" in out and "Код писать не нужно" in out
        return reply
    return talk


async def feed(brain, *payloads):
    for p in payloads:
        await brain.handle_payload(p)
    await settle(brain, timeout=20)


async def _chat_id(brain):
    return (await brain.db.get_chat_by_jid("stella", GROUP))["id"]


async def test_reply_first_then_html_file_as_answer(brain, studio):
    brain.llm.queue = [_html_tool("делаю игру, минуты через 3 ✨")]
    await feed(brain, upsert("стелла сделай игру html", msg_id="ASK1"))
    assert [m["type"] for m in brain.evo.sent] == ["text", "media"]
    doc = brain.evo.sent[1]
    assert doc["mimetype"] == "text/html" and doc["filename"] == "Звёзды.html" and doc["caption"] == "играй!"
    assert doc["quoted"]["key"]["id"] == "ASK1"  # файл — ответом на просьбу
    assert studio["args"][0][:2] == (BRIEF, "Звёзды") and studio["args"][0][2] is None
    assert await brain.refresh_spend() >= 0.5  # расходы студии учтены в дневном бюджете


async def test_silent_model_still_announces_and_failure_refunds(brain, studio):
    brain.llm.queue = [_html_tool("<молчу>")]
    await feed(brain, upsert("стелла сайт"))
    assert brain.evo.texts()[0].startswith("делаю страницу ✨ будет готова")
    studio["fail"] = "страница делалась слишком долго"
    brain.llm.queue = [_html_tool("делаю")]
    await feed(brain, upsert("стелла ещё сайт"))
    assert brain.evo.texts()[-1] == "страница не получилась 😕 страница делалась слишком долго"
    used = await brain.db.kv_get(f"html:{await _chat_id(brain)}:{date.today().isoformat()}")
    assert used[1] == 1  # неудачная не съела лимит
    assert await brain.refresh_spend() >= 0.75  # а потраченное студией учтено


async def test_limits_busy_chat_and_bad_brief(brain, studio):
    errors = []

    async def try_tool(args):
        try:
            await brain_tools["make_html"].handler(args)
        except ToolError as exc:
            errors.append(str(exc))

    brain_tools = {}

    async def twice(tools, prompt):
        brain_tools.update(tools)
        await try_tool({"title": "x", "brief": "коротко"})
        await tools["make_html"].handler({"title": "x", "brief": BRIEF})
        await try_tool({"title": "y", "brief": BRIEF})
        return "делаю"

    brain.s.html_per_day = 1
    studio["delay"] = 0.3
    brain.llm.queue = [twice]
    await feed(brain, upsert("стелла сайт"))
    assert "опиши подробно" in errors[0] and errors[1] == "за один ответ — одна страница"

    async def again(tools, prompt):
        brain_tools.update(tools)
        await try_tool({"title": "x", "brief": BRIEF})
        return "ок"

    brain.llm.queue = [again]
    await feed(brain, upsert("стелла ещё"))
    assert "хватит" in errors[-1]
    brain.llm.queue = [_html_tool("ок")]
    await feed(brain, upsert("стелла сайт", sender=f"{OWNER}@s.whatsapp.net", name="Хозяин"))  # владельцу можно
    assert len([m for m in brain.evo.sent if m["type"] == "media"]) == 2


async def test_second_request_while_busy_is_refused(brain, studio):
    errors = []
    studio["delay"] = 0.5

    async def second(tools, prompt):
        try:
            await tools["make_html"].handler({"title": "x", "brief": BRIEF})
        except ToolError as exc:
            errors.append(str(exc))
        return "ок"

    brain.llm.queue = [_html_tool("делаю"), second]
    await brain.handle_payload(upsert("стелла сайт"))
    for _ in range(100):
        await asyncio.sleep(0.02)
        if brain.evo.texts():
            break
    await feed(brain, upsert("стелла и ещё один"))
    assert errors == ["я уже делаю страницу для этого чата — подожди, пока пришлю"]


async def test_budget_and_switch_off(brain, studio):
    errors = []

    async def grab(tools, prompt):
        try:
            await tools["make_html"].handler({"title": "x", "brief": BRIEF})
        except ToolError as exc:
            errors.append(str(exc))
        return "ок"

    await brain.db.kv_add(f"spend:{date.today().isoformat()}", brain.s.daily_budget_usd)
    brain.llm.queue = [grab]
    await feed(brain, upsert("стелла сайт"))
    brain.s.html_enabled = False
    brain.llm.queue = [grab]
    await feed(brain, upsert("стелла сайт"))
    assert "бюджет" in errors[0] and "выключены" in errors[1] and studio["n"] == 0


async def test_page_with_photo_from_chat(brain, studio):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 200, 10)).save(buf, "JPEG")
    brain.evo.media = buf.getvalue()
    brain.llm.queue = [_html_tool("делаю открытку", use_photo=True)]
    photo = {"stanzaId": "PH1", "participant": "77011111111@s.whatsapp.net",
             "quotedMessage": {"imageMessage": {"url": "x", "mimetype": "image/jpeg"}}}
    await feed(brain, upsert("стелла сделай открытку с этой фоткой", quoted=photo))
    assert studio["args"][0][2][0] == "image/jpeg"  # студия видит фото
    assert brain.evo.sent[-1]["type"] == "media" and brain.evo.sent[-1]["size"] > 1000  # фото внутри файла


async def test_photo_required_when_asked(brain, studio):
    errors = []

    async def ask(tools, prompt):
        try:
            await tools["make_html"].handler({"title": "x", "brief": BRIEF, "use_photo": True})
        except ToolError as exc:
            errors.append(str(exc))
        return "ок"

    brain.llm.queue = [ask]
    await feed(brain, upsert("стелла открытку с фото"))
    assert "фото нет" in errors[0]


async def test_paused_chat_gets_no_page(brain, studio):
    from datetime import timedelta

    from bot.util import utcnow

    studio["delay"] = 0.3

    async def talk(tools, prompt):
        await tools["make_html"].handler({"title": "x", "brief": BRIEF})
        await brain.db.update_chat(await _chat_id(brain), paused_until=utcnow() + timedelta(minutes=5))
        return "делаю"

    brain.llm.queue = [talk]
    await feed(brain, upsert("стелла сайт"))
    assert not [m for m in brain.evo.sent if m["type"] == "media"]
    used = await brain.db.kv_get(f"html:{await _chat_id(brain)}:{date.today().isoformat()}")
    assert not used or used[1] == 0
