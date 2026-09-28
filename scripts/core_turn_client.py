"""Opt-in example: fetch Core-authorized turn speech, then stream it to TTS.

This runs in a trusted voice client, not in the TTS service container.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from types import SimpleNamespace
from typing import Awaitable, Callable

import aiohttp

from stream_client import run as run_stream_client


TURN_ID = re.compile(r"^vt_[0-9a-f]{32}$")
TERMINAL = {"succeeded", "denied", "failed", "cancelled", "uncertain"}


class PlaybackCancelled(Exception):
    """The local playback turn ended; the Core action was not interrupted."""


async def _unless_cancelled(awaitable, cancel_event: asyncio.Event | None):
    if cancel_event is None:
        return await awaitable
    work = asyncio.create_task(awaitable)
    stopped = asyncio.create_task(cancel_event.wait())
    try:
        done, _ = await asyncio.wait((work, stopped), return_when=asyncio.FIRST_COMPLETED)
        if stopped in done:
            raise PlaybackCancelled("playback cancelled before TTS started")
        return await work
    finally:
        if not work.done():
            work.cancel()
        stopped.cancel()
        await asyncio.gather(work, stopped, return_exceptions=True)


async def core_speech(core_url: str, turn_id: str, token: str, *, actor: str = "device",
                      timeout: float = 15.0, poll_interval: float = 0.2,
                      allow_approval_pending: bool = False,
                      cancel_event: asyncio.Event | None = None) -> dict:
    """Return only a matching Core turn's speakable, nonempty speech_text."""
    if not TURN_ID.fullmatch(turn_id):
        raise ValueError("invalid Core audio_turn_id")
    if actor not in {"device", "software"}:
        raise ValueError("actor must be device or software")
    if not token or timeout <= 0 or poll_interval <= 0:
        raise ValueError("Core token and positive timeout/poll interval required")
    if cancel_event is not None and cancel_event.is_set():
        raise PlaybackCancelled("playback cancelled before Core polling")
    route = "/v1/voice/device/turns/" if actor == "device" else "/v1/voice/turns/"
    url = core_url.rstrip("/") + route + turn_id
    deadline = time.monotonic() + timeout
    action_id = None
    async with aiohttp.ClientSession(
        headers={"Authorization": "Bearer " + token},
        timeout=aiohttp.ClientTimeout(total=min(timeout, 10.0)), trust_env=False,
    ) as client:
        while True:
            async def get_result():
                async with client.get(url) as response:
                    response.raise_for_status()
                    return await response.json()

            result = await _unless_cancelled(get_result(), cancel_event)
            if (not isinstance(result, dict) or result.get("audio_turn_id") != turn_id
                    or not isinstance(result.get("action_id"), str)
                    or not result["action_id"]):
                raise RuntimeError("Core turn correlation is invalid")
            if action_id is None:
                action_id = result["action_id"]
            elif result["action_id"] != action_id:
                raise RuntimeError("Core action correlation changed")
            state = result.get("state")
            if state in TERMINAL or (state == "awaiting_approval" and allow_approval_pending):
                speech = result.get("speech_text")
                if not isinstance(speech, str) or not speech.strip():
                    raise RuntimeError("Core has no authoritative speech for this state")
                return {"audio_turn_id": turn_id, "action_id": result["action_id"],
                        "state": state, "speech_text": speech}
            if time.monotonic() >= deadline:
                raise TimeoutError("Core turn has no selected speakable result")
            await _unless_cancelled(
                asyncio.sleep(min(poll_interval, max(0.0, deadline - time.monotonic()))),
                cancel_event,
            )


async def synthesize_core_turn(core_url: str, turn_id: str, core_token: str, *,
                               tts_url: str, actor: str = "device", voice: str = "",
                               instruction: str = "Speak clearly and naturally.",
                               output: str | None = None, core_timeout: float = 15.0,
                               poll_interval: float = 0.2, tts_timeout: float = 120.0,
                               allow_approval_pending: bool = False,
                               cancel_after_audio_bytes: int = 0,
                               on_audio: Callable[[bytes], Awaitable[None]] | None = None,
                               cancel_event: asyncio.Event | None = None) -> dict:
    authoritative = await core_speech(
        core_url, turn_id, core_token, actor=actor, timeout=core_timeout,
        poll_interval=poll_interval, allow_approval_pending=allow_approval_pending,
        cancel_event=cancel_event,
    )
    if cancel_event is not None and cancel_event.is_set():
        raise PlaybackCancelled("playback cancelled before TTS started")
    tts = await run_stream_client(SimpleNamespace(
        url=tts_url, voice=voice, instruction=instruction,
        text=[authoritative["speech_text"]], output=output,
        cancel_after_audio_bytes=cancel_after_audio_bytes,
        piece_delay_ms=0, flush_each=False, timeout=tts_timeout,
    ), on_audio=on_audio, cancel_event=cancel_event)
    return {"core_audio_turn_id": authoritative["audio_turn_id"],
            "core_action_id": authoritative["action_id"],
            "core_state": authoritative["state"], "tts": tts}


async def synthesize_core_stream(core_url: str, turn_id: str, core_token: str, *,
                                 tts_url: str, actor: str = "device", voice: str = "",
                                 instruction: str = "Speak clearly and naturally.",
                                 timeout: float = 95.0, tts_timeout: float = 120.0,
                                 allow_approval_pending: bool = False,
                                 on_audio: Callable[[bytes], Awaitable[None]] | None = None,
                                 on_clear_audio: Callable[[], Awaitable[None]] | None = None,
                                 cancel_event: asyncio.Event | None = None) -> dict:
    """Opt-in Core SSE → serialized TTS PCM. Local audio stop never cancels an action.

    This is a trusted client example, not a Satellite/LVA playback adapter. It does
    not replay speech after reconnect or infer a result from a disconnected stream.
    """
    if not TURN_ID.fullmatch(turn_id) or actor not in {"device", "software"}:
        raise ValueError("invalid Core voice turn or actor")
    if not core_token or timeout <= 0 or tts_timeout <= 0:
        raise ValueError("Core token and positive deadlines required")
    if on_audio is not None and on_clear_audio is None:
        raise ValueError("PCM playback requires a queue-clear callback for interruption")
    if cancel_event is not None and cancel_event.is_set():
        raise PlaybackCancelled("playback cancelled before Core streaming")
    started = time.monotonic()
    path = "/v1/voice/device/turns/" if actor == "device" else "/v1/voice/turns/"
    url = core_url.rstrip("/") + path + turn_id + "/events?speech=true"
    action_id = None
    active: asyncio.Task | None = None
    active_cancel: asyncio.Event | None = None
    answer_started = False
    progress_ordinals: set[int] = set()
    first_pcm_ms = None
    speech_ready_ms = None
    snapshot_ms = None
    hermes_started_ms = None
    tool_activity_ms = None
    tts_start_ms = None
    cancellation_ms = None
    terminal_state = None
    tts_result = None
    finished = False

    async def stop_speech() -> None:
        nonlocal active, active_cancel, cancellation_ms
        if active is None:
            return
        if active.done():
            await asyncio.gather(active, return_exceptions=True)
        else:
            assert active_cancel is not None
            active_cancel.set()
            cancellation_ms = round((time.monotonic() - started) * 1000)
            done, _ = await asyncio.wait({active}, timeout=0.8)
            if not done:
                active.cancel()  # Closing the socket is the bounded local fallback.
                done, _ = await asyncio.wait({active}, timeout=0.2)
            if not done:
                raise RuntimeError("TTS cancellation unconfirmed; answer playback withheld")
            await asyncio.gather(active, return_exceptions=True)
        if on_clear_audio is not None:
            await asyncio.wait_for(on_clear_audio(), timeout=0.5)
        active = None

    def start_speech(text: str) -> None:
        nonlocal active, active_cancel, tts_start_ms, first_pcm_ms
        if not isinstance(text, str) or not text.strip() or len(text) > 240:
            raise RuntimeError("Core speech event is missing or oversized")
        active_cancel = asyncio.Event()
        local_cancel = active_cancel
        tts_start_ms = round((time.monotonic() - started) * 1000)

        async def forward_pcm(packet: bytes) -> None:
            nonlocal first_pcm_ms
            if local_cancel.is_set() or (cancel_event is not None and cancel_event.is_set()):
                return
            if len(packet) > 65536 or len(packet) % 2:
                raise RuntimeError("invalid bounded PCM packet")
            if first_pcm_ms is None:
                first_pcm_ms = round((time.monotonic() - started) * 1000)
            if on_audio is not None:
                await asyncio.wait_for(on_audio(packet), timeout=0.5)

        active = asyncio.create_task(run_stream_client(SimpleNamespace(
            url=tts_url, voice=voice, instruction=instruction, text=[text], output=None,
            cancel_after_audio_bytes=0, piece_delay_ms=0, flush_each=False,
            timeout=tts_timeout, collect_playback_packets=False,
        ), on_audio=forward_pcm, cancel_event=local_cancel))

    async def next_line(response) -> bytes:
        line_task = asyncio.create_task(response.content.readline())
        stop_task = (asyncio.create_task(cancel_event.wait())
                     if cancel_event is not None else None)
        try:
            waiting = {line_task} | ({stop_task} if stop_task is not None else set())
            done, _ = await asyncio.wait(waiting, timeout=10.0,
                                         return_when=asyncio.FIRST_COMPLETED)
            if stop_task is not None and stop_task in done:
                raise PlaybackCancelled("local playback cancelled")
            if line_task not in done:
                raise TimeoutError("Core progress stream stalled")
            return await line_task
        finally:
            if not line_task.done():
                line_task.cancel()
            if stop_task is not None:
                stop_task.cancel()
                await asyncio.gather(stop_task, return_exceptions=True)
            await asyncio.gather(line_task, return_exceptions=True)

    try:
        async with aiohttp.ClientSession(
            headers={"Authorization": "Bearer " + core_token},
            timeout=aiohttp.ClientTimeout(total=timeout), trust_env=False,
        ) as client:
            async with client.get(url) as response:
                response.raise_for_status()
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise RuntimeError("Core did not return a turn event stream")
                while True:
                    line = await next_line(response)
                    if not line:
                        break
                    if len(line) > 4096:
                        raise RuntimeError("Core event line exceeds bound")
                    if not line.startswith(b"data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except (ValueError, TypeError) as exc:
                        raise RuntimeError("invalid Core event") from exc
                    if (not isinstance(event, dict) or event.get("version") != "1.0.0"
                            or event.get("audio_turn_id") != turn_id
                            or not isinstance(event.get("action_id"), str)
                            or not event["action_id"].startswith("act_")):
                        raise RuntimeError("Core turn event correlation is invalid")
                    if action_id is None:
                        action_id = event["action_id"]
                    elif event["action_id"] != action_id:
                        raise RuntimeError("Core action correlation changed")
                    kind = event.get("type")
                    if kind == "snapshot" and snapshot_ms is None:
                        snapshot_ms = event.get("elapsed_ms")
                    elif kind == "hermes_started" and hermes_started_ms is None:
                        hermes_started_ms = event.get("elapsed_ms")
                    elif kind == "tool_activity" and tool_activity_ms is None:
                        tool_activity_ms = event.get("elapsed_ms")
                    elif kind == "progress_speech" and not answer_started:
                        ordinal = event.get("ordinal")
                        if ordinal in {1, 2} and ordinal not in progress_ordinals:
                            progress_ordinals.add(ordinal)
                            if active is None or active.done():
                                start_speech(event.get("speech_text"))
                    elif kind == "approval_waiting" and allow_approval_pending:
                        speech_ready_ms = event.get("elapsed_ms")
                        await stop_speech()
                        start_speech(event.get("speech_text"))
                        tts_result = await active
                        terminal_state = "awaiting_approval"
                        finished = True
                        break
                    elif kind == "response_available":
                        if event.get("state") not in TERMINAL or answer_started:
                            continue
                        speech_ready_ms = event.get("elapsed_ms")
                        await stop_speech()
                        start_speech(event.get("speech_text"))
                        answer_started = True
                        terminal_state = event["state"]
                    elif kind == "terminal":
                        if not answer_started or event.get("state") != terminal_state:
                            raise RuntimeError("Core terminal event lacked authoritative speech")
                        assert active is not None
                        tts_result = await active
                        finished = True
                        break
    finally:
        if not finished:
            await stop_speech()
    if terminal_state is None or tts_result is None:
        raise RuntimeError("Core event stream ended without a speakable result")
    return {"core_audio_turn_id": turn_id, "core_action_id": action_id,
            "core_state": terminal_state, "tts": tts_result,
            "timing": {"basis": "synthetic-client-monotonic; not audible latency",
                       "core_snapshot_elapsed_ms": snapshot_ms,
                       "hermes_started_core_elapsed_ms": hermes_started_ms,
                       "tool_activity_core_elapsed_ms": tool_activity_ms,
                       "speech_ready_core_elapsed_ms": speech_ready_ms,
                       "tts_start_client_elapsed_ms": tts_start_ms,
                       "first_pcm_client_elapsed_ms": first_pcm_ms,
                       "cancel_client_elapsed_ms": cancellation_ms}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", required=True, help="Trusted Core base URL")
    parser.add_argument("--turn-id", required=True, help="Core audio_turn_id")
    parser.add_argument("--actor", choices=("device", "software"), default="device")
    parser.add_argument("--tts-url", default="ws://127.0.0.1:18084/v1/speech/stream")
    parser.add_argument("--voice", default="")
    parser.add_argument("--instruction", default="Speak clearly and naturally.")
    parser.add_argument("--output", help="Optional WAV output path")
    parser.add_argument("--core-timeout", type=float, default=15.0)
    parser.add_argument("--poll-interval", type=float, default=0.2)
    parser.add_argument("--tts-timeout", type=float, default=120.0)
    parser.add_argument("--allow-approval-pending", action="store_true")
    parser.add_argument("--cancel-after-audio-bytes", type=int, default=0)
    args = parser.parse_args()
    if args.cancel_after_audio_bytes < 0 or args.tts_timeout <= 0:
        parser.error("cancellation threshold must be nonnegative and TTS timeout positive")
    core_token = os.environ.get("CORTEX_CORE_TOKEN", "")
    if not core_token or not os.environ.get("CORTEX_TTS_TOKEN"):
        parser.error("CORTEX_CORE_TOKEN and CORTEX_TTS_TOKEN are required")
    result = asyncio.run(synthesize_core_turn(
        args.core_url, args.turn_id, core_token, tts_url=args.tts_url,
        actor=args.actor, voice=args.voice, instruction=args.instruction,
        output=args.output, core_timeout=args.core_timeout,
        poll_interval=args.poll_interval, tts_timeout=args.tts_timeout,
        allow_approval_pending=args.allow_approval_pending,
        cancel_after_audio_bytes=args.cancel_after_audio_bytes,
    ))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
