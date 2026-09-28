"""Create a local, blinded review page from a level-matched listening pack."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import secrets
import shutil
from pathlib import Path


QUANTS = ("q4", "q6", "q8")
LABELS = ("A", "B", "C")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_review(source_dir: Path, output_dir: Path, seed: int) -> None:
    manifest = json.loads((source_dir / "manifest.json").read_text())
    cases = manifest.get("cases")
    if not isinstance(cases, dict) or not cases:
        raise ValueError("matched pack has no cases")
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    key = {"seed": seed, "source_manifest": str(source_dir / "manifest.json"), "cases": {}}
    sections = []
    for case_id, case in cases.items():
        if not isinstance(case_id, str) or not case_id or not all(
            char.isalnum() or char in "_-" for char in case_id
        ):
            raise ValueError("invalid case id")
        variants = case.get("variants")
        if not isinstance(variants, dict) or set(variants) != set(QUANTS):
            raise ValueError(f"expected Q4/Q6/Q8 variants for {case_id}")
        order = list(QUANTS)
        rng.shuffle(order)
        key["cases"][case_id] = {}
        players = []
        for label, quant in zip(LABELS, order, strict=True):
            source = source_dir / f"{case_id}-{quant}.wav"
            expected = variants[quant]["matched_sha256"]
            if not source.is_file() or sha256(source) != expected:
                raise ValueError(f"missing or changed matched WAV: {source}")
            blind_name = f"{case_id}-{label}.wav"
            destination = output_dir / blind_name
            shutil.copyfile(source, destination)
            key["cases"][case_id][label] = {"quant": quant, "sha256": expected}
            players.append(
                f'<label>{label}<audio controls preload="none" src="{html.escape(blind_name, quote=True)}"></audio></label>'
            )
        prompt = html.escape(str(case["text"]))
        sections.append(
            f'<section><h2>{html.escape(case_id)}</h2><p>{prompt}</p>'
            + "\n".join(players)
            + "<p>Notes: ________________________________</p></section>"
        )
    page = """<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Breeze listening review</title>
<style>body{font:1rem system-ui;max-width:48rem;margin:2rem auto;padding:0 1rem;line-height:1.5}
section{border-top:1px solid #bbb;padding:1rem 0}label{display:flex;align-items:center;gap:1rem;margin:.6rem 0}
audio{width:min(100%,26rem)}</style>
<h1>Breeze listening review</h1>
<p>Compare A, B, and C within each prompt at a comfortable fixed volume. Note
pronunciation, names and numbers, phrase joins, voice consistency, and long-reply
naturalness. Open <code>answer-key.json</code> only after making your choices.
These are single samples; the labels are randomized separately for each prompt.</p>
""" + "\n".join(sections) + "\n</html>\n"
    (output_dir / "index.html").write_text(page)
    (output_dir / "answer-key.json").write_text(json.dumps(key, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path,
                        default=Path("evidence/local/listening-pack-level-matched"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("evidence/local/listening-pack-blind"))
    parser.add_argument("--seed", type=int, default=None,
                        help="Optional deterministic label order; random by default")
    args = parser.parse_args()
    if args.output_dir.resolve() == args.source_dir.resolve():
        parser.error("output directory must differ from matched source directory")
    build_review(args.source_dir, args.output_dir,
                 secrets.randbits(64) if args.seed is None else args.seed)
    print(args.output_dir / "index.html")


if __name__ == "__main__":
    main()
