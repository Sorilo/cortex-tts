"""Core-result authority gate for the opt-in streaming example client."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import core_turn_client  # noqa: E402


TURN_ID = "vt_" + "a" * 32


@pytest.fixture
async def core_server():
    state = {"responses": [], "requests": [], "events": []}

    async def result(request):
        assert request.headers.get("Authorization") == "Bearer core-test-token"
        state["requests"].append(request.path)
        rows = state["responses"]
        return web.json_response(rows[min(len(state["requests"]) - 1, len(rows) - 1)])

    async def events(request):
        assert request.headers.get("Authorization") == "Bearer core-test-token"
        state["requests"].append(request.path)
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for delay, item in state["events"]:
            await asyncio.sleep(delay)
            try:
                await response.write(b"data: " + json.dumps(item).encode() + b"\n\n")
            except (ConnectionError, RuntimeError):
                break
        return response

    app = web.Application()
    app.router.add_get("/v1/voice/device/turns/{turn_id}", result)
    app.router.add_get("/v1/voice/turns/{turn_id}", result)
    app.router.add_get("/v1/voice/device/turns/{turn_id}/events", events)
    app.router.add_get("/v1/voice/turns/{turn_id}/events", events)
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


def wire_event(kind, number, **fields):
    return {"version": "1.0.0", "id": f"boot:{number}",
            "audio_turn_id": TURN_ID, "action_id": "act_" + "1" * 32,
            "type": kind, **fields}


@pytest.mark.asyncio
async def test_pcm_callback_requires_local_queue_clear():
    async def audio(_):
        pass

    with pytest.raises(ValueError, match="queue-clear"):
        await core_turn_client.synthesize_core_stream(
            "http://unused", TURN_ID, "token", tts_url="ws://unused", on_audio=audio)


@pytest.mark.asyncio
async def test_progress_pcm_is_preempted_by_authoritative_answer(core_server, monkeypatch):
    base, state = core_server
    state["events"] = [
        (0, wire_event("snapshot", 0, state="running", speech_text=None)),
        (0, wire_event("tool_activity", 1, activity="working", speech_text="secret")),
        (0, wire_event("progress_speech", 2, ordinal=1, speech_text="I'm checking that now.")),
        (0.03, wire_event("response_available", 3, state="succeeded",
                          speech_text="When I checked, the lamp was off.")),
        (0, wire_event("terminal", 4, state="succeeded")),
    ]
    calls = []
    forwarded = []
    clear_count = []
    progress_started = asyncio.Event()

    async def tts(args, *, on_audio, cancel_event):
        calls.append(args.text[0])
        assert args.output is None and args.collect_playback_packets is False
        await on_audio(b"\0\0")
        if "checking" in args.text[0]:
            progress_started.set()
            await cancel_event.wait()
            await on_audio(b"stale0")
            return {"complete": False, "cancelled": True}
        await asyncio.sleep(0.01)
        return {"complete": True, "first_audio_before_end": True}

    async def audio(packet):
        forwarded.append(packet)

    async def clear_audio():
        clear_count.append(True)

    monkeypatch.setattr(core_turn_client, "run_stream_client", tts)
    result = await core_turn_client.synthesize_core_stream(
        base, TURN_ID, "core-test-token", tts_url="ws://unused",
        on_audio=audio, on_clear_audio=clear_audio)
    assert progress_started.is_set()
    assert calls == ["I'm checking that now.", "When I checked, the lamp was off."]
    assert forwarded == [b"\0\0", b"\0\0"]  # stale packet was discarded
    assert len(clear_count) == 1
    assert result["core_state"] == "succeeded"
    assert result["timing"]["first_pcm_client_elapsed_ms"] is not None
    assert result["timing"]["basis"].endswith("not audible latency")


@pytest.mark.asyncio
async def test_stream_rejects_uncorrelated_or_unapproved_speech(core_server, monkeypatch):
    base, state = core_server
    state["events"] = [
        (0, wire_event("snapshot", 0, state="running", speech_text=None)),
        (0, wire_event("response_available", 1, state="succeeded",
                       speech_text="Untrusted", action_id="act_foreign")),
    ]

    async def unexpected_tts(*args, **kwargs):
        pytest.fail("uncorrelated Core event must not reach TTS")

    monkeypatch.setattr(core_turn_client, "run_stream_client", unexpected_tts)
    with pytest.raises(RuntimeError, match="correlation changed"):
        await core_turn_client.synthesize_core_stream(
            base, TURN_ID, "core-test-token", tts_url="ws://unused")


@pytest.mark.asyncio
async def test_stream_local_stop_does_not_interrupt_core_action(core_server, monkeypatch):
    base, state = core_server
    state["events"] = [(0, wire_event("snapshot", 0, state="running", speech_text=None)),
                       (1, wire_event("working", 1, state="running"))]
    cancel = asyncio.Event()

    async def unexpected_tts(*args, **kwargs):
        pytest.fail("no speakable event was emitted")

    monkeypatch.setattr(core_turn_client, "run_stream_client", unexpected_tts)
    task = asyncio.create_task(core_turn_client.synthesize_core_stream(
        base, TURN_ID, "core-test-token", tts_url="ws://unused", cancel_event=cancel))
    await asyncio.sleep(0.02)
    cancel.set()
    with pytest.raises(core_turn_client.PlaybackCancelled):
        await asyncio.wait_for(task, 0.3)
    assert state["requests"] == [f"/v1/voice/device/turns/{TURN_ID}/events"]


@pytest.mark.asyncio
async def test_local_stop_clears_progress_pcm_without_core_interrupt(core_server, monkeypatch):
    base, state = core_server
    state["events"] = [(0, wire_event("snapshot", 0, state="running", speech_text=None)),
                       (0, wire_event("progress_speech", 1, ordinal=1,
                                      speech_text="I'm working on your request.")),
                       (1, wire_event("working", 2, state="running"))]
    cancel = asyncio.Event()
    started = asyncio.Event()
    forwarded = []
    clears = []

    async def tts(args, *, on_audio, cancel_event):
        await on_audio(b"\0\0")
        started.set()
        await cancel_event.wait()
        await on_audio(b"stale0")
        return {"cancelled": True}

    async def audio(packet):
        forwarded.append(packet)

    async def clear_audio():
        clears.append(True)

    monkeypatch.setattr(core_turn_client, "run_stream_client", tts)
    task = asyncio.create_task(core_turn_client.synthesize_core_stream(
        base, TURN_ID, "core-test-token", tts_url="ws://unused", on_audio=audio,
        on_clear_audio=clear_audio, cancel_event=cancel))
    await asyncio.wait_for(started.wait(), 1)
    cancel.set()
    with pytest.raises(core_turn_client.PlaybackCancelled):
        await asyncio.wait_for(task, 0.3)
    assert forwarded == [b"\0\0"] and clears == [True]
    assert state["requests"] == [f"/v1/voice/device/turns/{TURN_ID}/events"]
