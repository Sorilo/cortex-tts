"""Core-result authority gate for the opt-in streaming example client."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core_turn_client  # noqa: E402


TURN_ID = "vt_" + "a" * 32


@pytest.fixture
async def core_server():
    state = {"responses": [], "requests": []}

    async def result(request):
        assert request.headers.get("Authorization") == "Bearer core-test-token"
        state["requests"].append(request.path)
        rows = state["responses"]
        return web.json_response(rows[min(len(state["requests"]) - 1, len(rows) - 1)])

    app = web.Application()
    app.router.add_get("/v1/voice/device/turns/{turn_id}", result)
    app.router.add_get("/v1/voice/turns/{turn_id}", result)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}", state
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_core_turn_client_waits_for_authoritative_speech(core_server, monkeypatch):
    base, state = core_server
    state["responses"] = [
        {"audio_turn_id": TURN_ID, "action_id": "act_1", "state": "admitted",
         "speech_text": None, "partial_transcript": "Do not say this."},
        {"audio_turn_id": TURN_ID, "action_id": "act_1", "state": "succeeded",
         "speech_text": "The lamp was on.", "model_output": "Do not say this either."},
    ]
    calls = []

    async def tts(args, *, on_audio=None, cancel_event=None):
        calls.append(args)
        assert on_audio is None
        assert cancel_event is None
        return {"turn_id": "tts-turn", "complete": True, "bytes": 4800}

    monkeypatch.setattr(core_turn_client, "run_stream_client", tts)
    result = await core_turn_client.synthesize_core_turn(
        base, TURN_ID, "core-test-token", tts_url="ws://127.0.0.1:18084/v1/speech/stream",
        poll_interval=0.001,
    )
    assert len(state["requests"]) == 2
    assert all(path.endswith(TURN_ID) for path in state["requests"])
    assert [call.text for call in calls] == [["The lamp was on."]]
    assert result == {"core_audio_turn_id": TURN_ID, "core_action_id": "act_1",
                      "core_state": "succeeded",
                      "tts": {"turn_id": "tts-turn", "complete": True, "bytes": 4800}}


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    {"audio_turn_id": TURN_ID, "action_id": "act_1", "state": "succeeded",
     "speech_text": None, "partial_transcript": "Untrusted."},
    {"audio_turn_id": "vt_" + "b" * 32, "action_id": "act_1", "state": "succeeded",
     "speech_text": "Wrong turn."},
    {"audio_turn_id": TURN_ID, "action_id": "", "state": "succeeded",
     "speech_text": "Unbound action."},
])
async def test_core_turn_client_rejects_untrusted_or_uncorrelated_result(
    core_server, monkeypatch, response,
):
    base, state = core_server
    state["responses"] = [response]

    async def unexpected_tts(_, *, on_audio=None, cancel_event=None):
        pytest.fail("TTS must not receive an untrusted Core result")

    monkeypatch.setattr(core_turn_client, "run_stream_client", unexpected_tts)
    with pytest.raises(RuntimeError):
        await core_turn_client.synthesize_core_turn(
            base, TURN_ID, "core-test-token", tts_url="ws://127.0.0.1:18084/v1/speech/stream",
        )


@pytest.mark.asyncio
async def test_approval_pending_speech_requires_opt_in(core_server, monkeypatch):
    base, state = core_server
    state["responses"] = [{"audio_turn_id": TURN_ID, "action_id": "act_1",
                           "state": "awaiting_approval",
                           "speech_text": "This action needs owner approval before it can run."}]
    calls = []

    async def tts(args, *, on_audio=None, cancel_event=None):
        calls.append(args.text)
        assert on_audio is None
        assert cancel_event is None
        return {"complete": True}

    monkeypatch.setattr(core_turn_client, "run_stream_client", tts)
    with pytest.raises(TimeoutError):
        await core_turn_client.synthesize_core_turn(
            base, TURN_ID, "core-test-token", tts_url="ws://127.0.0.1:18084/v1/speech/stream",
            core_timeout=0.02, poll_interval=0.005,
        )
    assert calls == []
    result = await core_turn_client.synthesize_core_turn(
        base, TURN_ID, "core-test-token", tts_url="ws://127.0.0.1:18084/v1/speech/stream",
        allow_approval_pending=True,
    )
    assert state["requests"][-1].startswith("/v1/voice/device/turns/")
    assert calls == [["This action needs owner approval before it can run."]]
    assert result["core_state"] == "awaiting_approval"


@pytest.mark.asyncio
async def test_core_turn_client_rejects_action_switch_while_polling(core_server, monkeypatch):
    base, state = core_server
    state["responses"] = [
        {"audio_turn_id": TURN_ID, "action_id": "act_1", "state": "admitted",
         "speech_text": None},
        {"audio_turn_id": TURN_ID, "action_id": "act_2", "state": "succeeded",
         "speech_text": "Wrong action."},
    ]

    async def unexpected_tts(_, *, on_audio=None, cancel_event=None):
        pytest.fail("TTS must not receive speech from a switched action")

    monkeypatch.setattr(core_turn_client, "run_stream_client", unexpected_tts)
    with pytest.raises(RuntimeError, match="action correlation changed"):
        await core_turn_client.synthesize_core_turn(
            base, TURN_ID, "core-test-token", tts_url="ws://127.0.0.1:18084/v1/speech/stream",
            poll_interval=0.001,
        )


@pytest.mark.asyncio
async def test_playback_cancel_before_core_poll_makes_no_request(core_server, monkeypatch):
    base, state = core_server
    cancel_event = asyncio.Event()
    cancel_event.set()

    async def unexpected_tts(_, *, on_audio=None, cancel_event=None):
        pytest.fail("TTS must not start for an abandoned playback turn")

    monkeypatch.setattr(core_turn_client, "run_stream_client", unexpected_tts)
    with pytest.raises(core_turn_client.PlaybackCancelled):
        await core_turn_client.synthesize_core_turn(
            base, TURN_ID, "core-test-token", tts_url="ws://127.0.0.1:18084/v1/speech/stream",
            cancel_event=cancel_event,
        )
    assert state["requests"] == []


@pytest.mark.asyncio
async def test_playback_cancel_interrupts_core_poll_interval(core_server, monkeypatch):
    base, state = core_server
    state["responses"] = [{"audio_turn_id": TURN_ID, "action_id": "act_pending",
                           "state": "admitted", "speech_text": None}]

    async def unexpected_tts(_, *, on_audio=None, cancel_event=None):
        pytest.fail("TTS must not start after playback was cancelled")

    monkeypatch.setattr(core_turn_client, "run_stream_client", unexpected_tts)
    cancel_event = asyncio.Event()
    task = asyncio.create_task(core_turn_client.synthesize_core_turn(
        base, TURN_ID, "core-test-token", tts_url="ws://127.0.0.1:18084/v1/speech/stream",
        poll_interval=5, cancel_event=cancel_event,
    ))
    try:
        async def first_get():
            while not state["requests"]:
                await asyncio.sleep(0.001)

        await asyncio.wait_for(first_get(), 1)
        cancel_event.set()
        with pytest.raises(core_turn_client.PlaybackCancelled):
            await asyncio.wait_for(task, 0.3)
        assert len(state["requests"]) == 1
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_playback_cancel_interrupts_pending_core_get(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    requests = []

    async def delayed_result(request):
        requests.append((request.method, request.path))
        started.set()
        await release.wait()
        return web.json_response({"audio_turn_id": TURN_ID, "action_id": "act_late",
                                  "state": "succeeded", "speech_text": "Stale speech."})

    app = web.Application()
    app.router.add_get("/v1/voice/device/turns/{turn_id}", delayed_result)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    async def unexpected_tts(_, *, on_audio=None, cancel_event=None):
        pytest.fail("TTS must not start after playback was cancelled")

    monkeypatch.setattr(core_turn_client, "run_stream_client", unexpected_tts)
    cancel_event = asyncio.Event()
    task = None
    try:
        base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        task = asyncio.create_task(core_turn_client.synthesize_core_turn(
            base, TURN_ID, "core-test-token", tts_url="ws://127.0.0.1:18084/v1/speech/stream",
            cancel_event=cancel_event,
        ))
        await asyncio.wait_for(started.wait(), 1)
        cancel_event.set()
        with pytest.raises(core_turn_client.PlaybackCancelled):
            await asyncio.wait_for(task, 0.3)
        assert requests == [("GET", f"/v1/voice/device/turns/{TURN_ID}")]
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await runner.cleanup()
