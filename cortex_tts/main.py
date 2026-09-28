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


async def watch_backend(engine: Engine, settings: Settings, poll_seconds: float = 1.0) -> None:
    """Rewarm after a backend outage without admitting cold client turns."""
    while True:
        await asyncio.sleep(poll_seconds)
        if not await engine.health():
            engine.warm_ready = False
            continue
        if engine.warm_ready:
            continue
        try:
            async with engine.admission:
                await warm_backend(engine, settings)
            engine.warm_ready = True
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Breeze recovery warmup failed; retrying")


async def serve() -> None:
    settings = Settings.from_env()
    if not settings.api_token:
        raise RuntimeError("CORTEX_TTS_TOKEN is required")
    engine = Engine(settings)
    await engine.start()
    runner = None
    wyoming = None
    watcher = None
    try:
        if settings.warmup:
            engine.warm_ready = False
            await warm_backend(engine, settings)
            engine.warm_ready = True
        runner = web.AppRunner(make_app(engine, settings))
        await runner.setup()
        site = web.TCPSite(runner, settings.api_host, settings.api_port)
        await site.start()
        wyoming = await start_wyoming(engine, settings)
        if settings.warmup:
            watcher = asyncio.create_task(watch_backend(engine, settings))
        stopped = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stopped.set)
        await stopped.wait()
    finally:
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
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
