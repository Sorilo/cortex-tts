"""Run varied synthetic Cortex TTS turns through the public streaming client."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from pathlib import Path
from types import SimpleNamespace

from stream_client import PLAYBACK_THRESHOLDS, run


async def benchmark(args: argparse.Namespace) -> dict:
    cases = json.loads(args.corpus.read_text())
    if not isinstance(cases, list) or not cases:
        raise ValueError("corpus must contain at least one case")
    rows = []
    for iteration in range(args.iterations):
        for case in cases:
            name, pieces = case["id"], case["pieces"]
            if not isinstance(name, str) or not isinstance(pieces, list) or not pieces:
                raise ValueError("each case needs an id and nonempty pieces")
            output = args.output_dir / f"{name}-{iteration + 1}.wav"
            result = await run(SimpleNamespace(
                url=args.url, voice=args.voice, instruction=args.instruction,
                text=pieces, output=output, cancel_after_audio_bytes=0,
                piece_delay_ms=args.piece_delay_ms, flush_each=args.flush_each,
                timeout=args.timeout,
            ))
            rows.append({"case": name, "iteration": iteration + 1, **result})
    ttfa = sorted(row["first_audio_seconds"] for row in rows)
    speed = [row["generation_x_realtime"] for row in rows]
    summary = {
        "count": len(rows), "voice": args.voice, "instruction": args.instruction,
        "ttfa_median_s": statistics.median(ttfa),
        "ttfa_p95_s": ttfa[round((len(ttfa) - 1) * 0.95)],
        "minimum_generation_x_realtime": min(speed),
        "incomplete": sum(not row["complete"] for row in rows),
        "early_audio_cases": sum(row["first_audio_before_end"] for row in rows),
        "largest_chunk_gap_seconds": max(row["largest_chunk_gap_seconds"] for row in rows),
        "ideal_zero_buffer_underrun_requests": sum(bool(row["ideal_zero_buffer_underruns"]) for row in rows),
        "ideal_zero_buffer_underruns_total": sum(row["ideal_zero_buffer_underruns"] for row in rows),
        "ideal_zero_buffer_underrun_seconds_total": sum(
            row["ideal_zero_buffer_underrun_seconds"] for row in rows),
        "playback_simulation": {
            threshold: {
                "underrun_requests": sum(bool(row["playback_simulation"][threshold]["underruns"])
                                          for row in rows),
                "underruns_total": sum(row["playback_simulation"][threshold]["underruns"]
                                       for row in rows),
                "playback_start_median_s": statistics.median(
                    row["playback_simulation"][threshold]["playback_start_seconds"]
                    for row in rows),
                "playback_start_p95_s": sorted(
                    row["playback_simulation"][threshold]["playback_start_seconds"]
                    for row in rows)[round((len(rows) - 1) * 0.95)],
            }
            for threshold in map(str, PLAYBACK_THRESHOLDS)
        },
        "results": rows,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:18080/v1/speech/stream")
    parser.add_argument("--corpus", type=Path, default=Path("benchmarks/synthetic_corpus.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("evidence/local/corpus"))
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--voice", default="")
    parser.add_argument("--instruction", default="Speak clearly and naturally.")
    parser.add_argument("--piece-delay-ms", type=int, default=0)
    parser.add_argument("--flush-each", action="store_true")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    if args.iterations < 1 or args.piece_delay_ms < 0 or args.timeout <= 0:
        parser.error("iterations and timeout must be positive; piece delay must be nonnegative")
    result = asyncio.run(benchmark(args))
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, indent=2))


if __name__ == "__main__":
    main()
