"""Cortex-facing streaming transport. It has no action or identity authority."""
from __future__ import annotations

import aiohttp
import asyncio
import hmac
import json
import time
import uuid

from aiohttp import WSMsgType, web

from .config import Settings
from .engine import Busy, Engine, ProtocolError, validate_client_message


def make_app(engine: Engine, settings: Settings) -> web.Application:
    app = web.Application(client_max_size=12 * 1024 * 1024)

    def authorized(request: web.Request) -> bool:
        return bool(settings.api_token) and hmac.compare_digest(
            request.headers.get("Authorization", ""), "Bearer " + settings.api_token
        )

    async def live(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def ready(_: web.Request) -> web.Response:
        healthy = await engine.health()
        return web.json_response({"ready": healthy}, status=200 if healthy else 503)

    async def metrics(request: web.Request) -> web.Response:
        if not authorized(request):
            raise web.HTTPUnauthorized()
        return web.json_response(engine.metrics.snapshot(engine.admission))

    async def voices(request: web.Request) -> web.Response:
        if not authorized(request):
            raise web.HTTPUnauthorized()
        return web.json_response({"voices": await engine.voices()})

    async def add_voice(request: web.Request) -> web.Response:
        if not authorized(request):
            raise web.HTTPUnauthorized()
        reader = await request.multipart()
        fields: dict[str, str | bytes] = {}
        async for part in reader:
            if part.name not in {"name", "ref_text", "ref_audio"}:
                raise web.HTTPBadRequest(text="unknown voice field")
            if part.name == "ref_audio":
                data = bytes(await part.read(decode=False))
                if len(data) > 10 * 1024 * 1024:
                    raise web.HTTPRequestEntityTooLarge(max_size=10 * 1024 * 1024, actual_size=len(data))
                fields[part.name] = data
            else:
                fields[part.name] = await part.text()
        name, ref_text, audio = fields.get("name"), fields.get("ref_text"), fields.get("ref_audio")
        if not isinstance(name, str) or not name or len(name) > 64 or not all(c.isalnum() or c in "_-" for c in name):
            raise web.HTTPBadRequest(text="invalid voice name")
        if not isinstance(ref_text, str) or not ref_text or len(ref_text) > 2000 or not isinstance(audio, bytes) or not audio:
            raise web.HTTPBadRequest(text="reference audio and exact transcript required")
        assert engine.client is not None
        from aiohttp import FormData

        form = FormData()
        form.add_field("name", name)
        form.add_field("ref_text", ref_text)
        form.add_field("ref_audio", audio, filename="reference.wav", content_type="audio/wav")
        async with engine.client.post(settings.backend_http + "/v1/voices", data=form, timeout=90) as response:
            body = await response.text()
            return web.Response(status=response.status, text=body, content_type="application/json")

    async def speech(request: web.Request) -> web.StreamResponse:
        if not authorized(request):
            raise web.HTTPUnauthorized()
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=64 * 1024)
        await ws.prepare(request)
        turn_id = str(uuid.uuid4())
        started = False
        finished = False
        input_ended = False
        first_audio = False
        begun = time.monotonic()
        send_task: asyncio.Task | None = None
        try:
            async with engine.admission:
                async with engine.session() as backend:
                    engine.metrics.requests += 1
                    await ws.send_json({"type": "ready", "version": 1, "turn_id": turn_id,
                                        "sample_rate": 24000, "format": "pcm_s16le", "channels": 1})

                    async def forward_input() -> None:
                        nonlocal started, input_ended
                        async for msg in ws:
                            if msg.type != WSMsgType.TEXT:
                                if msg.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                                    break
                                raise ProtocolError("binary client input unsupported")
                            try:
                                value = validate_client_message(json.loads(msg.data), settings, started)
                                if input_ended and value["type"] != "cancel":
                                    raise ProtocolError("only cancel is allowed after end")
                            except (ValueError, ProtocolError) as exc:
                                await ws.send_json({"type": "error", "message": str(exc), "turn_id": turn_id})
                                break
                            if value["type"] == "start":
                                started = True
                                value = {**value}
                                value.setdefault("instruction", settings.default_instruction)
                                if settings.default_voice:
                                    value.setdefault("voice_id", settings.default_voice)
                            await backend.send(value)
                            if value["type"] == "end":
                                input_ended = True
                        raise ConnectionError("client disconnected")

                    send_task = asyncio.create_task(forward_input())
                    iterator = backend.events().__aiter__()
                    deadline = begun + settings.max_session_seconds
                    while not finished:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("session time limit")
                        next_event = asyncio.create_task(iterator.__anext__())
                        pending: set[asyncio.Task] = {next_event, send_task}
                        done, _ = await asyncio.wait(pending, timeout=remaining,
                                                     return_when=asyncio.FIRST_COMPLETED)
                        if not done:
                            next_event.cancel()
                            await asyncio.gather(next_event, return_exceptions=True)
                            raise TimeoutError("session time limit")
                        if send_task in done:
                            exception = send_task.exception()
                            if exception:
                                next_event.cancel()
                                await asyncio.gather(next_event, return_exceptions=True)
                                raise exception
                        if next_event not in done:
                            try:
                                await asyncio.wait_for(next_event, remaining)
                            except TimeoutError:
                                raise TimeoutError("session time limit") from None
                        try:
                            kind, payload = next_event.result()
                        except StopAsyncIteration:
                            break
                        if kind == "audio":
                            data = payload
                            assert isinstance(data, bytes)
                            if not first_audio:
                                first_audio = True
                                engine.metrics.first_audio_seconds.append(time.monotonic() - begun)
                            engine.metrics.audio_bytes += len(data)
                            await ws.send_bytes(data)
                        else:
                            event = payload
                            assert isinstance(event, dict)
                            await ws.send_json({**event, "turn_id": turn_id})
                            if event["type"] == "cancelled":
                                engine.metrics.cancelled += 1
                            if event["type"] in {"done", "error", "cancelled"}:
                                finished = True
                                if event["type"] == "error":
                                    engine.metrics.failures += 1
                                break
        except Busy as exc:
            await ws.send_json({"type": "error", "code": "busy", "message": str(exc), "turn_id": turn_id})
        except (ProtocolError, OSError, TimeoutError, ConnectionError,
                ValueError, aiohttp.ClientError) as exc:
            engine.metrics.failures += 1
            if not ws.closed:
                await ws.send_json({"type": "error", "code": "backend", "message": str(exc), "turn_id": turn_id})
        finally:
            if send_task:
                send_task.cancel()
                await asyncio.gather(send_task, return_exceptions=True)
            if not ws.closed:
                await ws.close()
        return ws

    app.add_routes([
        web.get("/livez", live), web.get("/readyz", ready),
        web.get("/v1/metrics", metrics), web.get("/v1/voices", voices),
        web.post("/v1/voices", add_voice), web.get("/v1/speech/stream", speech),
    ])
    return app
