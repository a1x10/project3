import httpx

from bot.main import create_app

from .conftest import settle, upsert


async def test_webhook_secret_and_background_processing(brain):
    app = create_app(brain.s, brain=brain)
    brain.llm.queue = ["хай"]
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bot") as client:
            r = await client.post("/webhook", json=upsert("стелла хай"))
            assert r.status_code == 401
            r = await client.post("/webhook", json=upsert("стелла хай"), headers={"x-webhook-secret": "s3cret"})
            assert r.status_code == 200 and r.json() == {"ok": True}
            await settle(brain)
            assert brain.evo.texts() == ["хай"]
            # byEvents=true: событие в пути
            payload = upsert("стелла ещё")
            payload.pop("event")
            brain.llm.queue = ["ещё хай"]
            r = await client.post("/webhook/messages-upsert", json=payload, headers={"x-webhook-secret": "s3cret"})
            assert r.status_code == 200
            await settle(brain)
            assert brain.evo.texts()[-1] == "ещё хай"
            health = (await client.get("/health")).json()
            assert health["ok"] and health["spend_today_usd"] > 0
