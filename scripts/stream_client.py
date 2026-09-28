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
    async with aiohttp.ClientSession(headers=headers) as client:
        async with client.ws_connect(args.url, heartbeat=20) as ws:
            ready = await ws.receive_json(timeout=10)
            if ready.get("type") != "ready" or ready.get("version") != 1:
                raise RuntimeError("unexpected service contract")
            turn_id = ready["turn_id"]
            await ws.send_json({"type": "start", "voice_id": args.voice,
                                "instruction": args.instruction})
            for phrase in args.text:
                await ws.send_json({"type": "text", "text": phrase})
            await ws.send_json({"type": "end"})
            async for message in ws:
                if message.type == aiohttp.WSMsgType.BINARY:
                    if first_audio is None:
                        first_audio = time.monotonic() - started
                    pcm.extend(message.data)
                    if cancel_sent is not None:
                        audio_bytes_after_cancel += len(message.data)
                    if (args.cancel_after_audio_bytes and cancel_sent is None
                            and len(pcm) >= args.cancel_after_audio_bytes):
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
            "elapsed_seconds": elapsed, "audio_seconds": len(pcm) / 48000,
            "generation_x_realtime": (len(pcm) / 48000) / elapsed if elapsed else 0,
            "bytes": len(pcm), "complete": complete,
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
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2))


if __name__ == "__main__":
    main()
