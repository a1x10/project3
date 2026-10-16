"""Она видит фото и стикеры, читает старую переписку."""

import io

from PIL import Image

from bot.media import image_for_model

from .conftest import PETYA, VASYA, settle, upsert


async def feed(brain, *payloads):
    for p in payloads:
        await brain.handle_payload(p)
    await settle(brain)


def png(color=(255, 0, 0), size=(2400, 1200), mode="RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def test_image_for_model_shrinks_and_flattens():
    mt, data = image_for_model(png(size=(4000, 2000)))
    img = Image.open(io.BytesIO(data))
    assert mt == "image/jpeg" and max(img.size) <= 1568
    mt, data = image_for_model(png((0, 0, 0, 0), (512, 512), "RGBA"))  # прозрачный стикер — на белом
    assert Image.open(io.BytesIO(data)).getpixel((5, 5)) == (255, 255, 255)
    assert image_for_model(b"not an image") is None


async def test_she_sees_a_photo_sent_to_her(brain):
    brain.evo.media = png()
    brain.llm.queue = ["красный квадрат)"]
    await feed(brain, upsert(message={"imageMessage": {"caption": "стелла что на фото?"}}, message_type="imageMessage"))
    call = brain.llm.calls[0]
    assert len(call["images"]) == 1 and call["images"][0].media_type == "image/jpeg"
    assert "приложены фото" in call["prompt"]


async def test_she_sees_a_photo_someone_replied_to(brain):
    brain.evo.media = png()
    brain.llm.queue = ["это задача на дроби"]
    await feed(brain, upsert("стелла реши это", quoted={"stanzaId": "IMG1", "participant": PETYA,
                                                       "quotedMessage": {"imageMessage": {"caption": ""}}}))
    assert len(brain.llm.calls[0]["images"]) == 1


async def test_no_images_for_plain_text_or_when_disabled(brain):
    brain.llm.queue = ["ок", "ок"]
    await feed(brain, upsert("стелла привет"))
    assert brain.llm.calls[0]["images"] == []
    brain.s.vision_enabled = False
    brain.evo.media = png()
    await feed(brain, upsert(message={"imageMessage": {"caption": "стелла глянь"}}, message_type="imageMessage"))
    assert brain.llm.calls[1]["images"] == []


async def test_read_chat_history_finds_old_talk(brain):
    for i in range(60):
        await brain.handle_payload(upsert(f"болтовня {i}", sender=PETYA, name="Петя"))
    await brain.handle_payload(upsert("едем на экскурсию в пятницу", sender=VASYA, name="Вася"))
    await settle(brain)

    async def look(tools, prompt):
        found = await tools["read_chat_history"].handler({"query": "экскурси"})
        assert "Вася" in found and "пятницу" in found and "болтовня" not in found
        recent = await tools["read_chat_history"].handler({"hours": 1, "limit": 20})
        assert recent.count("\n") <= 20
        return "в пятницу экскурсия"

    brain.llm.queue = [look]
    await feed(brain, upsert("стелла что там было про экскурсию"))
    assert brain.evo.texts()[-1] == "в пятницу экскурсия"


def docx_bytes(text: str) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


async def test_she_reads_a_document_sent_to_her(brain):
    brain.evo.media = docx_bytes("Контрольная по физике в пятницу, тема — сила тяжести")
    brain.llm.queue = ["в пятницу контрольная по физике"]
    await feed(brain, upsert(message={"documentMessage": {"caption": "стелла что тут", "fileName": "план.docx",
                                                           "mimetype": "application/vnd.openxmlformats-officedocument."
                                                                       "wordprocessingml.document"}},
                             message_type="documentMessage"))
    prompt = brain.llm.calls[0]["prompt"]
    assert "содержимое файла «план.docx»" in prompt and "сила тяжести" in prompt
    assert "read_link" in brain.llm.calls[0]["tools"]


async def test_reply_to_a_document_and_bad_file(brain):
    brain.evo.media = b"\x00\x01garbage"
    brain.llm.queue = ["не открылся"]
    await feed(brain, upsert("стелла прочитай", quoted={"stanzaId": "DOC1", "participant": PETYA, "quotedMessage": {
        "documentMessage": {"fileName": "x.pdf", "mimetype": "application/pdf"}}}))
    assert "[файл «x.pdf»:" in brain.llm.calls[0]["prompt"]
