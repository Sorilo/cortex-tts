# Release rollback

`compose.release.yaml` is a separate Cortex TTS project. Its current tested
pair is the alpha.8 backend OCI index
`sha256:c8b2411666e60b76665f694f3f8c9d6bcf01a20f845f6dee33a1bbf28cd46a67`
and alpha.9 wrapper OCI index
`sha256:4e72820923e0b85975b14f269992bc942e3b7257a94cc2244ed37356cf25652a`,
with `BREEZE_CHUNK_FIRST=2` and `BREEZE_CHUNK_MAX=25`. The two-frame setting
was tested against the published alpha.8 image; read `docs/VALIDATION.md` for
the observed cancellation and continuity tradeoff.

To roll back only the wrapper, set `wrapper.image` in this project's
`compose.release.yaml` to the previously verified alpha.7 index
`ghcr.io/sorilo/cortex-tts-wrapper@sha256:1afd3d6d1b45cad446e89404712212a9601432d3e1d734f71e5b1fc211280ce1`.
Leave the alpha.8 backend digest and two-frame chunk setting unchanged. This
exact alpha.8/alpha.7 pair passed isolated streaming, cancellation, Wyoming,
active Whisper and expressive-mode checks. The older wrapper can misclassify
an abruptly closed backend stream as a client protocol error.

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

To return to the current release, restore the alpha.8 backend and alpha.9
wrapper digests above and `BREEZE_CHUNK_FIRST=2`, re-render Compose and repeat
the dedicated-project readiness and speech smoke checks. No model assets or
voice profiles need to be replaced for this image and chunk-setting rollback.
