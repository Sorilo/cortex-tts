# Source and model provenance

The original Python code in this repository is MIT licensed. The protocol and
request-lifecycle design were adapted from
[Sorilo/wyoming-s2cpp-tts](https://github.com/Sorilo/wyoming-s2cpp-tts)
at commit `7752a628171d5b49b1d27a989127977fdb00a4ee` (MIT). This repository
does not vendor the Fish Speech model or s2.cpp backend.

The backend build uses
[HoppouAI/Breeze-TTS-2.cpp](https://github.com/HoppouAI/Breeze-TTS-2.cpp)
at commit `8622f794bfe81649246ff908c8ca9247d9438556` under Apache-2.0,
including its upstream dependencies at pinned submodule revisions.

The Breeze TTS 2 model weights, derivative checkpoints and self-hosted outputs
are governed by the BreezeBlue Research and Non-Commercial License. That
license is distinct from the source code licenses. The downloader pins the
community Q4 GGUF at `81b22bad9f05b99970e30c5ee5e4bbc52fedf2f8` and the
official codec at `3e28c5151381a722f1d8661b4118c298caa77aa4`.
