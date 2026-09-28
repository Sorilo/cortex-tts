# Work state

Goal: standalone Breeze wrapper/backend repo; Cortex and Pi work untouched.

Source pins: Fish reference `7752a628171d5b49b1d27a989127977fdb00a4ee`;
Breeze C++ `8622f794bfe81649246ff908c8ca9247d9438556`;
Q4 GGUF `81b22bad9f05b99970e30c5ee5e4bbc52fedf2f8`;
official codec `3e28c5151381a722f1d8661b4118c298caa77aa4`.

Decision: backend owns phrase splitting and saved reference encoding; wrapper
owns bounded admission, protocol adaptation and session lifetime. Vulkan is
the initial backend because upstream reports it faster than CUDA for this
implementation's small per-frame graphs.

Independent evidence: 20 fake-backend/transport tests; Compose config;
wrapper and pinned Vulkan backend builds; runtime `ldd`; SHA-256 verified Q4
and codec files; CPU-only real-Q4 HTTP/Cortex/Wyoming streaming and synthetic
saved-voice cloning. See docs/VALIDATION.md for measured CPU timings.

Owner authorized an isolated GPU window. Q4, Q6 and Q8 now run on Vulkan0 of
the dev RTX 3080; the runtime image selects NVIDIA's headless EGL ICD to avoid
silent CPU fallback. Q4 warm short TTFA is about 0.19 s, more than 2× real-time
for the tested saved voice, with about 2.9 GiB peak GPU use alone. Q4 plus
active pinned Wyoming base.en or distil-small.en uses under 4 GiB observed peak.
Short+long startup warmup hides common first-request shader compilation behind
readiness (20.0 s on this RTX 3080). New text shapes can still cause a slower
first response. See docs/VALIDATION.md for sample sizes and caveats.

Remaining: human listening/quantization quality judgment, real playback
underrun measurement and physical integration.
Existing `cortex-dev`
containers must remain untouched. Stop only our isolated GPU test resources.

GitHub repository: https://github.com/Sorilo/cortex-tts. First pushed commit
`8f4291087b082a218452b7f743354d0dab17717d`; initial remote CI passed.
The first alpha image workflow failed before build because GHCR paths had a
mixed-case owner; the path was corrected for alpha.2.

Alpha.2 was published successfully from `d0e7ffce53cce16ecf0bb2c99f3af347a08cc061`.
Backend digest: `sha256:953f6229d3cbb94fb5d2bb69a672a8e7baa64b8f191ec03b5fccdc43ba768896`.
Wrapper digest: `sha256:908eea62ba2a0a33fde1e1eaf8be695707072923119c34d3bb38922fd43ab47d`.
The digest-pinned release Compose file is separate from the local-build stack.
Alpha.2's backend image predates the headless EGL fix.
Alpha.4's GitHub-built backend exited SIGILL on this host (native CPU tuning
from the CI runner). The backend Dockerfile now sets `GGML_NATIVE=OFF` and
`GGML_AVX512=OFF`; a local portable rebuild ran Q4 on Vulkan0 and streamed
audio, with warm TTFA 185 ms. The published alpha.5 image passed the release
smoke and soak below.
Alpha.5 published backend and wrapper passed an isolated release Compose smoke
and a 100-request Q4 soak alongside 150 synthetic Whisper base.en requests;
observed combined peak was 3,618 MiB. See docs/VALIDATION.md. One cancellation
metric counted the client closing after `cancelled` as a failure; the Cortex
stream now treats `cancelled` as terminal and has a regression test. The
alpha.6 wrapper is published and the final release Compose pins its immutable
digest with the verified alpha.5 backend. That exact pair passed readiness,
cancelled in 213 ms with no stale audio, reported `failures:0`, and completed
a fresh next turn. Final source and image checks are recorded in
docs/VALIDATION.md.

The published digest-pinned pair also produced PCM before a second text piece
arrived in a real delayed-input test; 10 queue probes measured about 0.75 s
admission delay for an intentionally 0.75 s occupied slot. A versioned varied
synthetic corpus completed 16 default, eight voice-design, eight saved-clone,
and eight directed-clone turns. A locally generated 6.24 s WAV served as the
clone reference. Cold text/voice shapes had isolated TTFA/speed outliers; warm
repeats were about 2× real time. Eight generated outputs were checked through
isolated pinned Whisper base.en and recovered the intended words. These checks
do not replace owner listening or real playback. Local files are ignored under
`evidence/local/`. Only the `cortex-tts-incremental-check` test project may be
stopped; other Cortex containers remain untouched.

Follow-up varied-text soak: 80 additional Q4 turns with isolated pinned
Whisper base.en resident completed over 257.2 s, emitting 523.2 s of PCM.
Median/p95 TTFA was 187/196 ms; after the first corpus cycle, all turns were
at least 1.91× real time. All three isolated containers had zero restarts.
This supports sustained synthetic throughput, not physical playback quality.

The Cortex wrapper now classifies malformed client input as one terminal
`code:protocol` event rather than sending a second backend error. Three new
regressions verify slot recovery. Alpha.7 wrapper image published at OCI index
`sha256:1afd3d6d1b45cad446e89404712212a9601432d3e1d734f71e5b1fc211280ce1`;
release Compose now pins it. Alpha.7 CI and image publication passed. An
isolated published-image Q4 smoke returned one protocol error and a clean next
turn, with `failures:1`, zero restarts and backend GPU residency. Earlier
latency distributions are from alpha.6 and should not be relabeled alpha.7.

Continuity finding: added packet-timed fill-level playback simulation to the
stream client and varied-corpus benchmark (21 local tests now pass). Two
independent alpha.7/Q4 first-shape eight-case runs after separate backend
restarts each showed idealized underruns in weather and multi-sentence turns.
A measured 1.25 s fill did not eliminate both; a 2.0 s fill eliminated them
in one run but modeled median/p95 audible start at 1.20/2.42 s. A later
16-turn shape-warm run had no modeled underruns even at zero buffer. Physical
playback and low-latency audible starts remain unresolved. Use a measured
fill-level queue in the future Cortex playback client; do not claim first PCM
arrival is equivalent to sound from the device.

Generic prewarm experiment: three different short/multi-sentence phrases on a
fresh published alpha.7/Q4 stack did not remove weather or multi-sentence
first-user gaps (2.742 s and 1.198 s largest packet gaps; two modeled
zero-buffer underrun requests). The exact synthetic prewarm corpus is tracked
under `benchmarks/`; local measurements stay ignored. Do not add more generic
startup phrases without evidence of generalization; current service-side
first-shape continuity remains unresolved.

Message-boundary diagnostic: the pinned backend drains completed sentences on
each `text` event. The same complete weather wording sent in one message after
a fresh start had no modeled underrun; split-message weather had one in the
cold corpus. Added `--combine-pieces` to the benchmark. Two independent fresh
eight-case combined-message Q4 runs had zero modeled underruns, first-packet
p95 442/437 ms and minimum speed 1.48×/1.54×. Two split-message cold runs
had two underrun requests each. The integration guide now tells Cortex to
send already-complete Core-authorized speech in one `text` message, preserving
literal incremental chunks only when speech truly arrives that way. Long-reply
inter-packet gaps still warrant real playback tests. No runtime coalescing or
extra startup warmup was added.

Chunk-first tuning: new `scripts/benchmark_cancel.py` repeats real
cancel-after-first-PCM and fresh-turn recovery. Published backend binary at
four-frame default missed the 250 ms cancel goal at p95 285 ms (20 pairs).
Two-frame override reached p95 121 ms (20 pairs alone) and 138 ms (20 pairs
with active pinned Whisper base.en), though one active-STT cancel took 345 ms.
Warm/fresh combined-text Q4 corpus remained >1.5× real time with zero modeled
underruns; observed active-STT peak was 3,695 MiB. One-frame override cut
cancel p95 further to 93 ms under STT load, but introduced extra modeled
zero-buffer gaps in warm combined and cold split-message speech; a 0.32 s
fill removed warm combined gaps in simulation. Set the provisional default to
two frames in backend Dockerfile and both Compose files; expose first/max
chunk settings in `.env.example`. The next gate is audible quality and real
playback on Satellite.

Alpha.8 backend published at OCI index
`sha256:c8b2411666e60b76665f694f3f8c9d6bcf01a20f845f6dee33a1bbf28cd46a67`.
Release Compose now pins it with the verified alpha.7 wrapper index
`sha256:1afd3d6d1b45cad446e89404712212a9601432d3e1d734f71e5b1fc211280ce1`.
The exact pair passed isolated RTX 3080 readiness, Wyoming output, a fresh
eight-case combined-message corpus (first PCM median/p95 124/303 ms, minimum
1.567× speed, zero modeled underrun requests) and 20 cancel/recovery pairs
(cancel median/p95 115.5/121.8 ms, maximum 121.9 ms; 20/20 recoveries).
No other Cortex deployment was changed. See docs/ROLLBACK.md for digest-pinned
fallback. Human listening, physical Satellite playback and Core integration
remain open gates; retain the active goal.

The exact published pair also passed isolated active Whisper `base.en`
coexistence: eight fresh combined-message Q4 turns had first-PCM median/p95
145/157 ms, minimum 1.527× speed and zero modeled zero-buffer underrun
requests while 159/159 synthetic clips were transcribed. Observed peak was
3,725 MiB. A separate 20-pair cancel/recovery run under active STT had cancel
median/p95/max 130/155/163 ms, 20/20 fresh turns and 126/126 STT probes;
peak was 3,697 MiB. All three containers had zero restarts and the isolated
stack was stopped. These results do not erase the earlier 345 ms active-STT
cancel outlier or prove physical playback and human-rated quality.

The exact published pair passed isolated expressive-mode testing too: a
service-generated 3.92 s exact-transcript WAV was saved and discovered as a
synthetic clone. Eight combined-message turns each of voice design, saved
clone and directed clone completed above 1.6× real time with no modeled
zero-buffer underruns. First-PCM median/p95 was 124/373 ms, 152/2462 ms,
and 151/166 ms respectively. The clone's first long-reply shape caused the
2.462 s outlier; an exact repeat began at 0.328 s. No service restarted.
Human judgment of similarity, pronunciation and direction remains pending.

Backend disconnects were incorrectly labeled `code:protocol` by the Cortex
wrapper; backend-originated errors lacked a consistent `code:backend`. A
separate BackendError now distinguishes server failures from client protocol
errors. The Wyoming path catches it and reports `breeze_error`. The full local
suite passes 22 tests. A locally built wrapper plus published alpha.8 backend
survived an immediate isolated backend restart: the interrupted turn got one
terminal backend error, no stale PCM, and a fresh turn completed. The first
post-restart turn took 11.28 s to first PCM despite `/readyz` returning 200;
an exact warm repeat took 0.424 s. This cold-recovery limitation is documented
in docs/VALIDATION.md. Publish and verify an immutable alpha.9 wrapper, then
pin its digest in release Compose; physical playback remains pending.
