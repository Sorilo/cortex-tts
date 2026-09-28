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

Independent evidence: nine fake-backend/transport tests; Compose config;
wrapper and pinned Vulkan backend builds; runtime `ldd`; SHA-256 verified Q4
and codec files; CPU-only real-Q4 HTTP/Cortex/Wyoming streaming and synthetic
saved-voice cloning. See docs/VALIDATION.md for measured CPU timings.

Remaining: GPU performance/quality, Whisper coexistence, listening, soak and
physical integration. Existing `cortex-dev` containers are active; a blank GPU
compute-process snapshot is not exclusive access. Inspect current state before
updating or running on GPU.
