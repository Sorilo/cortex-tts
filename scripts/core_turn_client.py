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


async def core_speech(core_url: str, turn_id: str, token: str, *, actor: str = "device",
                      timeout: float = 15.0, poll_interval: float = 0.2,
                      allow_approval_pending: bool = False) -> dict:
    """Return only a matching Core turn's speakable, nonempty speech_text."""
    if not TURN_ID.fullmatch(turn_id):
        raise ValueError("invalid Core audio_turn_id")
    if actor not in {"device", "software"}:
        raise ValueError("actor must be device or software")
    if not token or timeout <= 0 or poll_interval <= 0:
        raise ValueError("Core token and positive timeout/poll interval required")
    route = "/v1/voice/device/turns/" if actor == "device" else "/v1/voice/turns/"
    url = core_url.rstrip("/") + route + turn_id
    deadline = time.monotonic() + timeout
    action_id = None
    async with aiohttp.ClientSession(
        headers={"Authorization": "Bearer " + token},
        timeout=aiohttp.ClientTimeout(total=min(timeout, 10.0)), trust_env=False,
    ) as client:
        while True:
            async with client.get(url) as response:
                response.raise_for_status()
                result = await response.json()
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
            await asyncio.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))


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
    )
    tts = await run_stream_client(SimpleNamespace(
        url=tts_url, voice=voice, instruction=instruction,
        text=[authoritative["speech_text"]], output=output,
        cancel_after_audio_bytes=cancel_after_audio_bytes,
        piece_delay_ms=0, flush_each=False, timeout=tts_timeout,
    ), on_audio=on_audio, cancel_event=cancel_event)
    return {"core_audio_turn_id": authoritative["audio_turn_id"],
            "core_action_id": authoritative["action_id"],
            "core_state": authoritative["state"], "tts": tts}


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
