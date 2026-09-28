# Release rollback

`compose.release.yaml` is a separate Cortex TTS project. Its current tested
pair is the alpha.8 backend OCI index
`sha256:c8b2411666e60b76665f694f3f8c9d6bcf01a20f845f6dee33a1bbf28cd46a67`
and alpha.7 wrapper OCI index
`sha256:1afd3d6d1b45cad446e89404712212a9601432d3e1d734f71e5b1fc211280ce1`,
with `BREEZE_CHUNK_FIRST=2` and `BREEZE_CHUNK_MAX=25`. The two-frame setting
was tested against the published alpha.8 image; read `docs/VALIDATION.md` for
the observed cancellation and continuity tradeoff.

To return to the previous published backend, change only the
`breeze-backend.image` digest in this project's `compose.release.yaml` to
`ghcr.io/sorilo/cortex-tts-backend@sha256:0ace2780f6a5b4f47fe4ca5b977db83c09e51bdd38f4c9a5a1f6df023262e65e`.
Keep the alpha.7 wrapper digest above. Set `BREEZE_CHUNK_FIRST=4` in this
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

To return to alpha.8, restore its backend digest and
`BREEZE_CHUNK_FIRST=2`, re-render Compose and repeat the dedicated-project
readiness and speech smoke checks. No model assets or voice profiles need to
be replaced for this backend and chunk-setting rollback.
