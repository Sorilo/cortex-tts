"""Download pinned GGUF quantizations and codec; verify their transport hashes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download

GGUF_REPO = "HoppouAI/Breeze-TTS-2.cpp"
GGUF_REVISION = "81b22bad9f05b99970e30c5ee5e4bbc52fedf2f8"
CODEC_REPO = "BreezeBlue/Breeze-TTS-2"
CODEC_REVISION = "3e28c5151381a722f1d8661b4118c298caa77aa4"
GGUF_EXPECTED = {
    "q4": ("breeze-tts-2-q4_k.gguf", "483418fbbb438f5f1c08dbe2b017e42db0f1d126765cd3f772d8622a30a4915c"),
    "q6": ("breeze-tts-2-q6_k.gguf", "0eb51de6cbccd54b1c408198797254ac46b3cbd55ca1174c630eaac6d01064d3"),
    "q8": ("breeze-tts-2-q8_0.gguf", "a02bcc4b69b0601032727f8040c4942149b1b73aa0f69022fe5aaa6a8f0ef879"),
}
CODEC_EXPECTED = {
    "audio_tokenizer/config.json": "ee65bb901c876664ab8707c487157aa1a6ee57c65969b28fb5ec9dc211e68167",
    "audio_tokenizer/configuration.json": "6bc26d64eb5024b4d1dab5a52371958b429256d6c9d59787f1f5294a54e0cebd",
    "audio_tokenizer/model.safetensors": "836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258",
    "audio_tokenizer/preprocessor_config.json": "fcb3805e597e786d4067706e602f6688524640f8d3396790e2e09b5942fcbdfb",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quant", choices=GGUF_EXPECTED, nargs="+", default=["q4"],
                        help="GGUF variants to download; default q4")
    args = parser.parse_args()
    target = Path("models/Breeze-TTS-2").resolve()
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=GGUF_REPO, revision=GGUF_REVISION,
                      allow_patterns=[GGUF_EXPECTED[q][0] for q in args.quant], local_dir=target)
    snapshot_download(repo_id=CODEC_REPO, revision=CODEC_REVISION,
                      allow_patterns=["audio_tokenizer/*"], local_dir=target)
    manifest = {}
    selected = {GGUF_EXPECTED[q][0]: GGUF_EXPECTED[q][1] for q in args.quant}
    for relative, expected in {**selected, **CODEC_EXPECTED}.items():
        digest = hashlib.sha256()
        with (target / relative).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            raise RuntimeError(f"checksum mismatch: {relative}")
        manifest[relative] = actual
    (target / "SHA256SUMS.json").write_text(json.dumps({"gguf_repo": GGUF_REPO,
                                                      "gguf_revision": GGUF_REVISION,
                                                      "codec_repo": CODEC_REPO,
                                                      "codec_revision": CODEC_REVISION,
                                                      "files": manifest}, indent=2) + "\n")
    print(f"Verified {len(manifest)} files in {target}")


if __name__ == "__main__":
    main()
