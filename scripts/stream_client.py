"""Cortex contract example and local first-audio benchmark client."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import wave
from pathlib import Path

import aiohttp


async def run(args: argparse.Namespace) -> dict:
    headers = {"Authorization": "Bearer " + os.environ["CORTEX_TTS_TOKEN"]}
    started = time.monotonic()
    first_audio = None
    pcm = bytearray()
    cancel_sent = None
    cancel_ack_seconds = None
    audio_bytes_after_cancel = 0
    complete = False
    first_text_sent = None
    last_text_sent = None
    end_sent = None
    ready_seconds = None
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
                        if first_audio is None:
                            first_audio = time.monotonic() - started
                        pcm.extend(message.data)
                        if cancel_sent is not None:
                            audio_bytes_after_cancel += len(message.data)
                        if (args.cancel_after_audio_bytes and cancel_sent is None
                                and len(pcm) >= args.cancel_after_audio_bytes):
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
            "elapsed_seconds": elapsed, "audio_seconds": len(pcm) / 48000,
            "generation_x_realtime": (len(pcm) / 48000) / elapsed if elapsed else 0,
            "bytes": len(pcm), "complete": complete,
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
