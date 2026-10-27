import asyncio
import contextlib
import logging
import threading

import uvicorn

from . import antivirus, api, config, db, demo, dns_server, scanner, telegram, vpn


@contextlib.asynccontextmanager
async def lifespan(app):
    db.connect()
    tasks = []
    if config.DEMO:
        demo.seed()
    else:
        tasks.append(asyncio.create_task(scanner.scan_loop()))
    tasks.append(asyncio.create_task(asyncio.to_thread(vpn.manager.restore)))
    telegram.bot.ensure_running()
    stop = threading.Event()
    threading.Thread(target=antivirus.watch_loop, args=(stop,), name="av-watch", daemon=True).start()
    try:
        yield
    finally:
        stop.set()
        telegram.bot.stop()
        for t in tasks:
            t.cancel()


api.app.router.lifespan_context = lifespan


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    dns_server.start()
    uvicorn.run(api.app, host=config.WEB_HOST, port=config.WEB_PORT, log_level="info")


if __name__ == "__main__":
    run()
