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

Independent evidence: eleven fake-backend/transport tests; Compose config;
wrapper and pinned Vulkan backend builds; runtime `ldd`; SHA-256 verified Q4
and codec files; CPU-only real-Q4 HTTP/Cortex/Wyoming streaming and synthetic
saved-voice cloning. See docs/VALIDATION.md for measured CPU timings.

Remaining: GPU performance/quality, Whisper coexistence, listening, soak and
physical integration. Existing `cortex-dev` containers are active; a blank GPU
compute-process snapshot is not exclusive access. Inspect current state before
updating or running on GPU.

GitHub repository: https://github.com/Sorilo/cortex-tts. First pushed commit
`8f4291087b082a218452b7f743354d0dab17717d`; initial remote CI passed.
The first alpha image workflow failed before build because GHCR paths had a
mixed-case owner; the path is corrected for alpha.2. GPU validation is still
pending.

Alpha.2 was published successfully from `d0e7ffce53cce16ecf0bb2c99f3af347a08cc061`.
Backend digest: `sha256:953f6229d3cbb94fb5d2bb69a672a8e7baa64b8f191ec03b5fccdc43ba768896`.
Wrapper digest: `sha256:908eea62ba2a0a33fde1e1eaf8be695707072923119c34d3bb38922fd43ab47d`.
The digest-pinned release Compose file is separate from the local-build stack.
