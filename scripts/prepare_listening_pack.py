"""Match Q4/Q6/Q8 corpus WAV levels without altering their timing or dynamics."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import wave
from array import array
from pathlib import Path


def read_pcm(path: Path) -> array:
    with wave.open(str(path), "rb") as wav:
        if (wav.getnchannels(), wav.getframerate(), wav.getsampwidth(),
                wav.getcomptype()) != (1, 24000, 2, "NONE"):
            raise ValueError(f"expected 24 kHz mono PCM s16le WAV: {path}")
        samples = array("h")
        samples.frombytes(wav.readframes(wav.getnframes()))
    if not samples:
        raise ValueError(f"empty WAV: {path}")
    return samples


def rms(samples: array) -> float:
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("benchmarks/listening_corpus.json"))
    parser.add_argument("--source-root", type=Path, default=Path("evidence/local"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("evidence/local/listening-pack-level-matched"))
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--backend-image", default="")
    parser.add_argument("--wrapper-image", default="")
    args = parser.parse_args()
    if sys.byteorder != "little":
        parser.error("this PCM reader requires a little-endian host")
    corpus = json.loads(args.corpus.read_text())
    if not isinstance(corpus, list) or not corpus:
        parser.error("expected a nonempty listening corpus")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source_commit": args.source_commit,
        "backend_image": args.backend_image,
        "wrapper_image": args.wrapper_image,
        "corpus_source": str(args.corpus),
        "format": "24000 Hz mono PCM s16le WAV",
        "gain_method": "attenuate each case to its quietest source RMS using one linear gain per WAV",
        "cases": {},
    }
    for case in corpus:
        name = case["id"]
        sources = {}
        for quant in ("q4", "q6", "q8"):
            path = args.source_root / f"listening-pack-{quant}" / f"{name}-1.wav"
            samples = read_pcm(path)
            level = rms(samples)
            if level == 0:
                raise ValueError(f"silent WAV: {path}")
            sources[quant] = (path, samples, level)
        target = min(source[2] for source in sources.values())
        entry = {"text": " ".join(piece.strip() for piece in case["pieces"]),
                 "target_rms": target, "variants": {}}
        for quant, (path, samples, level) in sources.items():
            gain = target / level
            matched = array("h", (round(sample * gain) for sample in samples))
            output = args.output_dir / f"{name}-{quant}.wav"
            with wave.open(str(output), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(24000)
                wav.writeframes(matched.tobytes())
            entry["variants"][quant] = {
                "raw": str(path), "matched": str(output),
                "duration_s": len(samples) / 24000,
                "raw_rms": level, "gain": gain,
                "matched_rms": rms(matched),
                "matched_peak": max(abs(sample) for sample in matched),
                "raw_sha256": sha256(path), "matched_sha256": sha256(output),
            }
        manifest["cases"][name] = entry
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(args.output_dir / "manifest.json")


if __name__ == "__main__":
    main()
