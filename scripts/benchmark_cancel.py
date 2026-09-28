"""Repeat cancel-after-first-audio and fresh-turn recovery on a running wrapper."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from pathlib import Path
from types import SimpleNamespace

from stream_client import run


LONG_TEXT = (
    "Here is the plan for the afternoon. First, finish the report and send it "
    "for review. Next, take a short break and check the calendar for changes. "
    "After that, prepare the notes for tomorrow's meeting. If something urgent "
    "comes up, handle it before starting the final task. Otherwise, leave enough "
    "time to review the details carefully before dinner."
)


def client_args(args: argparse.Namespace, text: str, cancel_bytes: int) -> SimpleNamespace:
    return SimpleNamespace(
        url=args.url, voice=args.voice, instruction=args.instruction,
        text=[text], output=None, cancel_after_audio_bytes=cancel_bytes,
        piece_delay_ms=0, flush_each=False, timeout=args.timeout,
    )


async def benchmark(args: argparse.Namespace) -> dict:
    rows = []
    for iteration in range(1, args.samples + 1):
        cancelled = await run(client_args(args, LONG_TEXT, 1))
        if (cancelled["complete"] or cancelled["cancel_ack_seconds"] is None
                or cancelled["audio_bytes_after_cancel"]):
            raise RuntimeError(f"cancel failed on iteration {iteration}: {cancelled}")
        recovered = await run(client_args(args, "The next turn is clear.", 0))
        if not recovered["complete"] or not recovered["bytes"]:
            raise RuntimeError(f"fresh turn failed on iteration {iteration}: {recovered}")
        rows.append({"iteration": iteration, "cancel_ack_seconds": cancelled["cancel_ack_seconds"],
                     "audio_bytes_after_cancel": cancelled["audio_bytes_after_cancel"],
                     "cancel_turn_id": cancelled["turn_id"],
                     "fresh_turn_id": recovered["turn_id"],
                     "fresh_audio_bytes": recovered["bytes"]})
    latencies = sorted(row["cancel_ack_seconds"] for row in rows)
    return {"samples": len(rows), "cancel_ack_median_s": statistics.median(latencies),
            "cancel_ack_p95_s": latencies[round((len(latencies) - 1) * 0.95)],
            "cancel_ack_max_s": latencies[-1],
            "fresh_turns_completed": len(rows), "results": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:18080/v1/speech/stream")
    parser.add_argument("--voice", default="")
    parser.add_argument("--instruction", default="Speak clearly and naturally.")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", type=Path,
                        default=Path("evidence/local/cancel-benchmark.json"))
    args = parser.parse_args()
    if not 1 <= args.samples <= 100 or args.timeout <= 0:
        parser.error("samples must be 1–100 and timeout must be positive")
    result = asyncio.run(benchmark(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()
