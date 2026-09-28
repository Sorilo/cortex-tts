"""Run an isolated Cortex TTS corpus while Wyoming STT transcribes repeatedly."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

from benchmark_corpus import benchmark
from wyoming_stt_probe import transcribe


async def gpu_memory_mib(device: str) -> int:
    proc = await asyncio.create_subprocess_exec(
        "nvidia-smi", f"--id={device}", "--query-gpu=memory.used",
        "--format=csv,noheader,nounits",
        stdout=asyncio.subprocess.PIPE,
    )
    output, _ = await proc.communicate()
    if proc.returncode:
        raise RuntimeError("nvidia-smi memory sampling failed")
    return int(output.decode().strip().splitlines()[0])


async def run(args: argparse.Namespace) -> dict:
    if not os.getenv("CORTEX_TTS_TOKEN"):
        raise ValueError("CORTEX_TTS_TOKEN required")
    if not args.gpu_device:
        raise ValueError("GPU device index or UUID required for accurate memory sampling")
    stop = asyncio.Event()
    probes: list[dict] = []
    memory: list[int] = []

    async def stt_loop() -> None:
        while not stop.is_set():
            probes.append(await transcribe(args.stt_host, args.stt_port, args.probe_wav))

    async def memory_loop() -> None:
        while not stop.is_set():
            memory.append(await gpu_memory_mib(args.gpu_device))
            await asyncio.sleep(args.memory_interval)

    stt_task = asyncio.create_task(stt_loop())
    memory_task = asyncio.create_task(memory_loop())
    try:
        corpus = await benchmark(SimpleNamespace(
            corpus=args.corpus, output_dir=args.output_dir, iterations=1,
            url=args.url, voice="", instruction="Speak clearly and naturally.",
            combine_pieces=True, piece_delay_ms=0, flush_each=False,
            timeout=args.timeout,
        ))
    finally:
        stop.set()
        await asyncio.gather(stt_task, memory_task)
    if not probes or not memory or corpus["incomplete"]:
        raise RuntimeError("active-STT corpus did not complete")
    expected = args.expected_transcript.strip()
    return {
        "quant": args.quant,
        "gpu_device": args.gpu_device,
        "tts_count": corpus["count"],
        "tts_first_pcm_median_s": corpus["ttfa_median_s"],
        "tts_first_pcm_p95_s": corpus["ttfa_p95_s"],
        "tts_min_generation_x_realtime": corpus["minimum_generation_x_realtime"],
        "tts_ideal_zero_buffer_underrun_requests": corpus["ideal_zero_buffer_underrun_requests"],
        "stt_probe_count": len(probes),
        "stt_exact_transcripts": sum(probe["text"].strip() == expected for probe in probes),
        "stt_max_latency_s": max(probe["total_s"] for probe in probes),
        "gpu_memory_samples": len(memory),
        "gpu_memory_peak_mib": max(memory),
        "gpu_memory_min_mib": min(memory),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quant", required=True)
    parser.add_argument("--gpu-device", default=os.getenv("BREEZE_GPU_DEVICE"),
                        help="NVIDIA GPU index or UUID; defaults to BREEZE_GPU_DEVICE")
    parser.add_argument("--url", default="ws://127.0.0.1:18084/v1/speech/stream")
    parser.add_argument("--stt-host", default="127.0.0.1")
    parser.add_argument("--stt-port", type=int, default=10310)
    parser.add_argument("--probe-wav", type=Path, required=True)
    parser.add_argument("--expected-transcript", required=True)
    parser.add_argument("--corpus", type=Path, default=Path("benchmarks/listening_corpus.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--memory-interval", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.memory_interval <= 0 or args.timeout <= 0:
        parser.error("memory interval and timeout must be positive")
    result = asyncio.run(run(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
