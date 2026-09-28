import hashlib
import json
from pathlib import Path

import pytest

from scripts.make_blind_listening_review import build_review


def test_blind_review_copies_verified_audio_and_hides_quant_labels(tmp_path: Path):
    source = tmp_path / "matched"
    output = tmp_path / "blind"
    source.mkdir()
    variants = {}
    for quant in ("q4", "q6", "q8"):
        data = (quant + " audio").encode()
        (source / f"numbers-{quant}.wav").write_bytes(data)
        variants[quant] = {"matched_sha256": hashlib.sha256(data).hexdigest()}
    (source / "manifest.json").write_text(json.dumps({"cases": {
        "numbers": {"text": "One < two & three", "variants": variants}
    }}))

    build_review(source, output, seed=5)

    page = (output / "index.html").read_text()
    key = json.loads((output / "answer-key.json").read_text())
    assert "One &lt; two &amp; three" in page
    assert all(f"numbers-{label}.wav" in page for label in "ABC")
    assert all(quant not in page for quant in ("q4", "q6", "q8"))
    assert {item["quant"] for item in key["cases"]["numbers"].values()} == {"q4", "q6", "q8"}
    for label, item in key["cases"]["numbers"].items():
        assert hashlib.sha256((output / f"numbers-{label}.wav").read_bytes()).hexdigest() == item["sha256"]

    (source / "numbers-q4.wav").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed matched WAV"):
        build_review(source, output, seed=5)
