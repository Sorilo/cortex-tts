import asyncio
import json

import aiohttp
import pytest
from aiohttp import web

from cortex_tts.api import make_app
from cortex_tts.config import Settings
from cortex_tts.engine import Engine
from cortex_tts.main import warm_backend
from cortex_tts.wyoming_adapter import start_wyoming
from wyoming.client import AsyncTcpClient
from wyoming.info import Describe, Info
from wyoming.tts import Synthesize, SynthesizeStart, SynthesizeChunk, SynthesizeStop, SynthesizeStopped
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error


@pytest.fixture
async def services():
    disconnected = asyncio.Event()
    done_gate = asyncio.Event()

    async def backend_socket(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "ready", "sample_rate": 24000})
        complete_task = None

        async def finish():
            await done_gate.wait()
            await ws.send_json({"type": "done"})

        try:
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(message.data)
                    if data["type"] == "start":
                        await ws.send_json({"type": "started"})
                    elif data["type"] == "text":
                        if data["text"] == "backend-error":
                            await ws.send_json({"type": "error", "message": "synthetic backend failure"})
                            break
                        if data["text"] == "backend-drop":
                            await ws.close()
                            break
                        await ws.send_bytes(b"\x01\x00" * 100)
                    elif data["type"] == "end":
                        complete_task = asyncio.create_task(finish())
                    elif data["type"] == "cancel":
                        if complete_task:
                            complete_task.cancel()
                        await ws.send_json({"type": "cancelled"})
        finally:
            if complete_task:
                complete_task.cancel()
                await asyncio.gather(complete_task, return_exceptions=True)
            disconnected.set()
        return ws

    async def health(_):
        return web.json_response({"status": "ok"})

    async def voices(_):
        return web.json_response([{"id": "warm", "saved": True}])

    async def add_voice(request):
        reader = await request.multipart()
        fields = {}
        async for part in reader:
            fields[part.name] = await part.read()
        assert fields["name"] == b"test_voice"
        assert fields["ref_text"] == b"hello"
        assert fields["ref_audio"] == b"RIFFsynthetic"
        return web.json_response({"id": "test_voice"})

    backend = web.Application()
    backend.add_routes([web.get("/ws", backend_socket), web.get("/health", health),
                        web.get("/v1/voices", voices), web.post("/v1/voices", add_voice)])
    backend_runner = web.AppRunner(backend)
    await backend_runner.setup()
    backend_site = web.TCPSite(backend_runner, "127.0.0.1", 0)
    await backend_site.start()
    backend_port = backend_site._server.sockets[0].getsockname()[1]

    settings = Settings(backend_http=f"http://127.0.0.1:{backend_port}",
                        backend_ws=f"ws://127.0.0.1:{backend_port}/ws",
                        api_token="secret", max_session_seconds=5)
    engine = Engine(settings)
    await engine.start()
    wrapper_runner = web.AppRunner(make_app(engine, settings))
    await wrapper_runner.setup()
    wrapper_site = web.TCPSite(wrapper_runner, "127.0.0.1", 0)
    await wrapper_site.start()
    wrapper_port = wrapper_site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{wrapper_port}", done_gate, disconnected, engine
    done_gate.set()
    await wrapper_runner.cleanup()
    await engine.close()
    await backend_runner.cleanup()


@pytest.mark.asyncio
async def test_startup_warmup_finishes_before_accepting_clients(services):
    _, done_gate, disconnected, engine = services
    done_gate.set()
    await asyncio.wait_for(warm_backend(engine, engine.settings), 1)
    await asyncio.wait_for(disconnected.wait(), 1)
    assert engine.metrics.requests == 0


@pytest.mark.asyncio
async def test_stream_yields_audio_before_completion(services):
    base, done_gate, _, engine = services
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        async with client.ws_connect(base + "/v1/speech/stream") as ws:
            ready = await ws.receive_json()
            assert ready["type"] == "ready"
            turn_id = ready["turn_id"]
            await ws.send_json({"type": "start", "voice_id": "warm"})
            await ws.send_json({"type": "text", "text": "Hello."})
            await ws.send_json({"type": "end"})
            assert (await ws.receive_json())["type"] == "started"
            audio = await ws.receive(timeout=1)
            assert audio.type == aiohttp.WSMsgType.BINARY
            assert len(audio.data) == 200
            assert not done_gate.is_set()
            done_gate.set()
            complete = await ws.receive_json()
            assert complete == {"type": "done", "turn_id": turn_id}
    assert engine.metrics.audio_bytes == 200


@pytest.mark.asyncio
async def test_auth_and_voice_discovery(services):
    base, _, _, _ = services
    async with aiohttp.ClientSession() as client:
        assert (await client.get(base + "/v1/voices")).status == 401
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        async with client.get(base + "/v1/voices") as response:
            assert await response.json() == {"voices": ["warm"]}


@pytest.mark.asyncio
async def test_authenticated_voice_upload(services):
    base, _, _, _ = services
    data = aiohttp.FormData()
    data.add_field("name", "test_voice")
    data.add_field("ref_text", "hello")
    data.add_field("ref_audio", b"RIFFsynthetic", filename="voice.wav", content_type="audio/wav")
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        async with client.post(base + "/v1/voices", data=data) as response:
            assert response.status == 200
            assert (await response.json())["id"] == "test_voice"


@pytest.mark.asyncio
async def test_wyoming_progressive_audio(services):
    _, done_gate, _, engine = services
    wyoming = await start_wyoming(engine, Settings(**{**engine.settings.__dict__,
                                                       "wyoming_host": "127.0.0.1", "wyoming_port": 0}))
    try:
        port = wyoming._server.sockets[0].getsockname()[1]
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Describe().event())
            assert Info.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            await client.write_event(Synthesize(text="Hello.").event())
            assert AudioStart.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert AudioChunk.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert not done_gate.is_set()
            done_gate.set()
            assert AudioStop.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert SynthesizeStopped.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
    finally:
        await wyoming.stop()


@pytest.mark.asyncio
async def test_wyoming_incremental_text_before_stop(services):
    _, done_gate, _, engine = services
    wyoming = await start_wyoming(engine, Settings(**{**engine.settings.__dict__,
                                                       "wyoming_host": "127.0.0.1", "wyoming_port": 0}))
    try:
        port = wyoming._server.sockets[0].getsockname()[1]
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(SynthesizeStart().event())
            await client.write_event(SynthesizeChunk(text="Hello.").event())
            assert AudioStart.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert AudioChunk.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            await client.write_event(SynthesizeStop().event())
            done_gate.set()
            assert AudioStop.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert SynthesizeStopped.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
    finally:
        await wyoming.stop()


@pytest.mark.asyncio
async def test_wyoming_stream_without_stop_times_out_and_releases_backend(services):
    _, _, disconnected, engine = services
    wyoming = await start_wyoming(engine, Settings(**{**engine.settings.__dict__,
                                                       "wyoming_host": "127.0.0.1", "wyoming_port": 0,
                                                       "max_session_seconds": 0.05}))
    try:
        port = wyoming._server.sockets[0].getsockname()[1]
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(SynthesizeStart().event())
            await client.write_event(SynthesizeChunk(text="Hello.").event())
            assert AudioStart.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert AudioChunk.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert Error.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
        await asyncio.wait_for(disconnected.wait(), 1)
        assert not engine.admission.lock.locked()
    finally:
        await wyoming.stop()


@pytest.mark.asyncio
async def test_wyoming_disconnect_aborts_backend(services):
    _, done_gate, disconnected, engine = services
    wyoming = await start_wyoming(engine, Settings(**{**engine.settings.__dict__,
                                                       "wyoming_host": "127.0.0.1", "wyoming_port": 0}))
    try:
        port = wyoming._server.sockets[0].getsockname()[1]
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Synthesize(text="Stop before completion.").event())
            assert AudioStart.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert AudioChunk.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
        await asyncio.wait_for(disconnected.wait(), 1)
        for _ in range(20):
            if not engine.admission.lock.locked():
                break
            await asyncio.sleep(0.01)
        assert not engine.admission.lock.locked()
        assert not done_gate.is_set()
    finally:
        await wyoming.stop()


@pytest.mark.asyncio
async def test_disconnect_closes_backend_before_done(services):
    base, done_gate, disconnected, _ = services
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        async with client.ws_connect(base + "/v1/speech/stream") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "start"})
            await ws.send_json({"type": "text", "text": "Interrupt me."})
            await ws.send_json({"type": "end"})
            await ws.receive_json()
            await ws.receive()
            await ws.close()
        await asyncio.wait_for(disconnected.wait(), 1)
        assert not done_gate.is_set()


@pytest.mark.asyncio
async def test_cancel_discards_pending_audio_and_frees_slot(services):
    base, done_gate, disconnected, engine = services
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        async with client.ws_connect(base + "/v1/speech/stream") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "start"})
            await ws.send_json({"type": "text", "text": "Stop."})
            await ws.send_json({"type": "end"})
            await ws.receive_json()
            assert (await ws.receive()).type == aiohttp.WSMsgType.BINARY
            await ws.send_json({"type": "cancel"})
            assert (await ws.receive_json())["type"] == "cancelled"
            assert (await ws.receive()).type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}
            await ws.close()
        await asyncio.wait_for(disconnected.wait(), 1)
        for _ in range(20):
            if not engine.admission.lock.locked():
                break
            await asyncio.sleep(0.01)
        assert not engine.admission.lock.locked()
        assert engine.metrics.cancelled == 1
        assert engine.metrics.failures == 0
        assert not done_gate.is_set()
        async with client.ws_connect(base + "/v1/speech/stream") as next_ws:
            assert (await next_ws.receive_json())["type"] == "ready"
            await next_ws.send_json({"type": "start"})
            await next_ws.send_json({"type": "text", "text": "Fresh turn."})
            await next_ws.send_json({"type": "end"})
            assert (await next_ws.receive_json())["type"] == "started"
            assert (await next_ws.receive()).type == aiohttp.WSMsgType.BINARY
            done_gate.set()
            assert (await next_ws.receive_json())["type"] == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["backend-error", "backend-drop"])
async def test_backend_failure_is_terminal_and_releases_slot(services, text):
    base, _, disconnected, engine = services
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        async with client.ws_connect(base + "/v1/speech/stream") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "start"})
            await ws.send_json({"type": "text", "text": text})
            await ws.send_json({"type": "end"})
            assert (await ws.receive_json())["type"] == "started"
            assert (await ws.receive_json())["type"] == "error"
        await asyncio.wait_for(disconnected.wait(), 1)
        for _ in range(20):
            if not engine.admission.lock.locked():
                break
            await asyncio.sleep(0.01)
        assert not engine.admission.lock.locked()
