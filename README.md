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

The backend uses Vulkan. The NVIDIA container runtime must expose a Vulkan-capable
driver and `graphics,display,compute,utility` driver capabilities. Run a separate
container smoke test and check `/readyz`; `gpus: all` alone is not proof that
Vulkan selected the intended 3080. No GPU allocation is attempted by ordinary
Python tests.

## Contract

See [docs/CORTEX-INTEGRATION.md](docs/CORTEX-INTEGRATION.md) for the versioned
stream events, Core authority boundary and later Cortex changes. The backend
performs phrase splitting. `text` can be sent as the LLM produces it; `flush`
forces a waiting phrase. The first playable audio is binary 24 kHz mono signed
16-bit little-endian PCM. `cancel` stops the current backend session and clears
its buffered text. A client disconnect closes the backend socket.

Saved cloned voices are created via authenticated `POST /v1/voices` with
`name`, `ref_audio` WAV, and exact `ref_text`. A saved voice ID is selectable in
Wyoming and Cortex. Leaving `voice_id` empty requests natural-language voice
design through `instruction`. Sending a voice ID with an `instruction` directs
that cloned voice. Saved `.breeze` profiles persist in the mounted voices volume;
reference recordings need not be retained by this service.

Run local tests with `pytest -q`. Current benchmark status and remaining gates
are in [docs/VALIDATION.md](docs/VALIDATION.md).
