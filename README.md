# cortex-tts

Standalone streaming Breeze TTS 2 service for Cortex and Wyoming clients. A CPU-only
wrapper handles the protocols; a Vulkan GPU backend holds the Breeze model. This
project is under development and has not been validated on a physical Satellite.

The initial runtime is [HoppouAI/Breeze-TTS-2.cpp](https://github.com/HoppouAI/Breeze-TTS-2.cpp)
at commit `8622f794bfe81649246ff908c8ca9247d9438556`. The default model is the
standard Q4_K GGUF. The GGUF and its required official `audio_tokenizer/` codec
are pinned and SHA-256 checked by `scripts/download_model.py`. The model and
generated outputs carry the BreezeBlue research/non-commercial license. Source
code licensing and adapted Fish attribution are described in [LICENSES.md](LICENSES.md).

## Local setup

1. Create a Python environment and install: `pip install -e '.[dev]' huggingface_hub`.
2. Run `python scripts/download_model.py`; it downloads about 3.2 GB of model
   assets into ignored `models/Breeze-TTS-2/` and checks every file.
   `python scripts/download_model.py --quant q4 q6 q8` also fetches the pinned
   comparison models; Q4 remains the deployment default.
3. Copy `.env.example` to `.env`, set absolute model/voice directories and a
   strong random `CORTEX_TTS_TOKEN`.
   Set `BREEZE_GPU_DEVICE` to the intended GPU index or UUID from `nvidia-smi -L`.
4. Only after confirming the GPU is available for this project, run
   `docker compose -p cortex-tts-dev up -d --build` from this repo.
5. Use `CORTEX_TTS_TOKEN=... python scripts/stream_client.py 'Hello from Cortex.'
   --output /tmp/cortex-tts-sample.wav` for an opt-in local smoke test.

The wrapper exposes a Cortex WebSocket on loopback port 18080 and Wyoming TCP on
loopback port 10220 by default. Change only this project's `.env` for deployment.
The backend ports are private to the dedicated Docker network. For Home Assistant
on another host, bind Wyoming to an appropriate trusted interface through this
project's `CORTEX_TTS_BIND` setting and configure HA's Wyoming integration.

The backend uses Vulkan with an NVIDIA headless EGL ICD. The NVIDIA container
runtime must expose a Vulkan-capable driver and `graphics,display,compute,utility`
driver capabilities. Check the backend log for `backend: Vulkan0` and confirm
its process owns GPU memory with `nvidia-smi`; `/readyz` alone cannot detect a
CPU fallback. The image builds ggml with native CPU tuning disabled so CI
runner instructions do not leak into the deployed binary. The wrapper warms short and long synthesis before opening its
ports (set `CORTEX_TTS_WARMUP=false` only for diagnostics). A cold restart took
about 20 seconds to become ready in the local RTX 3080 test. Ordinary Python tests
do not allocate a GPU.
The wrapper watches for backend outages and re-runs the short/long synthesis
warmup after recovery. `/readyz` stays unavailable during this rewarm, and
new speech requests receive a backend-warming error until it completes. A
local RTX 3080 test took about 24–26 seconds to return to readiness after
an isolated backend-only restart, then first PCM arrived in 120 ms. This
is recovery latency, not normal warm-request latency.
`BREEZE_CHUNK_FIRST=2` and `BREEZE_CHUNK_MAX=25` are the provisional streaming
defaults. The first value controls early PCM and how quickly an in-flight
chunk can be cancelled; one-frame output needs more playback buffering and
showed extra modeled gaps on split-message text. Set either value only after
measuring first sound, cancellation, throughput and rebuffers together.

The published alpha images are pinned by digest in `compose.release.yaml`.
When a safe GPU window is available, run that file on its own for a separate
`cortex-tts-release` project. Add `-f compose.stt-bench.yaml` only for an
isolated Whisper coexistence run with predownloaded `base.en` or
`distil-small.en` files in `STT_BENCH_MODEL_DIR`. That profile never references
the active Cortex deployment's model volume or STT container.
The release file uses ports 18084 and 10224 by default, separate from the
development file's ports. Both files require an explicit GPU device.
The current release pins the tested alpha.8 backend and alpha.10 wrapper pair.
See [docs/ROLLBACK.md](docs/ROLLBACK.md) for the exact fallback pair and
first-chunk setting if the new backend needs to be rolled back.

## Contract

See [docs/CORTEX-INTEGRATION.md](docs/CORTEX-INTEGRATION.md) for the versioned
stream events, Core authority boundary and later Cortex changes. The backend
performs phrase splitting. `text` can be sent as the LLM produces it; `flush`
forces a waiting phrase. The first playable audio is binary 24 kHz mono signed
16-bit little-endian PCM. `cancel` stops the current backend session and clears
its buffered text. A client disconnect closes the backend socket.
The first PCM packet is available before synthesis completes, but immediate
device playback can underrun on a first-seen text shape. Buffer by measured
PCM fill level and validate audible latency and rebuffers on the target device;
see [docs/CORTEX-INTEGRATION.md](docs/CORTEX-INTEGRATION.md).
When Core already has a complete authorized reply, send it as one `text`
message rather than artificially splitting it into sentences. The incremental
API remains available when authorized text genuinely arrives in pieces.

Saved cloned voices are created via authenticated `POST /v1/voices` with
`name`, `ref_audio` WAV, and exact `ref_text`. A saved voice ID is selectable in
Wyoming and Cortex. Leaving `voice_id` empty requests natural-language voice
design through `instruction`. Sending a voice ID with an `instruction` directs
that cloned voice. Saved `.breeze` profiles persist in the mounted voices volume;
reference recordings need not be retained by this service.

Run local tests with `pytest -q`. Current benchmark status and remaining gates
are in [docs/VALIDATION.md](docs/VALIDATION.md).

`scripts/core_turn_client.py` is an opt-in trusted-client example for the
current Core handoff. Given a Core `audio_turn_id`, it polls Core's authenticated
turn result, verifies the turn/action correlation, and sends only a nonempty
Core `speech_text` to this service in one streaming `text` message. Set
`CORTEX_CORE_TOKEN`, `CORTEX_TTS_TOKEN`, `CORTEX_CORE_URL` and
`CORTEX_AUDIO_TURN_ID` in the trusted client environment, then run:

```sh
python scripts/core_turn_client.py --core-url "$CORTEX_CORE_URL" \
  --turn-id "$CORTEX_AUDIO_TURN_ID" --output /tmp/core-tts-turn.wav
```

The script saves a WAV after receiving
progressive PCM; it does not implement device playback or change Core actions.
See [docs/CORTEX-INTEGRATION.md](docs/CORTEX-INTEGRATION.md) before adapting it
to a live voice path.

For an isolated synthetic corpus run against an already-started service, set
`CORTEX_TTS_TOKEN` and run `python scripts/benchmark_corpus.py --url
ws://127.0.0.1:18080/v1/speech/stream`. WAVs and JSON stay in ignored
`evidence/local/corpus/`. To verify that audio can arrive before later text,
run `python scripts/stream_client.py --flush-each --piece-delay-ms 1500
'The front door is locked.' 'The hallway lights are on.'`. Queue admission
delay can be sampled with `python scripts/benchmark_queue.py`.
