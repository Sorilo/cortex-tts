# Validation status and required evidence

The service has a local fake-backend protocol test suite. This is software
evidence only. It does not establish a real model's TTFA, speed, quality,
Vulkan operation, GPU co-residency, or physical Satellite playback.

## Performance targets

- Warm wrapper-client first playable audio: median at most 300 ms, p95 at most 500 ms.
- Sustained generation: consistently faster than real time; prefer 1.5x or more.
- No playback underruns on the defined short/long response corpus.
- Wrapper overhead p95 at most 25 ms versus the direct Breeze WebSocket.
- Cancellation to stopped backend and discarded queued audio at most 250 ms.
- Breeze plus Wyoming Whisper target at most 5 GiB observed peak GPU usage.

Measure queue delay, text accumulation, direct-backend TTFA, wrapper-client
TTFA, chunk gaps, client buffering, audio duration/generation time, peak VRAM,
and cold loading separately. Record hardware and model revisions. Compare Q4_K,
Q6_K and Q8_0; ordinary voice, saved clone, voice design and direction; short
commands and long replies. Listen for names, numbers, pronunciation, phrase
joins, consistency and long-response degradation. Repeat with isolated
LinuxServer Wyoming `base.en` and `distil-small.en` instances resident and
actively transcribing. Use the exact pins documented in the Cortex M6a voice
evaluation, but separate Compose names, ports, networks and volumes.

Before any GPU run, coordinate access with ongoing Cortex/Pi work. A blank
`nvidia-smi` process list is not exclusive authorization. Do not operate another
task's STT container. Store machine-local measurements under ignored
`evidence/local/`; publish only reviewable synthetic results and exact commands.

Run the streaming example and benchmark with `scripts/stream_client.py`. The
client reports first audio and generated-audio-to-wall-time ratio. It is a
smoke metric. `scripts/benchmark_stream.py` compares direct and wrapped paths,
records first audio, throughput and chunk gaps in ignored `evidence/local/`.
It does not yet infer actual playback buffer underruns; measure those with the
target playback client.

## Current independent checks (2026-09-28)

- Python package compiles; eleven local fake-backend tests pass. They cover Cortex
  early audio, auth, voice upload/discovery, disconnect/cancel, Wyoming discovery,
  Wyoming legacy and incremental early audio, bounded admission, input limits,
  terminal backend errors and abrupt backend disconnects.
- Docker Compose syntax, wrapper image build and pinned Vulkan backend image
  build pass. `ldd` resolves all backend libraries inside the runtime image.
- Pinned Q4 GGUF plus official codec downloaded and SHA-256 verified (five files).
- Isolated CPU-only real-Q4 smoke: HTTP synthesis returned 30,720 bytes PCM;
  Cortex WebSocket delivered 61,440 bytes (1.28 s audio) with first audio at
  3.495 s and completion at 14.592 s. Wyoming delivered 30,720 bytes.
  Saved synthetic voice `cpu_smoke_voice` encoded from a generated 1.28 s WAV
  and successfully streamed a further 38,400 bytes through the Cortex API.
  These timings are CPU compatibility evidence, not GPU performance evidence.
- The direct-versus-wrapper benchmark harness completed one Q4 CPU request per
  path with the same saved synthetic voice and 0.72 s of audio. Direct/client
  TTFA was 4.268 s and wrapper/client TTFA 4.251 s; each produced 34,560 PCM
  bytes. One sequential CPU sample is too weak to estimate wrapper p95 overhead.
- Real GPU model, Whisper coexistence, listening, soak, and physical playback
  remain pending and must not be represented as passed.
- Initial GitHub Actions wrapper test/Compose workflow passed at
  `8f4291087b082a218452b7f743354d0dab17717d`.
- Alpha.2 image workflow passed at `d0e7ffce53cce16ecf0bb2c99f3af347a08cc061`:
  backend `ghcr.io/sorilo/cortex-tts-backend@sha256:953f6229d3cbb94fb5d2bb69a672a8e7baa64b8f191ec03b5fccdc43ba768896`;
  wrapper `ghcr.io/sorilo/cortex-tts-wrapper@sha256:908eea62ba2a0a33fde1e1eaf8be695707072923119c34d3bb38922fd43ab47d`.
  Those images are packaged; the GPU behavior remains unmeasured.
