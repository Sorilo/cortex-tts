"""Cortex contract example and local first-audio benchmark client."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import wave
from pathlib import Path
from typing import Awaitable, Callable

import aiohttp

PLAYBACK_THRESHOLDS = (0.0, 0.32, 0.64, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)


def simulate_playback(packets: list[tuple[float, float]], threshold_seconds: float,
                      completed_seconds: float) -> dict:
    """Model a PCM queue that starts once its fill level reaches a threshold."""
    if threshold_seconds < 0:
        raise ValueError("playback threshold must be nonnegative")
    buffered = 0.0
    playback_end = None
    playback_start = None
    underruns = 0
    underrun_seconds = 0.0
    for arrival, duration in packets:
        if playback_start is None:
            buffered += duration
            if buffered >= threshold_seconds:
                playback_start = arrival
                playback_end = arrival + buffered
        elif arrival > playback_end:
            underruns += 1
            underrun_seconds += arrival - playback_end
            playback_end = arrival + duration
        else:
            playback_end += duration
    if playback_start is None and packets:
        playback_start = completed_seconds
    return {"playback_start_seconds": playback_start,
            "underruns": underruns, "underrun_seconds": underrun_seconds}


async def run(args: argparse.Namespace, *,
              on_audio: Callable[[bytes], Awaitable[None]] | None = None) -> dict:
    """Receive progressive PCM; optionally forward each packet before completion."""
    headers = {"Authorization": "Bearer " + os.environ["CORTEX_TTS_TOKEN"]}
    started = time.monotonic()
    first_audio = None
    pcm = bytearray()
    audio_bytes = 0
    cancel_sent = None
    cancel_ack_seconds = None
    audio_bytes_after_cancel = 0
    complete = False
    first_text_sent = None
    last_text_sent = None
    end_sent = None
    ready_seconds = None
    last_chunk_at = None
    largest_chunk_gap = 0.0
    ideal_playback_end = None
    ideal_underruns = 0
    ideal_underrun_seconds = 0.0
    packets = []
    async with aiohttp.ClientSession(headers=headers) as client:
        async with client.ws_connect(
            args.url, heartbeat=20,
            timeout=aiohttp.ClientWSTimeout(ws_receive=args.timeout),
        ) as ws:
            ready = await ws.receive_json(timeout=10)
            if ready.get("type") != "ready" or ready.get("version") != 1:
                raise RuntimeError("unexpected service contract")
            ready_seconds = time.monotonic() - started
            turn_id = ready["turn_id"]

            async def send_input() -> None:
                nonlocal first_text_sent, last_text_sent, end_sent
                await ws.send_json({"type": "start", "voice_id": args.voice,
                                    "instruction": args.instruction})
                for index, phrase in enumerate(args.text):
                    await ws.send_json({"type": "text", "text": phrase})
                    last_text_sent = time.monotonic() - started
                    if first_text_sent is None:
                        first_text_sent = last_text_sent
                    if args.flush_each:
                        await ws.send_json({"type": "flush"})
                    if index + 1 < len(args.text) and args.piece_delay_ms:
                        await asyncio.sleep(args.piece_delay_ms / 1000)
                await ws.send_json({"type": "end"})
                end_sent = time.monotonic() - started

            sender = asyncio.create_task(send_input())
            try:
                async for message in ws:
                    if message.type == aiohttp.WSMsgType.BINARY:
                        if len(message.data) % 2:
                            raise RuntimeError("odd-length PCM")
                        arrived = time.monotonic()
                        if first_audio is None:
                            first_audio = arrived - started
                        if last_chunk_at is not None:
                            largest_chunk_gap = max(largest_chunk_gap, arrived - last_chunk_at)
                        last_chunk_at = arrived
                        duration = len(message.data) / 48000
                        packets.append((arrived - started, duration))
                        if ideal_playback_end is None:
                            ideal_playback_end = arrived + duration
                        elif arrived > ideal_playback_end:
                            ideal_underruns += 1
                            ideal_underrun_seconds += arrived - ideal_playback_end
                            ideal_playback_end = arrived + duration
                        else:
                            ideal_playback_end += duration
                        audio_bytes += len(message.data)
                        if args.output:
                            pcm.extend(message.data)
                        if on_audio is not None:
                            await on_audio(message.data)
                        if cancel_sent is not None:
                            audio_bytes_after_cancel += len(message.data)
                        if (args.cancel_after_audio_bytes and cancel_sent is None
                                and audio_bytes >= args.cancel_after_audio_bytes):
                            sender.cancel()
                            await asyncio.gather(sender, return_exceptions=True)
                            cancel_sent = time.monotonic()
                            await ws.send_json({"type": "cancel"})
                    elif message.type == aiohttp.WSMsgType.TEXT:
                        event = json.loads(message.data)
                        if event.get("turn_id") != turn_id:
                            raise RuntimeError("turn correlation changed")
                        if event.get("type") == "error":
                            raise RuntimeError(str(event.get("message", "synthesis failed")))
                        if event.get("type") == "cancelled":
                            cancel_ack_seconds = time.monotonic() - cancel_sent if cancel_sent else None
                            break
                        if event.get("type") == "done":
                            complete = True
                            break
                    else:
                        break
            finally:
                if not sender.done():
                    sender.cancel()
                send_result = await asyncio.gather(sender, return_exceptions=True)
                if isinstance(send_result[0], Exception):
                    raise send_result[0]
            if complete and end_sent is None:
                raise RuntimeError("backend completed before all text was sent")
            if not complete and cancel_ack_seconds is None:
                raise RuntimeError("stream closed before completion")
    elapsed = time.monotonic() - started
    playback = {str(threshold): simulate_playback(packets, threshold, elapsed)
                for threshold in PLAYBACK_THRESHOLDS}
    if args.output and pcm:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(pcm)
    return {"turn_id": turn_id, "first_audio_seconds": first_audio,
            "ready_seconds": ready_seconds,
            "elapsed_seconds": elapsed, "audio_seconds": audio_bytes / 48000,
            "generation_x_realtime": (audio_bytes / 48000) / elapsed if elapsed else 0,
            "bytes": audio_bytes, "complete": complete,
            "largest_chunk_gap_seconds": largest_chunk_gap,
            "ideal_zero_buffer_underruns": ideal_underruns,
            "ideal_zero_buffer_underrun_seconds": ideal_underrun_seconds,
            "playback_simulation": playback,
            "first_text_sent_seconds": first_text_sent,
            "last_text_sent_seconds": last_text_sent,
            "text_send_span_seconds": (
                last_text_sent - first_text_sent if first_text_sent is not None and last_text_sent is not None else None),
            "end_sent_seconds": end_sent,
            "first_audio_after_first_text_seconds": (
                first_audio - first_text_sent if first_audio is not None and first_text_sent is not None else None),
            "first_audio_before_last_text": (
                first_audio < last_text_sent if first_audio is not None and last_text_sent is not None else False),
            "first_audio_before_end": (
                first_audio < end_sent if first_audio is not None and end_sent is not None else False),
            "cancel_ack_seconds": cancel_ack_seconds,
            "audio_bytes_after_cancel": audio_bytes_after_cancel}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="+", help="Incremental text pieces")
    parser.add_argument("--url", default="ws://127.0.0.1:18080/v1/speech/stream")
    parser.add_argument("--voice", default="")
    parser.add_argument("--instruction", default="Speak clearly and naturally.")
    parser.add_argument("--output", help="Optional WAV output path")
    parser.add_argument("--cancel-after-audio-bytes", type=int, default=0)
    parser.add_argument("--piece-delay-ms", type=int, default=0,
                        help="Delay between incremental text pieces while receiving audio")
    parser.add_argument("--flush-each", action="store_true",
                        help="Flush each text piece to force early phrase synthesis")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if args.piece_delay_ms < 0 or args.timeout <= 0:
        parser.error("piece delay must be nonnegative and timeout must be positive")
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
