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
The corpus client also models zero-buffer and several fill-level playback cases
from observed PCM packet times; simulated playback start is distinct from first
packet arrival. `scripts/benchmark_stream.py` compares direct and wrapped paths,
records first audio, throughput and chunk gaps in ignored `evidence/local/`.
It does not yet infer actual playback buffer underruns; measure those with the
target playback client.

## Current independent checks (2026-09-28)

- Python package compiles; 23 local tests pass. They cover Cortex
  early audio, auth, voice upload/discovery, disconnect/cancel, Wyoming discovery,
  Wyoming legacy and incremental early audio, bounded admission, input limits,
  Wyoming stream timeout,
  terminal backend errors and abrupt backend disconnects, recovery after both
  failures, busy-slot isolation, queued admission order, a concurrently
  sending streaming client, and single terminal protocol errors for malformed
  JSON, out-of-order text and unknown message types, plus the playback
  fill-level simulation used by the corpus benchmark.
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
- Human listening, real playback-device underruns, far-field microphone audio,
  and physical Satellite/Core integration remain pending. The later 80-turn
  varied-text soak below covers several minutes but not an overnight run.
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
- The release Compose previously pinned the verified portable alpha.5 backend OCI
  index `sha256:0ace2780f6a5b4f47fe4ca5b977db83c09e51bdd38f4c9a5a1f6df023262e65e`
  and alpha.6 wrapper index
  `sha256:39ed6a01f908de63554ab37bc37c3862ec22b929ef860a92a47bfa5cf2699144`.
  This exact pair passed isolated Compose readiness on the RTX 3080. A published
  cancellation acknowledged in 213 ms with zero post-cancel audio; metrics
  showed `cancelled:1`, `failures:0`, `active:false`, `queued:0`. A fresh next
  turn produced 188,160 PCM bytes and completed normally. This verifies the
  cancellation fix in the published wrapper, not only in the local tests.
- The earlier release Compose retained the verified alpha.5 backend and pinned the
  published alpha.7 wrapper OCI index
  `sha256:1afd3d6d1b45cad446e89404712212a9601432d3e1d734f71e5b1fc211280ce1`.
  Alpha.7's CI tests and image publication passed. An isolated published-image
  RTX 3080 smoke returned one terminal `code:protocol` event for malformed
  JSON, closed the stream, then completed a fresh Q4 turn (153,600 PCM bytes,
  3.2 s audio, first audio 376 ms, 1.86× real-time client ratio). Metrics were
  `requests:2`, `failures:1`, `active:false`, `queued:0`; both containers had
  zero restarts and the backend owned 2,957 MiB of GPU memory. One smoke turn
  does not re-establish the earlier latency distribution for the new wrapper.
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
- An additional 80-turn Q4 default-voice soak repeated the eight-case corpus
  ten times with isolated pinned Wyoming Whisper `base.en` resident. All turns
  completed, with no backend, wrapper or Whisper container restart. The run
  produced 523.2 s of PCM over 257.2 s of client wall time; first-audio
  median/p95 was 187/196 ms. First-cycle shape warmups included one 657 ms
  first audio and a 1.16× real-time slowest turn. Across cycles 2–10, the
  slowest turn was 1.91× real time. Whisper was resident, not actively
  transcribing during this particular soak; the prior 100-turn repeated-text
  run exercised active STT. This corpus remains synthetic and does not measure
  physical-device underruns or human-rated speech quality.
- Packet-level timing on the current alpha.7-wrapper/alpha.5-backend published
  pair exposed a remaining continuity tradeoff. In two independent eight-case
  first-shape runs after separate backend restarts, the weather and
  multi-sentence cases each had one idealized zero-buffer underrun. One run's
  largest packet gap was 2.76 s; its total modeled underrun was 1.47 s. A
  1.25 s fill still left both requests with a modeled underrun. A 2.0 s fill
  eliminated them in that run, but raised modeled playback start to median/p95
  1.20/2.42 s. A separate 16-turn shape-warm run had zero modeled underruns
  at every tested fill level; immediate-playback median/p95 first packet was
  187/194 ms, while a 1.0 s fill began at 719/760 ms. The local client models
  ideal PCM scheduling only. It does not account for device jitter, playback
  implementation or arbitrary novel text shapes. Thus first-packet latency
  passes its warm target in these runs, but low-latency *audible* playback with
  no underruns remains unproven and may require a larger buffer or backend
  first-shape optimization.
- A generic prewarm experiment on a fresh alpha.7/Q4 stack ran the three
  synthetic prompts in `benchmarks/generic_prewarm_experiment.json` after the
  built-in startup warmup and before the eight-case corpus. It did not remove
  first-user gaps: weather still had a 2.742 s largest packet gap and 0.768 s
  modeled zero-buffer underrun; multi-sentence still had a 1.198 s largest gap
  and 0.345 s modeled underrun. The corpus had two underrun requests and a
  1.128× slowest request. These different but similar-length warmups did not
  generalize across the tested text; they are not added to startup. Reproduce
  by running `scripts/benchmark_corpus.py --corpus
  benchmarks/generic_prewarm_experiment.json` once, followed by the default
  corpus once, against a newly started isolated release stack. Results remain
  under ignored `evidence/local/`.
- Message boundaries were then isolated with the unchanged published images.
  The pinned backend drains complete sentences as each `text` message arrives;
  a single message containing several sentences can become one synthesis piece
  below its length budget. On two independent fresh-backend eight-case runs,
  `scripts/benchmark_corpus.py --combine-pieces` joined each case's available
  sentences with spaces and sent one `text` message. Both runs had zero
  idealized zero-buffer underruns, first-packet median/p95 190/442 and
  187/437 ms, and minimum request speeds 1.48× and 1.54× real time. The
  comparable split-message first-shape runs each had two underrun requests.
  The combined runs still had a largest inter-packet gap around 2.77 s on the
  long reply, but previously delivered PCM covered that gap in the model.
  One cold single-message weather request separately had a 0.669 s largest
  gap and no modeled underrun. These results support sending an already-complete
  Core-authorized response as one message. They do not prove arbitrary
  incremental speech, device playback or naturalness is free of gaps.
- First-chunk tuning used the unchanged published backend binary with isolated
  Compose command overrides. At four frames, 20 cancel/fresh-turn pairs had
  client-observed cancel median/p95 221/285 ms (maximum 293 ms): all fresh
  turns completed, zero PCM arrived after the cancel request, and metrics
  showed 20 cancellations with zero failures. At two frames, 20 comparable
  pairs had median/p95 116/121 ms (maximum 123 ms). With isolated pinned
  Wyoming `base.en` actively transcribing 60 synthetic commands, another 20
  two-frame pairs had median/p95 120/138 ms; one 345 ms outlier exceeded the
  250 ms goal, so the bound is not unconditional. All 40 two-frame fresh turns
  completed and both STT batches transcribed 60/60 exact commands.
- Two-frame Q4 combined-message corpus runs completed above real time: 16
  shape-warm turns had first-packet median/p95 123/126 ms, minimum speed
  1.56× and zero idealized zero-buffer underruns; eight fresh-shape turns had
  123/295 ms, minimum 1.62× and zero modeled underruns. With `base.en`
  actively transcribing 60 generated commands, 16 further combined turns had
  126/135 ms, minimum 1.75×, zero modeled underruns and 3,695 MiB observed
  peak GPU memory in 150 samples. All three isolated containers had zero
  restarts. A fresh split-message corpus still had two of eight idealized
  zero-buffer underrun requests; chunk tuning does not fix phrase boundaries.
- One-frame exploratory tuning lowered 20 active-STT cancel/fresh-turn pairs
  to median/p95 85/93 ms (maximum 94 ms), but 16 warm combined turns had six
  tiny idealized zero-buffer underruns totaling 27 ms. A modeled 0.32 s PCM
  fill eliminated them and began playback at median/p95 285/311 ms. A fresh
  combined run had 0.32 s-fill playback 281/464 ms, zero modeled underruns
  and minimum 1.56× speed. A fresh split-message run had four of eight
  zero-buffer underrun requests, versus two of eight with two-frame chunks.
  Active `base.en` transcribed 60/60 commands and observed peak memory was
  3,684 MiB. Two frames is the provisional default pending physical playback
  and human listening; one frame remains an opt-in experiment.
- Alpha.8 source tests and image publication passed for commit
  `d92d270c9524ff516a6adc111596be90fc44d5f1`. Current release Compose pins
  the published alpha.8 backend OCI index
  `sha256:c8b2411666e60b76665f694f3f8c9d6bcf01a20f845f6dee33a1bbf28cd46a67`
  with the previously verified alpha.7 wrapper index
  `sha256:1afd3d6d1b45cad446e89404712212a9601432d3e1d734f71e5b1fc211280ce1`.
  The published backend's image command and the isolated release Compose both
  use `--chunk-first 2 --chunk-max 25`. On the RTX 3080, this exact published
  pair passed readiness and Wyoming synthesis (AudioStart, five AudioChunks,
  AudioStop; 84,480 PCM bytes). An eight-case fresh Q4 combined-message corpus
  had first-PCM median/p95 124/303 ms, minimum 1.567× real-time generation,
  and zero idealized zero-buffer underrun requests. Twenty cancel-after-first-
  audio/fresh-turn pairs had cancel median/p95 115.5/121.8 ms, maximum
  121.9 ms, zero PCM received after each cancel request and 20/20 completed
  recoveries. Metrics after the corpus and pairs showed 48 requests, 20
  cancellations, zero failures, no active or queued request. Both containers
  had zero restarts; the backend owned about 2,957 MiB of GPU memory. These
  checks establish the shipped digest pair's synthetic behavior, not physical
  Satellite playback or human-rated sound quality. Reproduction output is
  ignored under `evidence/local/corpus-published-alpha8-q4-cold-combined/`
  and `evidence/local/cancel-published-alpha8-q4-20.json`.
- The same immutable alpha.8-backend/alpha.7-wrapper pair was then run with
  the pinned isolated LinuxServer Wyoming Whisper `base.en` container actively
  transcribing a repository-generated 3.92 s WAV. In one fresh eight-case Q4
  combined-message corpus, first-PCM median/p95 was 145/157 ms, minimum
  generation speed was 1.527× real time, and there were zero idealized
  zero-buffer underrun requests. Whisper returned the expected transcript on
  159/159 probes during that corpus; 137 GPU samples observed a 3,725 MiB
  peak. In a separate 20-pair cancel-after-first-audio/fresh-turn run, cancel
  median/p95/max was 130/155/163 ms, all 20 fresh turns completed, and the
  benchmark asserted zero post-cancel PCM. Whisper transcribed 126/126 probes
  during that run; 107 GPU samples observed a 3,697 MiB peak. Final wrapper
  metrics counted 48 requests, 20 cancellations, zero failures and no active
  or queued request. Backend, wrapper and Whisper had zero restarts; the
  dedicated stack was removed afterward. The earlier isolated two-frame run
  did observe a 345 ms cancellation outlier under active STT, so this new run
  improves confidence but cannot establish a hard 250 ms bound. The playback
  model excludes device scheduling and arbitrary text. Local evidence is in
  `evidence/local/corpus-published-alpha8-q4-active-base/`,
  `evidence/local/published-alpha8-active-base-summary.json`, and
  `evidence/local/cancel-published-alpha8-q4-active-base-20.json`.
- The published alpha.8-backend/alpha.7-wrapper pair also passed expressive
  modes on the RTX 3080 without Whisper. A 3.92 s reference WAV was generated
  by this service from its exact transcript, uploaded through authenticated
  `POST /v1/voices`, and discovered through `GET /v1/voices` as
  `synthetic_alpha8`; no person or household recording was used. Across eight
  combined-message corpus turns per mode, design had first-PCM median/p95
  124/373 ms and minimum generation speed 1.63×, saved clone 152/2462 ms
  and 1.64×, and directed clone 151/166 ms and 1.99×. All 24 completed with
  zero idealized zero-buffer underrun requests, zero wrapper failures and zero
  container restarts. The clone p95 is the first 21.68 s long-reply shape:
  first PCM took 2.462 s; an exact repeat began at 0.328 s and generated at
  1.98× real time. This supports a first-shape cost, not a guaranteed warm
  bound. Audio artifacts and per-turn timing remain ignored under
  `evidence/local/published-alpha8-{design,clone,directed_clone}/`; the
  summary is `evidence/local/published-alpha8-expressive-summary.json`.
  Synthetic timing cannot establish clone similarity or direction fidelity;
  those still need listening.
- A local wrapper build against the immutable alpha.8 backend was tested with
  an immediate restart of only the isolated backend after first PCM. The
  interrupted Cortex turn received one terminal `code:backend` event with its
  original turn ID and no post-restart PCM; the slot released and a fresh turn
  completed with 111,360 PCM bytes. A regression test now distinguishes
  backend disconnects and backend-originated errors from malformed client
  input, and a Wyoming regression confirms a backend drop produces an Error
  event followed by a working new turn. The first fresh turn after restart
  began PCM in 11.28 s despite `/readyz` returning 200; an immediate exact
  repeat began in 0.424 s. Thus restart recovery works, but current readiness
  does not guarantee shader/shape warmup after a backend-only restart. The
  local run is `evidence/local/local-wrapper-restart-recovery.json`.
- Alpha.9 source tests and image publication passed for commit
  `d5860cd0d1255bf92065131f1883d8adb3c0b3e5`. The release Compose now
  pins its published wrapper OCI index
  `sha256:4e72820923e0b85975b14f269992bc942e3b7257a94cc2244ed37356cf25652a`
  with the verified alpha.8 backend index above. In an isolated published-pair
  RTX 3080 smoke, an immediate dedicated-backend restart after first PCM
  produced exactly one terminal `code:backend` event correlated to the
  interrupted turn, with zero later PCM. A fresh turn completed with 111,360
  PCM bytes; its first PCM took 11.29 s after the backend-only restart despite
  `/readyz` returning 200. A subsequent Wyoming turn returned AudioStart,
  five AudioChunks, AudioStop and 88,320 PCM bytes. Wrapper metrics counted
  two Cortex requests, one failure, no active or queued request; the wrapper
  itself did not restart. The isolated stack was removed. Published evidence
  is `evidence/local/published-alpha9-restart-smoke.json`. This confirms
  recovery and correct error classification, while preserving the cold-restart
  latency limitation and leaving physical playback unverified.
- The same published alpha.8-backend/alpha.9-wrapper pair was started in a
  new isolated project with the saved synthetic profile volume from the prior
  expressive run. Without re-uploading the reference, `GET /v1/voices`
  returned `synthetic_alpha8`, Wyoming Describe listed it alongside
  `breeze-design`, and a Cortex turn selecting that voice completed with
  126,720 PCM bytes. Its first-use first PCM was 2.98 s and its generated
  audio to total wall-time ratio was 0.63×; an exact repeat began at 0.456 s
  and ran at 1.59×. Both containers had zero restarts and the dedicated stack
  was removed. This verifies profile persistence and discovery across stack
  lifetimes, while showing the first-use saved-clone latency/throughput cost.
  Local evidence is `evidence/local/published-alpha9-persistent-clone.json`.
- The alpha.9 release exposed a restart-readiness gap: `/readyz` could be 200
  before its first recovered synthesis incurred about 11.3 s of cold Vulkan
  compilation. A local wrapper change now polls backend health, marks speech
  unready after an outage or backend stream failure, serializes the existing
  short/long warmup through the synthesis admission lock, and rejects new
  turns while warming. One new fake-backend test verifies a 503 readiness
  interval, a terminal backend-warming event for a new request, then restored
  readiness and speech. The local 23-test suite passes. With the immutable
  alpha.8 backend on the RTX 3080, an immediate midstream backend restart
  still yielded one correlated `code:backend` event and zero later PCM;
  `/readyz` returned 503 on 96 probes across 24.26 s of recovery, then the
  next 111,360-byte turn began PCM in 120 ms and generated at 2.02× real
  time. An idle backend restart similarly showed 99 unready probes across
  26.16 s, followed by a completed 111,360-byte turn with 120 ms first PCM.
  The watcher cannot prove detection of a restart too brief to be observed by
  its one-second health poll, and the current sample sizes do not establish
  a recovery-time SLA. Evidence is ignored under
  `evidence/local/local-wrapper-rewarm-{restart,idle-restart}.json`.
- Alpha.10 source tests and image publication passed for commit
  `64add88b8dfc1c503572aef848b15395704b8e84`. The current release
  Compose pins the published alpha.10 wrapper OCI index
  `sha256:192b16de727635df8ad1b194636df0b0641cb06995306f614816e12dfa9b91d9`
  with the verified alpha.8 backend index above. In an isolated published-
  pair RTX 3080 run, a midstream backend restart produced one correlated
  terminal `code:backend` event and zero late PCM. A new request during
  recovery received one `backend warming` error. Readiness remained 503
  for 95 probes over 24.00 s, then a fresh 111,360-byte turn started PCM in
  120 ms. An idle backend restart kept readiness 503 for 96 probes over
  24.24 s; the next 111,360-byte turn also started PCM in 119 ms. Metrics
  showed three accepted Cortex requests, one failure, no active or queued
  request. The wrapper had zero restarts and the dedicated stack was removed.
  These timings prove only the tested restart paths and local workload;
  evidence is `evidence/local/published-alpha10-rewarm-smoke.json`.
- Initial GitHub Actions wrapper test/Compose workflow passed at
  `8f4291087b082a218452b7f743354d0dab17717d`.
- Alpha.2 image workflow passed at `d0e7ffce53cce16ecf0bb2c99f3af347a08cc061`:
  backend `ghcr.io/sorilo/cortex-tts-backend@sha256:953f6229d3cbb94fb5d2bb69a672a8e7baa64b8f191ec03b5fccdc43ba768896`;
  wrapper `ghcr.io/sorilo/cortex-tts-wrapper@sha256:908eea62ba2a0a33fde1e1eaf8be695707072923119c34d3bb38922fd43ab47d`.
  Those images are packaged; the GPU behavior remains unmeasured.
