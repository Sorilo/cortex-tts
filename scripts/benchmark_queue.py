"""Measure Cortex ready-event delay with and without one occupied GPU slot."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

import aiohttp


async def expect_ready(ws: aiohttp.ClientWebSocketResponse, timeout: float) -> None:
    event = await ws.receive_json(timeout=timeout)
    if event.get("type") != "ready" or event.get("version") != 1:
        raise RuntimeError(f"expected Cortex ready, got {event}")


async def one_sample(client: aiohttp.ClientSession, url: str,
                     hold_seconds: float, timeout: float) -> dict:
    control_start = time.monotonic()
    async with client.ws_connect(url) as control:
        await expect_ready(control, timeout)
        control_ready = time.monotonic() - control_start
    # The server releases admission after it observes the control disconnect.
    await asyncio.sleep(0.05)

    async with client.ws_connect(url) as occupied:
        await expect_ready(occupied, timeout)

        async def release() -> None:
            await asyncio.sleep(hold_seconds)
            await occupied.close()

        started = time.monotonic()
        release_task = asyncio.create_task(release())
        try:
            async with client.ws_connect(url) as waiting:
                await expect_ready(waiting, timeout)
                queued_ready = time.monotonic() - started
        finally:
            await release_task
    return {"control_ready_s": control_ready, "queued_ready_s": queued_ready,
            "estimated_queue_delay_s": max(0.0, queued_ready - control_ready)}


async def run(args: argparse.Namespace) -> dict:
    token = os.environ["CORTEX_TTS_TOKEN"]
    headers = {"Authorization": "Bearer " + token}
    async with aiohttp.ClientSession(headers=headers) as client:
        rows = [await one_sample(client, args.url, args.hold_seconds, args.timeout)
                for _ in range(args.samples)]
    queue = sorted(row["estimated_queue_delay_s"] for row in rows)
    p95 = queue[round((len(queue) - 1) * 0.95)]
    return {"samples": len(rows), "hold_seconds": args.hold_seconds,
            "estimated_queue_delay_median_s": statistics.median(queue),
            "estimated_queue_delay_p95_s": p95, "results": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:18080/v1/speech/stream")
    parser.add_argument("--hold-seconds", type=float, default=0.75)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--output", type=Path, default=Path("evidence/local/queue-benchmark.json"))
    args = parser.parse_args()
    if not 0 < args.hold_seconds < args.timeout or not 1 <= args.samples <= 100:
        parser.error("hold must be positive and below timeout; samples must be 1–100")
    result = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "results"}))


if __name__ == "__main__":
    main()
