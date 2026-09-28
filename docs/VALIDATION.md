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
client sends text concurrently with receiving audio, and `--piece-delay-ms`
with `--flush-each` demonstrates audio preceding later text. It reports first
audio and generated-audio-to-wall-time ratio; the latter includes deliberate
input delays and is a smoke metric. `scripts/benchmark_queue.py` measures
ready-event delay while one GPU slot is occupied. `scripts/benchmark_corpus.py`
runs the versioned synthetic text corpus and saves local WAVs and per-turn JSON.
`scripts/benchmark_stream.py` compares direct and wrapped paths,
records first audio, throughput and chunk gaps in ignored `evidence/local/`.
It does not yet infer actual playback buffer underruns; measure those with the
target playback client.

## Current independent checks (2026-09-28)

- Python package compiles; 17 local fake-backend tests pass. They cover Cortex
  early audio, auth, voice upload/discovery, disconnect/cancel, Wyoming discovery,
  Wyoming legacy and incremental early audio, bounded admission, input limits,
  Wyoming stream timeout,
  terminal backend errors and abrupt backend disconnects, recovery after both
  failures, busy-slot isolation, queued admission order, and a concurrently
  sending streaming client.
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
- The same-sentence Q4/Q6/Q8 default-voice WAVs are valid 24 kHz mono 16-bit
  PCM with no clipped samples. Their raw RMS sample magnitudes were about
  2,293/1,921/789 respectively; Q8 is markedly quieter in this single sample.
  Level-matched copies are stored only under ignored `evidence/local/` for
  owner listening. Loudness and one STT back-transcription do not rank voice
  naturalness, pronunciation or clone similarity.
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
- The final release Compose pins the verified portable alpha.5 backend OCI
  index `sha256:0ace2780f6a5b4f47fe4ca5b977db83c09e51bdd38f4c9a5a1f6df023262e65e`
  and alpha.6 wrapper index
  `sha256:39ed6a01f908de63554ab37bc37c3862ec22b929ef860a92a47bfa5cf2699144`.
  This exact pair passed isolated Compose readiness on the RTX 3080. A published
  cancellation acknowledged in 213 ms with zero post-cancel audio; metrics
  showed `cancelled:1`, `failures:0`, `active:false`, `queued:0`. A fresh next
  turn produced 188,160 PCM bytes and completed normally. This verifies the
  cancellation fix in the published wrapper, not only in the local tests.
- On the same digest-pinned Q4 release pair, two text pieces sent 1.5 s apart
  with `--flush-each` produced the first PCM packet 0.413 s after connection,
  before the second text piece at 1.506 s and before `end`. This is a real
  incremental-output check; its wall-time throughput includes the intentional
  input delay. Ten occupied-slot ready-event probes with a 0.75 s hold gave
  estimated queue-delay median/p95 0.752/0.754 s. These timings separate
  admission wait from synthesis startup but do not measure end-user LLM delay.
- The reproducible eight-case synthetic corpus covers commands, names, numbers,
  punctuation, multi-piece text and a 22.64 s long reply. Sixteen default Q4
  turns completed: median/p95 first audio 186/194 ms. One first-pass weather
  phrase ran at 1.15× real time, then 2.10× on repetition; a first-pass short
  phrase began at 359 ms, then 191 ms. The other repeated turns were 1.98×
  real time or faster. These are warm-system but not necessarily warm-shape
  measurements, and do not establish sustained speed for arbitrary new text.
- Eight voice-design turns completed with median/p95 first audio 187/481 ms;
  eight synthetic saved-clone turns completed at 221/2386 ms; eight directed
  clone turns completed at 222/486 ms. The large clone p95 came from a single
  long-reply shape that started at 2.386 s. A 6.24 s WAV generated locally by
  this TTS service was registered as the synthetic clone with its exact text;
  it is not a human reference recording. In these small runs, after first-shape
  warmup, all three modes generated audio faster than real time. Whisper
  `base.en` recovered the intended names, numbers, multi-piece text and long
  reply in eight probed outputs, allowing punctuation/spacing normalization.
  This is an intelligibility proxy, not a listening or clone-similarity score.
- Initial GitHub Actions wrapper test/Compose workflow passed at
  `8f4291087b082a218452b7f743354d0dab17717d`.
- Alpha.2 image workflow passed at `d0e7ffce53cce16ecf0bb2c99f3af347a08cc061`:
  backend `ghcr.io/sorilo/cortex-tts-backend@sha256:953f6229d3cbb94fb5d2bb69a672a8e7baa64b8f191ec03b5fccdc43ba768896`;
  wrapper `ghcr.io/sorilo/cortex-tts-wrapper@sha256:908eea62ba2a0a33fde1e1eaf8be695707072923119c34d3bb38922fd43ab47d`.
  Those images are packaged; the GPU behavior remains unmeasured.
