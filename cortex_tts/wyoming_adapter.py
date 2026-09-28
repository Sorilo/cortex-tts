"""Wyoming compatibility over the same Breeze streaming backend."""
from __future__ import annotations

import asyncio
import math
import time

import aiohttp

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event
from wyoming.info import Attribution, Describe, Info, TtsProgram, TtsVoice
from wyoming.server import AsyncEventHandler, AsyncTcpServer
from wyoming.tts import Synthesize, SynthesizeChunk, SynthesizeStart, SynthesizeStop, SynthesizeStopped

from .config import Settings
from .engine import Busy, Engine, ProtocolError

VERSION = "0.1.0-alpha.5"


def info_event(voice_ids: list[str]) -> Event:
    attribution = Attribution(name="cortex-tts", url="https://github.com/Sorilo/cortex-tts")
    voices = [TtsVoice(name="breeze-design", attribution=attribution, installed=True,
                       description="Breeze voice design", version=VERSION, languages=["en", "zh"])]
    voices += [TtsVoice(name=voice, attribution=attribution, installed=True,
                        description="Saved Breeze reference voice", version=VERSION,
                        languages=["en", "zh"]) for voice in voice_ids]
    return Info(tts=[TtsProgram(name="cortex-tts", attribution=attribution,
                                installed=True, description="Streaming Breeze TTS 2",
                                version=VERSION, voices=voices,
                                supports_synthesize_streaming=True)]).event()


class Handler(AsyncEventHandler):
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                 engine: Engine, settings: Settings):
        super().__init__(reader, writer)
        self.engine = engine
        self.settings = settings
        self.commands: asyncio.Queue[dict] | None = None
        self.worker: asyncio.Task | None = None

    async def run(self) -> None:
        try:
            await super().run()
        finally:
            if self.worker:
                self.worker.cancel()
                await asyncio.gather(self.worker, return_exceptions=True)

    async def handle_event(self, event: Event) -> bool:
        if Describe.is_type(event.type):
            await self.write_event(info_event(await self.engine.voices()))
            return True
        if Synthesize.is_type(event.type):
            if self.worker and not self.worker.done():
                await self.write_event(Error(text="synthesis already active", code="busy").event())
                return True
            request = Synthesize.from_event(event)
            voice = request.voice.name if request.voice else ""
            self._begin(voice)
            assert self.commands is not None
            await self.commands.put({"type": "text", "text": request.text})
            await self.commands.put({"type": "end"})
            return True
        if SynthesizeStart.is_type(event.type):
            if self.worker and not self.worker.done():
                await self.write_event(Error(text="synthesis already active", code="busy").event())
                return True
            data = event.data or {}
            voice = data.get("voice") or {}
            self._begin(voice.get("name", "") if isinstance(voice, dict) else "")
            return True
        if SynthesizeChunk.is_type(event.type):
            if self.commands is None:
                await self.write_event(Error(text="synthesize-start required", code="protocol").event())
                return True
            chunk = SynthesizeChunk.from_event(event)
            if len(chunk.text) > self.settings.max_text_chars:
                await self.write_event(Error(text="text exceeds limit", code="protocol").event())
                return True
            await self.commands.put({"type": "text", "text": chunk.text})
            return True
        if SynthesizeStop.is_type(event.type):
            if self.commands is not None:
                await self.commands.put({"type": "end"})
            return True
        return True

    def _begin(self, voice: str) -> None:
        self.commands = asyncio.Queue(maxsize=32)
        self.worker = asyncio.create_task(self._speak(voice))

    async def _speak(self, voice: str) -> None:
        assert self.commands is not None
        elapsed_bytes = 0
        audio_started = False
        begun = time.monotonic()
        try:
            async with asyncio.timeout(self.settings.max_session_seconds), self.engine.admission:
                async with self.engine.session() as backend:
                    self.engine.metrics.requests += 1
                    await backend.send({"type": "start",
                                        "voice_id": "" if voice == "breeze-design" else (voice or self.settings.default_voice),
                                        "instruction": self.settings.default_instruction})

                    async def pump() -> None:
                        assert self.commands is not None
                        while True:
                            command = await self.commands.get()
                            await backend.send(command)
                            if command["type"] == "end":
                                return

                    pump_task = asyncio.create_task(pump())
                    try:
                        async for kind, payload in backend.events():
                            if kind == "audio":
                                data = payload
                                assert isinstance(data, bytes)
                                if not audio_started:
                                    self.engine.metrics.first_audio_seconds.append(time.monotonic() - begun)
                                    await self.write_event(AudioStart(rate=24000, width=2, channels=1).event())
                                    audio_started = True
                                timestamp = math.floor(elapsed_bytes * 1000 / 48000)
                                await self.write_event(AudioChunk(rate=24000, width=2, channels=1,
                                                                  audio=data, timestamp=timestamp).event())
                                elapsed_bytes += len(data)
                                self.engine.metrics.audio_bytes += len(data)
                            elif isinstance(payload, dict) and payload.get("type") == "error":
                                raise RuntimeError(str(payload.get("message", "backend error")))
                        if not audio_started:
                            await self.write_event(AudioStart(rate=24000, width=2, channels=1).event())
                        await self.write_event(AudioStop(timestamp=math.floor(elapsed_bytes * 1000 / 48000)).event())
                        await self.write_event(SynthesizeStopped().event())
                    finally:
                        pump_task.cancel()
                        await asyncio.gather(pump_task, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except (Busy, OSError, RuntimeError, ValueError, ProtocolError,
                aiohttp.ClientError, TimeoutError) as exc:
            self.engine.metrics.failures += 1
            if not self.writer.is_closing():
                await self.write_event(Error(text=str(exc)[:160], code="breeze_error").event())
        finally:
            self.commands = None


async def start_wyoming(engine: Engine, settings: Settings) -> AsyncTcpServer:
    server = AsyncTcpServer(settings.wyoming_host, settings.wyoming_port)
    await server.start(lambda reader, writer: Handler(reader, writer, engine, settings))
    return server
