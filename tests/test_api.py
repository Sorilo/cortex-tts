import asyncio
import json
import wave
from pathlib import Path
from runpy import run_path
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web

from cortex_tts.api import make_app
from cortex_tts.config import Settings
from cortex_tts.engine import Engine
from cortex_tts.main import warm_backend, watch_backend
from cortex_tts.wyoming_adapter import start_wyoming
from wyoming.client import AsyncTcpClient
from wyoming.info import Describe, Info
from wyoming.tts import Synthesize, SynthesizeStart, SynthesizeChunk, SynthesizeStop, SynthesizeStopped
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error

stream_client = run_path(str(Path(__file__).resolve().parents[1] /
                             "scripts/stream_client.py"))
run_stream_client = stream_client["run"]


def test_playback_fill_level_simulation():
    packets = [(0.2, 0.32), (0.7, 0.4), (1.1, 0.8)]
    first_packet = stream_client["simulate_playback"](packets, 0, 2.0)
    buffered = stream_client["simulate_playback"](packets, 0.64, 2.0)
    assert first_packet["playback_start_seconds"] == 0.2
    assert first_packet["underruns"] == 1
    assert first_packet["underrun_seconds"] == pytest.approx(0.18)
    assert buffered["playback_start_seconds"] == 0.7
    assert buffered["underruns"] == 0


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
                    elif data["type"] == "instruction":
                        await ws.send_json({"type": "instruction_set"})
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
async def test_stream_client_receives_audio_before_later_text(services, monkeypatch):
    base, done_gate, _, _ = services
    done_gate.set()
    monkeypatch.setenv("CORTEX_TTS_TOKEN", "secret")
    args = SimpleNamespace(url=base.replace("http://", "ws://") + "/v1/speech/stream",
                           voice="", instruction="Speak clearly.",
                           text=["First phrase.", "Second phrase."], output=None,
                           cancel_after_audio_bytes=0, piece_delay_ms=100,
                           flush_each=False, timeout=2)
    result = await asyncio.wait_for(run_stream_client(args), 2)
    assert result["complete"] and result["bytes"] == 400
    assert result["first_audio_before_last_text"]
    assert result["first_audio_before_end"]
    assert result["ideal_zero_buffer_underruns"] == 1
    assert result["ideal_zero_buffer_underrun_seconds"] > 0.05
    assert result["largest_chunk_gap_seconds"] > 0.05


@pytest.mark.asyncio
async def test_stream_client_acknowledges_mid_session_instruction(services, monkeypatch):
    base, done_gate, _, _ = services
    done_gate.set()
    monkeypatch.setenv("CORTEX_TTS_TOKEN", "secret")
    args = SimpleNamespace(url=base.replace("http://", "ws://") + "/v1/speech/stream",
                           voice="", instruction="Speak clearly.",
                           instruction_after_first="Speak softly.",
                           text=["First phrase.", "Second phrase."], output=None,
                           cancel_after_audio_bytes=0, piece_delay_ms=100,
                           flush_each=False, timeout=2)
    result = await asyncio.wait_for(run_stream_client(args), 2)
    assert result["complete"] and result["bytes"] == 400
    assert result["instruction_set_events"] == 1
    assert result["instruction_set_seconds"] is not None
    assert result["first_audio_before_last_text"]


@pytest.mark.asyncio
async def test_stream_client_instruction_update_requires_later_text():
    with pytest.raises(ValueError, match="at least two text pieces"):
        await run_stream_client(SimpleNamespace(text=["Only one."],
                                                instruction_after_first="Speak softly."))


@pytest.mark.asyncio
async def test_stream_client_writes_received_pcm_to_wav(services, monkeypatch, tmp_path):
    base, done_gate, _, _ = services
    done_gate.set()
    monkeypatch.setenv("CORTEX_TTS_TOKEN", "secret")
    output = tmp_path / "speech.wav"
    args = SimpleNamespace(url=base.replace("http://", "ws://") + "/v1/speech/stream",
                           voice="", instruction="Speak clearly.", text=["Hello."],
                           output=str(output), cancel_after_audio_bytes=0,
                           piece_delay_ms=0, flush_each=False, timeout=2)
    result = await asyncio.wait_for(run_stream_client(args), 2)
    with wave.open(str(output), "rb") as saved:
        assert saved.getnchannels() == 1
        assert saved.getframerate() == 24000
        assert saved.readframes(saved.getnframes()) == b"\x01\x00" * 100
    assert result["complete"] and result["bytes"] == 200


@pytest.mark.asyncio
async def test_preexisting_playback_cancel_suppresses_pcm_callback(services, monkeypatch):
    base, done_gate, _, engine = services
    monkeypatch.setenv("CORTEX_TTS_TOKEN", "secret")
    cancel_event = asyncio.Event()
    cancel_event.set()
    packets = []

    async def on_audio(pcm):
        packets.append(pcm)

    args = SimpleNamespace(url=base.replace("http://", "ws://") + "/v1/speech/stream",
                           voice="", instruction="Speak clearly.", text=["Hello."],
                           output=None, cancel_after_audio_bytes=0,
                           piece_delay_ms=0, flush_each=False, timeout=2)
    result = await asyncio.wait_for(run_stream_client(
        args, on_audio=on_audio, cancel_event=cancel_event,
    ), 2)
    assert packets == []
    assert not done_gate.is_set()
    assert result["complete"] is False
    assert result["cancel_ack_seconds"] is not None
    assert engine.metrics.cancelled == 1


@pytest.mark.asyncio
async def test_core_authorized_turn_streams_through_wrapper(services, monkeypatch):
    base, done_gate, _, engine = services
    monkeypatch.setenv("CORTEX_TTS_TOKEN", "secret")
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    with monkeypatch.context() as path_context:
        path_context.syspath_prepend(str(scripts))
        from core_turn_client import synthesize_core_turn

    turn_id = "vt_" + "a" * 32

    async def core_result(request):
        assert request.headers["Authorization"] == "Bearer core-test-token"
        return web.json_response({"audio_turn_id": turn_id, "action_id": "act_test",
                                  "state": "succeeded", "speech_text": "Authorized speech."})

    app = web.Application()
    app.add_routes([web.get("/v1/voice/device/turns/{turn_id}", core_result)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    packets = []
    first_packet = asyncio.Event()

    async def on_audio(pcm):
        packets.append(pcm)
        first_packet.set()

    task = None
    try:
        core_url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        task = asyncio.create_task(synthesize_core_turn(
            core_url, turn_id, "core-test-token",
            tts_url=base.replace("http://", "ws://") + "/v1/speech/stream",
            on_audio=on_audio,
        ))
        await asyncio.wait_for(first_packet.wait(), 2)
        assert packets == [b"\x01\x00" * 100]
        assert not task.done()
        done_gate.set()
        result = await asyncio.wait_for(task, 2)
        assert result["core_audio_turn_id"] == turn_id
        assert result["core_action_id"] == "act_test"
        assert result["tts"]["complete"] and result["tts"]["bytes"] == 200
        assert engine.metrics.requests == 1
    finally:
        done_gate.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await runner.cleanup()


@pytest.mark.asyncio
async def test_core_turn_playback_cancel_stops_pcm_without_interrupting_core(
    services, monkeypatch,
):
    base, done_gate, _, engine = services
    monkeypatch.setenv("CORTEX_TTS_TOKEN", "secret")
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    with monkeypatch.context() as path_context:
        path_context.syspath_prepend(str(scripts))
        from core_turn_client import synthesize_core_turn

    turn_id = "vt_" + "b" * 32
    core_requests = []

    async def core_result(request):
        core_requests.append((request.method, request.path))
        assert request.headers["Authorization"] == "Bearer core-test-token"
        return web.json_response({"audio_turn_id": turn_id, "action_id": "act_cancel_test",
                                  "state": "succeeded", "speech_text": "Authorized speech."})

    app = web.Application()
    app.add_routes([web.get("/v1/voice/device/turns/{turn_id}", core_result)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    cancel_event = asyncio.Event()
    packets = []

    async def on_audio(pcm):
        packets.append(pcm)
        cancel_event.set()

    try:
        core_url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        result = await asyncio.wait_for(synthesize_core_turn(
            core_url, turn_id, "core-test-token",
            tts_url=base.replace("http://", "ws://") + "/v1/speech/stream",
            on_audio=on_audio, cancel_event=cancel_event,
        ), 2)
        assert packets == [b"\x01\x00" * 100]
        assert not done_gate.is_set()
        assert result["tts"]["complete"] is False
        assert result["tts"]["cancel_ack_seconds"] is not None
        assert result["tts"]["audio_bytes_after_cancel"] == 0
        assert engine.metrics.cancelled == 1
        assert core_requests == [("GET", f"/v1/voice/device/turns/{turn_id}")]
    finally:
        done_gate.set()
        await runner.cleanup()


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
async def test_wyoming_session_text_budget_aborts_and_recovers(services):
    _, done_gate, disconnected, engine = services
    wyoming = await start_wyoming(engine, Settings(**{**engine.settings.__dict__,
                                                       "wyoming_host": "127.0.0.1", "wyoming_port": 0,
                                                       "max_total_text_chars": 8}))
    try:
        port = wyoming._server.sockets[0].getsockname()[1]
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Synthesize(text="Too long.").event())
            error = await asyncio.wait_for(client.read_event(), 1)
            assert Error.is_type(error.type)
            assert Error.from_event(error).code == "protocol"
            assert not engine.admission.lock.locked()
            await client.write_event(SynthesizeStart().event())
            await client.write_event(SynthesizeChunk(text="Hello.").event())
            assert AudioStart.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert AudioChunk.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            await client.write_event(SynthesizeChunk(text="More.").event())
            error = await asyncio.wait_for(client.read_event(), 1)
            assert Error.is_type(error.type)
            assert Error.from_event(error).code == "protocol"
            await asyncio.wait_for(disconnected.wait(), 1)
            assert not engine.admission.lock.locked()
            await client.write_event(Synthesize(text="Hi.").event())
            assert AudioStart.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert AudioChunk.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            done_gate.set()
            assert AudioStop.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
    finally:
        await wyoming.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("late_kind", ["chunk", "stop"])
async def test_wyoming_rejects_input_after_stop_and_recovers(services, late_kind):
    _, done_gate, disconnected, engine = services
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
            late = SynthesizeChunk(text="Late.").event() if late_kind == "chunk" else SynthesizeStop().event()
            await client.write_event(late)
            error = await asyncio.wait_for(client.read_event(), 1)
            assert Error.is_type(error.type)
            assert Error.from_event(error).code == "protocol"
            await asyncio.wait_for(disconnected.wait(), 1)
            assert not engine.admission.lock.locked()
            await client.write_event(Synthesize(text="Fresh.").event())
            assert AudioStart.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert AudioChunk.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
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
async def test_wyoming_backend_drop_reports_error_and_recovers(services):
    _, done_gate, disconnected, engine = services
    wyoming = await start_wyoming(engine, Settings(**{**engine.settings.__dict__,
                                                       "wyoming_host": "127.0.0.1", "wyoming_port": 0}))
    try:
        port = wyoming._server.sockets[0].getsockname()[1]
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Synthesize(text="backend-drop").event())
            event = await asyncio.wait_for(client.read_event(), 1)
            assert Error.is_type(event.type)
            assert Error.from_event(event).code == "breeze_error"
        await asyncio.wait_for(disconnected.wait(), 1)
        engine.warm_ready = True  # The fake backend is immediately available again.
        async with AsyncTcpClient("127.0.0.1", port) as client:
            await client.write_event(Synthesize(text="Recovered.").event())
            assert AudioStart.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            assert AudioChunk.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
            done_gate.set()
            assert AudioStop.is_type((await asyncio.wait_for(client.read_event(), 1)).type)
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
    base, done_gate, disconnected, engine = services
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        async with client.ws_connect(base + "/v1/speech/stream") as ws:
            ready = await ws.receive_json()
            await ws.send_json({"type": "start"})
            await ws.send_json({"type": "text", "text": text})
            await ws.send_json({"type": "end"})
            assert (await ws.receive_json())["type"] == "started"
            error = await ws.receive_json()
            assert error["type"] == "error"
            assert error["code"] == "backend"
            assert error["turn_id"] == ready["turn_id"]
        await asyncio.wait_for(disconnected.wait(), 1)
        for _ in range(20):
            if not engine.admission.lock.locked():
                break
            await asyncio.sleep(0.01)
        assert not engine.admission.lock.locked()
        engine.warm_ready = True  # The fake backend is immediately available again.
        async with client.ws_connect(base + "/v1/speech/stream") as next_ws:
            assert (await next_ws.receive_json())["type"] == "ready"
            await next_ws.send_json({"type": "start"})
            await next_ws.send_json({"type": "text", "text": "Recovered."})
            await next_ws.send_json({"type": "end"})
            assert (await next_ws.receive_json())["type"] == "started"
            assert (await next_ws.receive()).type == aiohttp.WSMsgType.BINARY
            done_gate.set()
            assert (await next_ws.receive_json())["type"] == "done"


@pytest.mark.asyncio
async def test_backend_recovery_warmup_gates_readiness_and_new_turns(services):
    base, done_gate, _, engine = services
    watcher = asyncio.create_task(watch_backend(engine, engine.settings, poll_seconds=0.01))
    try:
        async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
            async with client.ws_connect(base + "/v1/speech/stream") as ws:
                assert (await ws.receive_json())["type"] == "ready"
                await ws.send_json({"type": "start"})
                await ws.send_json({"type": "text", "text": "backend-drop"})
                await ws.send_json({"type": "end"})
                assert (await ws.receive_json())["type"] == "started"
                assert (await ws.receive_json())["code"] == "backend"
            async with client.get(base + "/readyz") as response:
                assert response.status == 503
            async with client.ws_connect(base + "/v1/speech/stream") as ws:
                event = await ws.receive_json()
                assert event["type"] == "error" and event["code"] == "backend"
                assert event["message"] == "backend warming" and event["turn_id"]
            done_gate.set()
            for _ in range(100):
                async with client.get(base + "/readyz") as response:
                    if response.status == 200:
                        break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("backend warmup did not restore readiness")
            async with client.ws_connect(base + "/v1/speech/stream") as ws:
                assert (await ws.receive_json())["type"] == "ready"
                await ws.send_json({"type": "start"})
                await ws.send_json({"type": "text", "text": "Recovered."})
                await ws.send_json({"type": "end"})
                assert (await ws.receive_json())["type"] == "started"
                assert (await ws.receive()).type == aiohttp.WSMsgType.BINARY
                assert (await ws.receive_json())["type"] == "done"
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


@pytest.mark.asyncio
async def test_cortex_session_text_budget_is_terminal_and_recovers(services):
    base, done_gate, disconnected, engine = services
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        async with client.ws_connect(base + "/v1/speech/stream") as ws:
            ready = await ws.receive_json()
            await ws.send_json({"type": "start"})
            for _ in range(7):
                await ws.send_json({"type": "text", "text": "x" * 2000})
            while True:
                event = await asyncio.wait_for(ws.receive(), 2)
                if event.type == aiohttp.WSMsgType.TEXT:
                    payload = json.loads(event.data)
                    if payload["type"] == "error":
                        assert payload["code"] == "protocol"
                        assert payload["turn_id"] == ready["turn_id"]
                        break
                else:
                    assert event.type == aiohttp.WSMsgType.BINARY
            assert (await ws.receive()).type == aiohttp.WSMsgType.CLOSE
        await asyncio.wait_for(disconnected.wait(), 1)
        assert not engine.admission.lock.locked()
        async with client.ws_connect(base + "/v1/speech/stream") as next_ws:
            assert (await next_ws.receive_json())["type"] == "ready"
            await next_ws.send_json({"type": "start"})
            await next_ws.send_json({"type": "text", "text": "Fresh."})
            await next_ws.send_json({"type": "end"})
            assert (await next_ws.receive_json())["type"] == "started"
            assert (await next_ws.receive()).type == aiohttp.WSMsgType.BINARY
            done_gate.set()
            assert (await next_ws.receive_json())["type"] == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["not-json", '{"type":"text","text":"too early"}',
                                      '{"type":"unknown"}'])
async def test_malformed_client_stream_has_one_protocol_error_and_recovers(services, payload):
    base, done_gate, disconnected, engine = services
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        async with client.ws_connect(base + "/v1/speech/stream") as ws:
            ready = await ws.receive_json()
            await ws.send_str(payload)
            event = await ws.receive_json()
            assert event["type"] == "error" and event["code"] == "protocol"
            assert event["turn_id"] == ready["turn_id"]
            assert (await ws.receive()).type == aiohttp.WSMsgType.CLOSE
        await asyncio.wait_for(disconnected.wait(), 1)
        assert not engine.admission.lock.locked()
        assert engine.metrics.failures == 1
        async with client.ws_connect(base + "/v1/speech/stream") as next_ws:
            assert (await next_ws.receive_json())["type"] == "ready"
            await next_ws.send_json({"type": "start"})
            await next_ws.send_json({"type": "text", "text": "Recovered."})
            await next_ws.send_json({"type": "end"})
            assert (await next_ws.receive_json())["type"] == "started"
            assert (await next_ws.receive()).type == aiohttp.WSMsgType.BINARY
            done_gate.set()
            assert (await next_ws.receive_json())["type"] == "done"


@pytest.mark.asyncio
async def test_busy_stream_is_rejected_without_interrupting_active_audio(services):
    base, _, disconnected, engine = services
    engine.admission.limit = 0
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        async with client.ws_connect(base + "/v1/speech/stream") as active:
            assert (await active.receive_json())["type"] == "ready"
            await active.send_json({"type": "start"})
            await active.send_json({"type": "text", "text": "Continue."})
            assert (await active.receive_json())["type"] == "started"
            assert (await active.receive()).type == aiohttp.WSMsgType.BINARY
            async with client.ws_connect(base + "/v1/speech/stream") as busy:
                response = await busy.receive_json()
                assert response["type"] == "error" and response["code"] == "busy"
            assert engine.admission.lock.locked()
        await asyncio.wait_for(disconnected.wait(), 1)
        assert not engine.admission.lock.locked()


@pytest.mark.asyncio
async def test_bounded_waiters_are_served_in_order(services):
    base, _, _, engine = services
    engine.admission.limit = 2
    async with aiohttp.ClientSession(headers={"Authorization": "Bearer secret"}) as client:
        occupied = await client.ws_connect(base + "/v1/speech/stream")
        first = second = None
        try:
            assert (await occupied.receive_json())["type"] == "ready"
            first = await client.ws_connect(base + "/v1/speech/stream")
            second = await client.ws_connect(base + "/v1/speech/stream")
            for _ in range(50):
                if engine.admission.waiters == 2:
                    break
                await asyncio.sleep(0.01)
            assert engine.admission.waiters == 2
            async with client.ws_connect(base + "/v1/speech/stream") as overflow:
                event = await overflow.receive_json()
                assert event["type"] == "error" and event["code"] == "busy"
            await occupied.close()
            assert (await asyncio.wait_for(first.receive_json(), 1))["type"] == "ready"
            await first.close()
            assert (await asyncio.wait_for(second.receive_json(), 1))["type"] == "ready"
        finally:
            await occupied.close()
            if first:
                await first.close()
            if second:
                await second.close()
