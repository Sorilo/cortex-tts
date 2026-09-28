from __future__ import annotations

import asyncio
import logging
import signal
import time

from aiohttp import web

from .api import make_app
from .config import Settings
from .engine import Engine
from .wyoming_adapter import start_wyoming


async def warm_backend(engine: Engine, settings: Settings) -> None:
    """Compile the common Vulkan path before the service accepts clients."""
    begun = time.monotonic()
    async with asyncio.timeout(120):
        while not await engine.health():
            await asyncio.sleep(0.25)
        for phrase in (
            "Hello from Cortex.",
            "The lights are on and the doors are locked. I can check your schedule, "
            "summarize the weather, or help with another task whenever you are ready.",
        ):
            async with engine.session() as backend:
                await backend.send({"type": "start", "voice_id": settings.default_voice,
                                    "instruction": settings.default_instruction})
                await backend.send({"type": "text", "text": phrase})
                await backend.send({"type": "end"})
                audio_bytes = 0
                async for kind, payload in backend.events():
                    if kind == "audio":
                        audio_bytes += len(payload)
                    elif payload["type"] == "error":
                        raise RuntimeError(f"Breeze warmup failed: {payload}")
                    elif payload["type"] == "done":
                        break
                if not audio_bytes:
                    raise RuntimeError("Breeze warmup produced no audio")
    logging.info("Breeze warmup finished in %.3f s", time.monotonic() - begun)


async def serve() -> None:
    settings = Settings.from_env()
    if not settings.api_token:
        raise RuntimeError("CORTEX_TTS_TOKEN is required")
    engine = Engine(settings)
    await engine.start()
    runner = None
    wyoming = None
    try:
        if settings.warmup:
            await warm_backend(engine, settings)
        runner = web.AppRunner(make_app(engine, settings))
        await runner.setup()
        site = web.TCPSite(runner, settings.api_host, settings.api_port)
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
        if runner:
            await runner.cleanup()
        await engine.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())


if __name__ == "__main__":
    main()
