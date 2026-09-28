# Validation status and required evidence

The service has fake-backend protocol tests and isolated RTX 3080 measurements.
Synthetic speech and loopback clients establish transport and local performance;
they do not establish human-rated audio quality or physical Satellite playback.

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

- Python package compiles; 14 local fake-backend tests pass. They cover Cortex
  early audio, auth, voice upload/discovery, disconnect/cancel, Wyoming discovery,
  Wyoming legacy and incremental early audio, bounded admission, input limits,
  Wyoming stream timeout,
  terminal backend errors and abrupt backend disconnects.
- Docker Compose syntax, wrapper image build and pinned Vulkan backend image
  build pass. `ldd` resolves all backend libraries inside the runtime image.
- Pinned Q4, Q6 and Q8 GGUF files plus official codec downloaded and SHA-256
  verified (seven files). Q4 is the deployment default.
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
- On a 10 GiB RTX 3080 (NVIDIA driver 595.91.07), the original runtime image
  silently selected CPU because the NVIDIA GLX Vulkan ICD lacked dependencies.
  The corrected image uses the headless EGL ICD; backend logs identify `Vulkan0`
  and `nvidia-smi` identifies the Breeze process. The alpha.2 backend image
  predates this headless ICD fix.
- The alpha.4 image built on GitHub detected Vulkan but exited with SIGILL
  (code 132) on the dev host before loading Q4, while the dev-host build ran.
  The backend build now disables ggml native CPU tuning and AVX-512. A local
  rebuild loaded Q4 on Vulkan0 and streamed 176,640 PCM bytes per request;
  its first cold TTFA was 12.635 s, then 185 ms and 2.19× real time. The
  published portable image was subsequently verified as described below.
- Q4, 20 sequential warm short requests per path with the same saved synthetic
  voice: direct TTFA median/p95 186/189 ms, wrapper 187/193 ms. Wrapper's median
  TTFA exceeded direct by about 1 ms; this sequential experiment does not
  establish p95 overhead under identical load. Every request completed above
  2.0× real time. Observed peak Breeze-only memory was 2,888 MiB for this short
  run, and 3,252 MiB during a longer reply. The first request after a cold
  model restart incurred roughly 10–13 seconds of Vulkan compilation and was
  excluded from warm distributions.
- A longer 11.04-second reply reached first audio in about 202–215 ms after
  its first shape-specific warmup and completed at about 2.1× real time. Largest
  chunk gaps approached 0.99 s; a playback buffer/underrun test remains needed.
- With pinned Wyoming Whisper `base.en` actively transcribing 20 synthetic
  commands, ten Q4 requests had median/p95 TTFA 186/193 ms, minimum 2.08×
  speed, and 3,678 MiB observed combined peak VRAM. With `distil-small.en`
  actively transcribing 20 commands, corresponding figures were 187/194 ms,
  2.07×, and 3,870 MiB. All 40 synthetic commands back-transcribed correctly.
  Model files were copied into this repo's ignored model area and SHA-checked;
  only the isolated `cortex-tts-stt-bench` container was operated.
- With distil-small resident, Q6's nine warm saved-voice requests had median/
  p95 TTFA 196/210 ms, minimum 2.0× speed and 3,996 MiB observed combined
  peak VRAM. Q8's nine warm requests had 192/198 ms, 2.02× and 4,491 MiB.
  Their first saved-voice request after default-voice warmup was excluded as a
  separate shape warmup. Q4 retains the most memory headroom; these timings and
  one Whisper back-transcription per quantization cannot rank perceived quality.
- Q4 default voice's ten warm short requests had median/p95 TTFA 186/332 ms
  and minimum 2.02× speed. A directed Q4 voice produced PCM above real time;
  one subsequent warm directed request reached first audio in 361 ms. Saved
  synthetic reference voice synthesis and voice registration were exercised,
  but direction fidelity and clone similarity require listening.
- One Q4 GPU cancellation acknowledged in 216 ms and delivered zero audio bytes
  after the cancel request. This is one client-observed sample, not a p95.
- Startup warmup first used only a short phrase: the wrapper ports stayed closed
  for 13.2 s and the first user request after readiness reached audio in 384 ms.
  A later, new long phrase then had two idealized zero-buffer underruns totaling
  0.76 s; four repeats had none. The warmup now includes a representative long
  phrase and took 20.0 s before readiness. Three requests for a *different*
  long phrase then had zero idealized underruns; the first reached audio in
  450 ms and ran at 1.37×, while subsequent ones started in 186–196 ms and
  ran above 2×. This simulation assumes PCM playback starts exactly at the first
  audio packet and does not include real device jitter or output buffering.
- Human listening, long-duration diverse-text soak, real playback-device
  underruns, far-field microphone audio, and physical Satellite/Core integration
  remain pending.
- The digest-pinned **alpha.5** published backend and wrapper passed an isolated
  Compose smoke on this RTX 3080: backend Vulkan0, zero restarts, wrapper
  `/readyz` healthy after 21.8 s startup warmup, Cortex PCM streamed, and
  Wyoming returned AudioStart/Chunk/Stop. Twenty alternating direct/wrapper
  pairs measured wrapper TTFA median/p95 183/189 ms and paired p95 wrapper
  overhead 8 ms; all 40 requests had zero idealized underruns. A 100-request
  published-wrapper soak with pinned base.en resident and 150 synthetic STT
  requests in parallel completed without a synthesis error or service restart:
  TTFA median/p95 186/199 ms, minimum 2.04× real-time speed, zero idealized
  underruns, 150/150 exact synthetic back-transcriptions, and 3,618 MiB
  observed combined peak VRAM. The synthetic phrase and 3.92 s generated audio
  were the same on each iteration; this cannot prove diverse-text quality.
  One published cancel acknowledged in 215 ms with no subsequent audio.
  The alpha.5 wrapper counted a client closing after `cancelled` as a failure;
  the event is now terminal and a regression test checks the failure count.
  Republish the wrapper before pinning that fix.
- Initial GitHub Actions wrapper test/Compose workflow passed at
  `8f4291087b082a218452b7f743354d0dab17717d`.
- Alpha.2 image workflow passed at `d0e7ffce53cce16ecf0bb2c99f3af347a08cc061`:
  backend `ghcr.io/sorilo/cortex-tts-backend@sha256:953f6229d3cbb94fb5d2bb69a672a8e7baa64b8f191ec03b5fccdc43ba768896`;
  wrapper `ghcr.io/sorilo/cortex-tts-wrapper@sha256:908eea62ba2a0a33fde1e1eaf8be695707072923119c34d3bb38922fd43ab47d`.
  Those images are packaged; the GPU behavior remains unmeasured.
