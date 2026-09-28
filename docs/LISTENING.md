# Quantization listening review

Q4_K is the release default because it leaves the most RTX 3080 memory for
Whisper and later models. Automated transcription and timing cannot establish
whether its speech quality is close enough to Q6_K or Q8_0. The owner needs to
listen before treating that choice as final.

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

Listen to `numbers`, `names`, `punctuation`, then `long_reply` for each
quantization. Check whether Q4 changes the words, pronunciation, voice
consistency, phrase joins or long-reply naturalness relative to Q6/Q8. The
matched copies use one constant linear attenuation per WAV to reach the
quietest source RMS for that prompt; they preserve duration and dynamics. RMS
matching is only a rough loudness control. This is one stochastic generation
per prompt/model, not a blinded or repeated perceptual study. Owner listening
and real speaker playback remain unverified.

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
