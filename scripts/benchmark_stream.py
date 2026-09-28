"""Compare direct Breeze and wrapper streaming on an isolated deployment.

All timings are client-observed. This script never starts a GPU or STT service.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

import aiohttp


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, int((len(ordered) - 1) * pct + 0.5)))]


async def measure(url: str, text: str, voice: str, instruction: str,
                  token: str | None, timeout: float) -> dict:
    headers = {"Authorization": "Bearer " + token} if token else {}
    async with aiohttp.ClientSession(headers=headers) as client:
        async with client.ws_connect(url, heartbeat=20,
                                     timeout=aiohttp.ClientWSTimeout(ws_receive=timeout)) as ws:
            ready = await ws.receive_json(timeout=timeout)
            if ready.get("type") != "ready":
                raise RuntimeError("backend did not become ready")
            begun = time.monotonic()
            await ws.send_json({"type": "start", "voice_id": voice,
                                "instruction": instruction})
            await ws.send_json({"type": "text", "text": text})
            await ws.send_json({"type": "end"})
            first = None
            last_chunk = None
            gaps = []
            bytes_audio = 0
            chunks = 0
            playback_end = None
            underrun_count = 0
            underrun_seconds = 0.0
            async for msg in ws:
                now = time.monotonic()
                if msg.type == aiohttp.WSMsgType.BINARY:
                    if len(msg.data) % 2:
                        raise RuntimeError("odd-length PCM")
                    if first is None:
                        first = now - begun
                    if last_chunk is not None:
                        gaps.append(now - last_chunk)
                    last_chunk = now
                    duration = len(msg.data) / 48000
                    if playback_end is None:
                        playback_end = now + duration
                    elif now > playback_end:
                        underrun_count += 1
                        underrun_seconds += now - playback_end
                        playback_end = now + duration
                    else:
                        playback_end += duration
                    bytes_audio += len(msg.data)
                    chunks += 1
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    event = json.loads(msg.data)
                    if event.get("type") == "error":
                        raise RuntimeError(str(event.get("message", "synthesis failed")))
                    if event.get("type") == "done":
                        break
                else:
                    raise RuntimeError("stream closed before done")
            total = time.monotonic() - begun
    audio_seconds = bytes_audio / 48000
    if not bytes_audio:
        raise RuntimeError("no audio was produced")
    return {"ttfa_s": first, "total_s": total, "audio_s": audio_seconds,
            "end_to_end_x_realtime": audio_seconds / total,
            "chunks": chunks, "largest_chunk_gap_s": max(gaps, default=0),
            "ideal_zero_buffer_underruns": underrun_count,
            "ideal_zero_buffer_underrun_s": underrun_seconds,
            "bytes": bytes_audio}


def summary(rows: list[dict]) -> dict:
    ttfa = [row["ttfa_s"] for row in rows]
    speed = [row["end_to_end_x_realtime"] for row in rows]
    gaps = [row["largest_chunk_gap_s"] for row in rows]
    return {"requests": len(rows), "ttfa_median_s": statistics.median(ttfa),
            "ttfa_p95_s": percentile(ttfa, 0.95),
            "speed_min_x_realtime": min(speed),
            "largest_gap_s": max(gaps),
            "ideal_zero_buffer_underrun_requests": sum(bool(r["ideal_zero_buffer_underruns"]) for r in rows),
            "results": rows}


async def run(args: argparse.Namespace) -> dict:
    results = {}
    for label, url, token in [
        ("direct", args.direct_ws, None),
        ("wrapper", args.wrapper_ws, os.getenv("CORTEX_TTS_TOKEN")),
    ]:
        if not url:
            continue
        if label == "wrapper" and not token:
            raise RuntimeError("CORTEX_TTS_TOKEN required for wrapper benchmark")
        rows = []
        for _ in range(args.requests):
            rows.append(await asyncio.wait_for(
                measure(url, args.text, args.voice, args.instruction, token,
                        args.timeout), args.timeout))
        results[label] = summary(rows)
    if "direct" in results and "wrapper" in results:
        results["median_wrapper_overhead_s"] = (
            results["wrapper"]["ttfa_median_s"] - results["direct"]["ttfa_median_s"]
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direct-ws", help="Local isolated direct backend WebSocket")
    parser.add_argument("--wrapper-ws", help="Local isolated Cortex wrapper WebSocket")
    parser.add_argument("--text", default="Hello from Cortex. This is a streaming test.")
    parser.add_argument("--voice", default="")
    parser.add_argument("--instruction", default="Speak clearly and naturally.")
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", default="evidence/local/stream-benchmark.json")
    args = parser.parse_args()
    if not args.direct_ws and not args.wrapper_ws:
        parser.error("at least one WebSocket URL is required")
    if args.requests < 1 or args.requests > 100:
        parser.error("requests must be between 1 and 100")
    results = asyncio.run(run(args))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
