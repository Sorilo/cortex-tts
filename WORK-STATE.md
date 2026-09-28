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

Independent evidence: 17 fake-backend/transport tests; Compose config;
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

Remaining: human listening/quantization quality judgment, long-duration
diverse-text soak, real playback underrun measurement and physical integration.
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
