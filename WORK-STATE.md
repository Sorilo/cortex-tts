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
in docs/VALIDATION.md. Alpha.9 wrapper published at OCI index
`sha256:4e72820923e0b85975b14f269992bc942e3b7257a94cc2244ed37356cf25652a`;
the digest-pinned release pairs it with the verified alpha.8 backend. The
exact published pair passed an isolated immediate backend-restart check: one
correlated terminal backend error, zero late PCM, a fresh 111,360-byte turn
and a subsequent Wyoming synthesis. Tag tests and image publication passed;
see docs/ROLLBACK.md for the prior verified pair. Physical playback and
owner listening remain pending.

Published alpha.8/alpha.9 was started again with the prior synthetic saved
voice volume. The profile survived the earlier stack removal, appeared in
Cortex `/v1/voices` and Wyoming Describe, and produced 126,720 PCM bytes
without re-upload. A first short cloned turn started PCM at 2.98 s and was
0.63× generated audio / wall time; an exact repeat started at 0.456 s and was
1.59×. This is a first-use latency caveat, not a persistence failure. The
dedicated test stack was stopped; other Cortex resources remained untouched.

Recovery warmup fix: the alpha.9 wrapper could report `/readyz` healthy while
the first post-restart turn still took 11.3 s to first PCM. The new wrapper
watcher detects observed backend outages or stream failures, holds readiness
at 503, rejects new turns with `code:backend` while warming, and re-runs the
short/long warmup under the synthesis lock. Local tests now pass 23/23. On
the RTX 3080 with the immutable alpha.8 backend, one immediate midstream
restart kept readiness unavailable for 24.26 s and the next completed turn
began PCM in 120 ms; one idle restart kept readiness unavailable for 26.16 s
and the next turn likewise began at 120 ms. Both tests used the local wrapper
image and were isolated/stopped. The published-image verification below
confirms the same recovery behavior; human listening and physical integration
remain open gates.

Alpha.10 wrapper published at OCI index
`sha256:192b16de727635df8ad1b194636df0b0641cb06995306f614816e12dfa9b91d9`
and release Compose pins it with the verified alpha.8 backend. The exact
published pair passed both immediate midstream and idle backend-restart
checks: readiness stayed 503 for 24.00/24.24 s, the next completed turns
started PCM in 120/119 ms, and the interrupted turn emitted one correlated
backend error with no stale audio. The isolated project was stopped; other
Cortex containers remain untouched. Owner listening and physical Satellite
integration are still open gates.

The pinned alpha.8/alpha.10 release pair also passed a 48-request shared-GPU
run with actively transcribing pinned Whisper `base.en`: eight Q4 combined-
message corpus turns had first-PCM median/p95 138/154 ms, minimum 1.558×
speed and zero modeled zero-buffer underrun requests; 20 cancellation/fresh-
turn pairs had cancel median/p95/max 128/139/157 ms with 20/20 recoveries.
Whisper transcribed 276/276 generated-clip probes, observed peak GPU use was
3,726 MiB, 111/111 readiness probes stayed healthy, and all three isolated
containers had zero restarts. The test project was removed afterward. See
docs/VALIDATION.md for workload and measurement limits.

Read-only Cortex handoff audit at Core `5ed4d07cec56fca89954ac377ef4b5162b4c0c61`
and Deploy `3cf01af1e7abd96e3f5b9798a50907cc05924a12`: Core GET returns
`speech_text` and may return null; the current HA voice agent waits terminal
states, while Core can also author an `awaiting_approval` phrase. The
development fake bridge returns a full eSpeak WAV; the dedicated HA pipeline
has no TTS engine selected and the conversation agent itself is not the PCM
playback transport. Updated docs/CORTEX-INTEGRATION.md to name the real
handoff paths and keep adapter-authored failure phrases out of Breeze until
their authority is explicitly reviewed. No Core/Deploy files were edited.

Added an opt-in trusted-client Core-to-TTS example in
`scripts/core_turn_client.py`. It polls authenticated Core turn GETs, validates
`audio_turn_id` and stable `action_id`, ignores partial/model text, and sends
one nonempty Core `speech_text` message to the existing streaming client.
Approval-pending speech is opt-in; playback cancellation never calls Core's
action interrupt. Six new synthetic Core-result gate cases plus one end-to-end
fake-Core/fake-backend wrapper path bring the local suite to 30 passing tests.
No Core, HA, Satellite, or other repo was modified.

Validated the new trusted Core turn client against the published alpha.8/Q4
backend and alpha.10 wrapper pair in an isolated `cortex-tts-release` project.
An authenticated fake Core moved from `admitted` with null speech to a
terminal authorized result; the real wrapper streamed 84,480 PCM bytes.
Ten further same-text turns completed above real time, with 117/344 ms
median/p95 first PCM after text and no idealized zero-buffer underruns.
The RTX 3080 Vulkan backend was confirmed by log and GPU process ownership.
Recorded synthetic limits in `docs/VALIDATION.md`; ignored JSON/WAV evidence
stays under `evidence/local/`. The isolated project is down and its temporary
token file was removed. Physical playback and human sound judgment remain open.

The trusted Core turn Python client now accepts an async `on_audio` callback
that receives each PCM packet before `done`, allowing a coordinated playback
transport to enqueue audio immediately. The streaming client stores complete
PCM only when writing a WAV, keeping long callback-only turns memory-bounded.
The fake-Core/fake-backend wrapper test holds completion until after the first
callback and verifies that PCM was delivered while synthesis was still active.
A separate WAV regression test keeps file output covered after removing the
unneeded in-memory accumulation on callback-only turns; 31 local tests pass.
No physical Satellite transport was changed or claimed validated.

Added an external `asyncio.Event` cancellation input to the trusted Core turn
client and streaming receive helper. It sends TTS `cancel` without waiting for
another packet, stops delivering PCM callbacks once set, and leaves Core action
interrupt untouched. Synthetic tests cover cancellation before first PCM and
after a callback, with TTS acknowledgement and no Core POST. The local suite
now has 33 passing tests. Physical speaker queue clearing and barge-in timing
remain for coordinated Satellite validation.

Validated external `cancel_event` end-to-end against the published alpha.8/Q4
backend and alpha.10 wrapper in an isolated RTX 3080 Vulkan project. Ten
cancel-after-first-callback/fresh-turn pairs completed: event-to-return
median/p95/max 116/121/121 ms, ten acknowledgements, no later PCM callbacks or
post-cancel PCM, and 10/10 fresh recoveries. Fake Core saw only 20 GETs; no
action-interrupt POST. Recorded exact source/image pins and synthetic limits in
`docs/VALIDATION.md`; ignored JSON is under `evidence/local/`. The isolated
containers were stopped and temporary test tokens removed. Owner listening
and physical Satellite barge-in remain unverified.

Extended the trusted client's `cancel_event` over Core polling, so a barge-in
before authorized speech promptly ends the local playback attempt rather than
opening a stale TTS session later. It raises `PlaybackCancelled`, distinct from
Core action cancellation; a pending GET and poll sleep are both interruptible.
Three synthetic tests cover pre-GET, in-flight GET and between-GET cancellation,
with no TTS request. The suite now has 36 passing tests; physical integration
remains outside this standalone repo.

Prepared a broader local Q4/Q6/Q8 listening pack on the published alpha.8/
alpha.10 digest pair. Four identical complete-message prompts per model cover
numbers, names, punctuation joins and a long reply. All twelve turns completed
above real time with zero idealized zero-buffer underrun requests in this run.
The tracked `benchmarks/listening_corpus.json` and
`scripts/prepare_listening_pack.py` reproduce the corpus and volume-matched
review copies under ignored `evidence/local/`; `docs/LISTENING.md` explains
the owner review. `BREEZE_MODEL_FILE` now selects Q6/Q8 in an isolated Compose
run while unset still defaults to Q4. Isolated containers and temporary tokens
were removed. One stochastic sample per prompt cannot establish perceived
quality; owner listening and physical Satellite validation remain open.

Ran the same four-prompt listening corpus under active, pinned Wyoming
`distil-small.en` STT for each published Q4/Q6/Q8 backend variant. Separate
isolated Compose runs produced first-PCM median/max 153/216, 167/224 and
158/224 ms; slowest generation 1.453×, 1.426× and 1.386×; sampled combined
GPU peak 3,951/4,459/4,917 MiB. All twelve TTS turns completed with zero
idealized zero-buffer underrun requests; 342/342 repeated STT probes exactly
transcribed the synthetic timer WAV. Every isolated container had zero
restarts, and temporary tokens/port override were removed. Q8 narrowly meets
the 5 GiB combined target in this workload; none guarantees the preferred
1.5× floor. Added `scripts/benchmark_active_stt.py` as a reproducible
concurrency/VRAM measurement helper. See `docs/VALIDATION.md`; owner sound
judgment and physical Satellite playback remain open.
The tracked helper was also exercised on one published Q4 prompt with active
distil-small STT: it captured TTS, ten memory samples and 12/12 expected
transcripts. Its isolated stack was stopped and temporary token removed.

Read-only Satellite source audit at main
`d332fb3da791c0c53106ef46a41715ba14079c33`: Satellite Python supervises
pinned Linux Voice Assistant; LVA and the selected HA Assist pipeline own TTS
interaction and speaker playback through `pipewire/<playback_sink>`. The first
physical Breeze path is an isolated HA Wyoming TTS pipeline after speech
authority gating. The standalone Core turn client's progressive PCM callback
does not feed current Satellite playback; direct PCM requires a separate
coordinated design. Updated `docs/CORTEX-INTEGRATION.md` and
`docs/VALIDATION.md`. No Satellite, HA, Pi or other Cortex repository was
changed. Owner listening, the isolated HA pipeline, physical playback and
barge-in remain open.

Bounded the wrapper's first-audio timing history to its 20 published recent
samples. Previously the list grew for every request over the service lifetime.
Added a retention regression; 37 local tests pass. Version advanced to
alpha.11 for a publishable wrapper build. The release Compose digest is still
alpha.10 until the new image has been published and validated.

Alpha.11 publication and isolated Q4 smoke succeeded. Wrapper OCI index
`sha256:8074f07a6a3a7daf105407c7bd70bcdb867a34a04c9c7941339a100c0dcfdd43`
was tested with the existing alpha.8 backend digest on dev RTX 3080; one
synthetic turn returned 2.08 s PCM in 1.28 s with first PCM at 390 ms.
Metrics had one recent sample, one request, zero failures; both containers
had zero restarts. This is a packaging/behavior smoke, not a new latency
distribution, active-STT, listening, or physical test. Updated release Compose,
README, rollback and validation docs to the tested pair. The isolated project
and temporary token/voice files were removed.

Added a blind local listening handoff for the existing Q4/Q6/Q8 matched pack.
`scripts/make_blind_listening_review.py` verifies each matched WAV against its
recorded hash, copies audio bytes unchanged under ignored
`evidence/local/listening-pack-blind/`, and writes an A/B/C browser page plus
a separate answer key. The local page was generated from all twelve existing
samples; owner quality judgment and physical playback are still outstanding.

Added a 12,000-character cumulative session text budget to Cortex and Wyoming
on top of their existing 2,000-character per-message bound. Previously many
small chunks could enqueue unlimited text; Wyoming legacy synthesis also
skipped the per-message check. Overflow now ends that request, closes the
backend session, and permits a new turn. Focused recovery tests pass and the
full local suite has 40 passing tests. Documented fixed start controls versus
next-piece `instruction` updates. Version advanced to alpha.12; release image
pin remains alpha.11 pending publication and isolated smoke.

Alpha.12 wrapper OCI index
`sha256:6d9255a48a8ccee02c32f4a28f20a23456e772eae0fece2059457b97d2be05c3`
passed an isolated published-image overflow/fresh-turn smoke with the tested
alpha.8 backend on dev RTX 3080. Seven 2,000-character frames yielded one
terminal protocol error and no PCM; a fresh turn returned 2.08 s PCM with
first packet at 312 ms. The wrapper was healthy; both containers had zero
restarts. Updated release pin, rollback and validation records. The temporary
project and token were removed. Alpha.12 image publication succeeded, and
release-pin CI passed for `9d8a3c077e070b51865bc82b778b1e6fc4e453d5`
(GitHub Actions run `36406916923`).

Closed a Wyoming streaming lifecycle gap: after `synthesize-stop`, later chunks
or duplicate stops previously entered an unconsumed command queue while the
backend finished. They now produce a terminal protocol error, cancel and close
the backend, and permit a fresh request on the same connection. The full local
suite passes 42 tests. Version advanced to alpha.13; the alpha.12 release pin
remains until publication and isolated published-image validation.

Alpha.13 image publication and isolated RTX 3080 Wyoming smoke succeeded.
Published wrapper OCI index
`sha256:6e95299fc245e8d5d28900aedc31a80692a127b769b5c2b524887aae8e074fa0`
with the tested alpha.8 backend rejected late chunk and duplicate stop with
terminal protocol errors, then completed fresh same-connection syntheses
(76,800 PCM bytes each). Neither rejected request reached backend admission;
metrics increased only for the two fresh turns. Both containers had zero
restarts. Release Compose and rollback records now pin the tested pair. The
isolated project, token, and temporary voices were removed. Human listening
and physical Satellite integration remain open.

Measured current published alpha.8-backend/alpha.13-wrapper paired overhead on
the authorized dev RTX 3080. With Q4 and the benchmark's fixed two-sentence
prompt, two shape-warm pairs were discarded, then 20 direct/wrapper pairs
alternated order. Client first-PCM direct median/p95 116/120 ms, wrapper
117/122 ms; paired wrapper overhead median/p95 1.3/5.0 ms. All 40 measured
turns returned identical 165,120-byte PCM lengths, exceeded 1.93× real time,
and had zero idealized zero-buffer underrun requests. Both containers had zero
restarts. This meets the 25 ms p95 target for this workload only; active-STT,
diverse-text, and physical playback overhead remain unmeasured. Detailed
ignored JSON and limitations are in `docs/VALIDATION.md`. The isolated stack,
loopback port, token and voice directory were removed.

Extended the active-STT benchmark helper with `--voice` and `--instruction`.
Ran current published Q4 alpha.8-backend/alpha.13-wrapper with isolated pinned
`distil-small.en` actively transcribing throughout three four-prompt expressive
modes. A known-text synthetic 3.52 s reference was generated and uploaded as
`synthetic_active13`. Design/clone/directed-clone first-PCM medians were
136/188/179 ms; sampled combined peaks 3,972/3,958/3,960 MiB; all modes
generated above real time with zero idealized underrun requests and 325/325
exact STT probes. The clone's first long-reply PCM took 2,411 ms; an exact
active-STT repeat took 231 ms and added 70/70 exact probes. All three
containers had zero restarts and wrapper metrics showed zero failures.
See `docs/VALIDATION.md` for exact pins and limits. The isolated stack, token,
temporary ports, and synthetic profile were removed. Human expressive-quality
judgment and physical playback remain open.

Prepared a concrete first-speaker acceptance protocol in
`docs/CORTEX-INTEGRATION.md` for the current HA Wyoming/LVA path. Read-only
Core, Deploy, and Satellite heads still match their previously audited pins.
The handoff requires authority gating of the HA adapter's fixed local phrases
before generic TTS selection, then measures Core result, HA/Wyoming events,
first audible speaker output, room separation, barge-in, receipts, active-STT
VRAM, and rollback. No HA, Satellite, Pi, or other Cortex repository was
changed. It is a plan for a coordinated physical window, not physical evidence.
