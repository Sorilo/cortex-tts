# Release rollback

`compose.release.yaml` is a separate Cortex TTS project. Its current tested
pair is the alpha.8 backend OCI index
`sha256:c8b2411666e60b76665f694f3f8c9d6bcf01a20f845f6dee33a1bbf28cd46a67`
and alpha.13 wrapper OCI index
`sha256:6e95299fc245e8d5d28900aedc31a80692a127b769b5c2b524887aae8e074fa0`,
with `BREEZE_CHUNK_FIRST=2` and `BREEZE_CHUNK_MAX=25`. The two-frame setting
was tested against the published alpha.8 image; read `docs/VALIDATION.md` for
the observed cancellation and continuity tradeoff.

To roll back only the wrapper, set `wrapper.image` in this project's
`compose.release.yaml` to the previously verified alpha.12 index
`ghcr.io/sorilo/cortex-tts-wrapper@sha256:6d9255a48a8ccee02c32f4a28f20a23456e772eae0fece2059457b97d2be05c3`.
Leave the alpha.8 backend digest and two-frame chunk setting unchanged. That
pair passed a published-image cumulative text-budget overflow and fresh-turn
smoke. The older alpha.11 wrapper index is
`ghcr.io/sorilo/cortex-tts-wrapper@sha256:8074f07a6a3a7daf105407c7bd70bcdb867a34a04c9c7941339a100c0dcfdd43`.
The alpha.11 pair passed a published-image Q4 smoke and all 37 source tests. The older
alpha.10 wrapper index is
`ghcr.io/sorilo/cortex-tts-wrapper@sha256:192b16de727635df8ad1b194636df0b0641cb06995306f614816e12dfa9b91d9`.
The alpha.10 pair passed isolated recovery, active Whisper, cancellation and streaming
checks. The older alpha.9 wrapper index is
`ghcr.io/sorilo/cortex-tts-wrapper@sha256:4e72820923e0b85975b14f269992bc942e3b7257a94cc2244ed37356cf25652a`.
The alpha.9 pair passed an isolated backend-restart, Wyoming and saved-voice smoke. It
correctly reports backend stream failures, but `/readyz` can become healthy
before post-restart synthesis is warm, causing an approximately 11-second
first-PCM delay in the observed first recovered turn.

The earlier alpha.7 wrapper index is
`ghcr.io/sorilo/cortex-tts-wrapper@sha256:1afd3d6d1b45cad446e89404712212a9601432d3e1d734f71e5b1fc211280ce1`.
The alpha.8/alpha.7 pair passed streaming, cancellation, Wyoming, active
Whisper and expressive-mode checks. Alpha.7 can misclassify an abruptly
closed backend stream as a client protocol error.

To return to the previous published backend baseline too, set
`breeze-backend.image` in this project's `compose.release.yaml` to
`ghcr.io/sorilo/cortex-tts-backend@sha256:0ace2780f6a5b4f47fe4ca5b977db83c09e51bdd38f4c9a5a1f6df023262e65e`.
Use the alpha.7 wrapper digest above. Set `BREEZE_CHUNK_FIRST=4` in this
project's `.env` to restore the original alpha.5 four-frame behavior; Compose
passes its explicit chunk command to the container, so changing the image
alone does not restore that default. Keep `BREEZE_CHUNK_MAX=25`. The alpha.5
backend with a two-frame command override was also tested, but that is a
different configuration from the original baseline.

Before applying the change, check that the chosen GPU is available and that
the dedicated project's model, voices and token variables are set. Render and
inspect the proposed config with `docker compose --project-name
cortex-tts-release -f compose.release.yaml config`. Then run `docker compose
--project-name cortex-tts-release -f compose.release.yaml up -d --wait` for
this project only. Check `/readyz`, confirm the backend log reports `Vulkan0`,
and synthesize a short Cortex or Wyoming test turn. The release project must
remain separate from any active Cortex, Whisper, Satellite or Pi stack.

To return to the current release, restore the alpha.8 backend and alpha.13
wrapper digests above and `BREEZE_CHUNK_FIRST=2`, re-render Compose and repeat
the dedicated-project readiness and speech smoke checks. No model assets or
voice profiles need to be replaced for this image and chunk-setting rollback.
Unset `BREEZE_MODEL_FILE` or set it to `/models/breeze-tts-2-q4_k.gguf` to
restore the Q4 release default after a Q6/Q8 comparison.
