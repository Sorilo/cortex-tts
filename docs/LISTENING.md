# Quantization listening review

Q4_K is the owner-approved release default because it leaves the most RTX 3080
memory for Whisper and later models. On 2026-09-28, the owner compared the
three blind, level-matched long-reply clips and found all acceptable: C sounded
slightly worse, with a possible slight advantage for A over B. The answer key
maps long-reply A/B/C to Q6_K/Q4_K/Q8_0. The owner chose Q4_K because its
quality was good enough for this use. The clips had different-sounding voices,
so this is a practical acceptance decision, not a controlled quality ranking.
Names, numbers, punctuation, clone similarity, direction fidelity, and real
speaker playback have not received the same owner listening verdict.

The local review set uses the four prompts in
`benchmarks/listening_corpus.json`: a timer with numbers, three names, a
two-sentence punctuation join, and a long multi-sentence reply. Each was sent
as one complete `text` message with the default voice instruction, “Speak
clearly and naturally.” The raw WAVs are in ignored
`evidence/local/listening-pack-{q4,q6,q8}/`; the twelve volume-matched copies
are in ignored `evidence/local/listening-pack-level-matched/`. That directory's
`manifest.json` records the exact text, image digests, raw/matched SHA-256,
duration, RMS, peak and gain for each file. The recordings are deliberately
excluded from Git because model output inherits the BreezeBlue license.

Run `python scripts/make_blind_listening_review.py` after preparing the matched
pack, then open the ignored local
`evidence/local/listening-pack-blind/index.html` in a browser. It presents
A/B/C in a separately randomized order for each prompt and copies the matched
WAV bytes unchanged. Record your preference and any audible faults for
`numbers`, `names`, `punctuation`, and `long_reply` before opening the adjacent
`answer-key.json`. The key records the random seed, variant mapping and source
hashes; use `--seed` to reproduce the label order if needed. Decide whether Q4
is acceptable relative to Q6/Q8, especially for names, numbers, phrase joins,
voice consistency and long-reply naturalness. The
matched copies use one constant linear attenuation per WAV to reach the
quietest source RMS for that prompt; they preserve duration and dynamics. RMS
matching is only a rough loudness control. This is one stochastic generation
per prompt/model, not a repeated perceptual study. The local page hides labels
for casual review but is not a controlled listening study. Real speaker
playback remains unverified.

To reproduce, use the verified model files and a dedicated local env file with
`BREEZE_MODEL_DIR`, `BREEZE_VOICES_DIR`, `BREEZE_GPU_DEVICE` and a fresh
`CORTEX_TTS_TOKEN`. Confirm the GPU window and that no other task reserves it.
For each quantization, set `BREEZE_MODEL_FILE` in that env file to the matching
container path `/models/breeze-tts-2-q4_k.gguf`,
`/models/breeze-tts-2-q6_k.gguf` or `/models/breeze-tts-2-q8_0.gguf`, then run
the isolated release project and wait for `/readyz` on loopback port 18084.
Run `scripts/benchmark_corpus.py` with
`--corpus benchmarks/listening_corpus.json --combine-pieces --url
ws://127.0.0.1:18084/v1/speech/stream --output-dir
evidence/local/listening-pack-q4` (substitute the output quantization). Stop
only that isolated Compose project before starting the next model. After all
three runs, execute `python scripts/prepare_listening_pack.py` to make the
volume-matched copies. Supply `--source-commit`, `--backend-image` and
`--wrapper-image` to embed the tested provenance in the local manifest. The
release Compose default remains Q4 when `BREEZE_MODEL_FILE` is unset.
The blind review generator checks the matched WAVs against those manifest
hashes before copying them. Keep both review audio and the answer key under
ignored `evidence/local/`; do not commit model outputs.

The matching four-prompt Q4/Q6/Q8 run with actively transcribing
`distil-small.en` is recorded in `docs/VALIDATION.md`. The tracked
`scripts/benchmark_active_stt.py` repeats that concurrent method against an
already-running isolated Breeze/Whisper stack. Expose only the isolated
Whisper container's TCP port 10300 on a temporary loopback port, then pass
`--stt-port`, `--probe-wav`, `--expected-transcript`, `--quant`, `--output-dir`
and `--output`. Set `BREEZE_GPU_DEVICE` or pass `--gpu-device` so VRAM samples
come from the TTS/STT GPU on a multi-GPU host. It never starts or stops
containers itself.

## Expressive voice review

The ignored `evidence/local/active-expressive-reference.wav` is a synthetic
reference spoken from the exact text “Hello, this is a synthetic reference voice
for Cortex.” In an isolated current-release Q4 run, the same four prompts from
`benchmarks/listening_corpus.json` were generated as reference-free design,
saved synthetic clone, and directed saved clone. Their WAVs are under ignored
`evidence/local/active-expressive-{design,clone,directed-clone}/` with names
such as `numbers-1.wav` and `long_reply-1.wav`. The design instruction was
“A warm, calm voice with a gentle smile.” The direction for the clone was
“Speak softly, with reassuring warmth and a slightly slower pace.”

Listen to the reference, then compare the same prompt across the three modes.
For clone, judge whether the character of the reference carries through; for
direction, judge whether warmth and pace change while the words remain clear.
Check names, numbers, phrase joins, and long-reply consistency. These files
were generated under active Whisper and are one stochastic sample per prompt,
not a human score. `docs/VALIDATION.md` records the timing and GPU limits;
human clone-similarity and direction judgments remain open.

The ignored `evidence/local/instruction-update-alpha13.wav` demonstrates a
single stream that starts with “Speak clearly and naturally,” then sends
“Speak softly, with reassuring warmth and a slightly slower pace” before its
second phrase. Listen for a change in delivery across the two phrases without
assuming the `instruction_set` acknowledgement proves the intended sound.
