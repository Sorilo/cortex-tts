from __future__ import annotations

import asyncio
import logging
import signal

from aiohttp import web

from .api import make_app
from .config import Settings
from .engine import Engine
from .wyoming_adapter import start_wyoming


async def serve() -> None:
    settings = Settings.from_env()
    if not settings.api_token:
        raise RuntimeError("CORTEX_TTS_TOKEN is required")
    engine = Engine(settings)
    await engine.start()
    runner = web.AppRunner(make_app(engine, settings))
    await runner.setup()
    site = web.TCPSite(runner, settings.api_host, settings.api_port)
    wyoming = None
    try:
        await site.start()
        wyoming = await start_wyoming(engine, settings)
        stopped = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stopped.set)
        await stopped.wait()
    finally:
        if wyoming:
            await wyoming.stop()
        await runner.cleanup()
        await engine.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
