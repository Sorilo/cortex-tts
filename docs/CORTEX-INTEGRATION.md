# Cortex integration contract (version 1)

The service synthesizes text supplied by its caller. It cannot authenticate a
person, authorize an action, or decide which agent output is safe to speak.
Only Core's authoritative `speech_text` should reach it. Stopping audio and
cancelling a Core action are separate operations; completed effects and receipts
remain authoritative after playback interruption.

Open `GET /v1/speech/stream` as WebSocket with `Authorization: Bearer <token>`.
The server returns `ready` with `version:1`, `turn_id`, `sample_rate:24000`,
`channels:1`, and `format:pcm_s16le`. Text frames are JSON. Client messages:

| type | fields | behavior |
| --- | --- | --- |
| `start` | optional `voice_id`, `instruction`, `seed`, `cfg_scale` | opens synthesis |
| `text` | `text` | appends incremental text |
| `flush` | optional `text` | forces buffered text into a phrase |
| `instruction` | `instruction` | changes delivery from the next phrase |
| `cancel` | none | aborts current generation and queued text |
| `end` | optional `text` | finishes buffered text and reports `done` |

`text` chunks are appended literally; a truly incremental caller must retain
spaces between words and sentences. The pinned Breeze backend drains a
completed sentence when each `text` message arrives. If Core has already
authorized a complete `speech_text` response, send that response in one
`text` message followed by `end`. Splitting an already-complete response into
artificial sentence messages can force separate synthesis pieces and create
avoidable first-shape gaps. Keep sending genuine incremental text as it becomes
authoritative; `flush` is for an unfinished phrase that must be spoken now.

The server forwards Breeze's `started`, `speaking`, `queued`,
`instruction_set`, `cancelled`, `done`, and `error` events with `turn_id`.
Binary frames are playable PCM; feed them into a playback queue as they arrive,
without waiting for `done`. Start the device when the queue reaches a measured
fill level, and adapt if it runs dry. Starting on the first frame minimizes
audible latency but can underrun on a first-seen text shape; buffering costs
audible latency. In the isolated Q4 cold-shape corpus, two of eight requests
underran in a zero-buffer simulation; a 1.25 s fill still underran, while a
2.0 s fill avoided those simulated gaps but began playback at median/p95
1.20/2.42 s. Those are local model results, not a Satellite setting. The
physical playback client must measure queue depth, first audible sound and
rebuffers before choosing its policy. An error or closed socket ends the
stream. The server admits one GPU synthesis session and a bounded waiting
queue. A busy request gets an `error` event with `code:busy`. Invalid JSON,
out-of-order input, and unsupported client messages get one terminal `error`
event with `code:protocol`; backend and transport failures use `code:backend`.

Authenticated `GET /v1/voices` lists saved voice IDs. `POST /v1/voices`
accepts multipart `name`, `ref_audio` WAV, and exact `ref_text`. The backend
stores the encoded voice profile. `GET /readyz` checks backend availability,
while `GET /livez` only checks the wrapper. Authenticated `/v1/metrics` exposes
counts and timing without utterance text or audio.

## Later integration checklist

1. In `cortex-deploy/fakes/voice.py`, replace only the development playback
   transport that currently produces a full eSpeak WAV; keep eSpeak selectable
   for deterministic tests. Do not bypass Core speech formatting.
2. In the voice-facing HA adapter at
   `cortex-deploy/config/custom_components/cortex_assist/__init__.py`, use the
   authoritative speech returned by Core. Send already-complete Core speech in
   one `text` message; use literal incremental chunks only if Core authorizes
   them as they arrive. Arrange client playback to consume PCM frames into a
   measured queue; a complete WAV response defeats streaming TTFA.
3. Correlate the Core turn ID with the TTS stream at the caller, and propagate
   playback stop to TTS `cancel`/disconnect. Route any action interruption
   through Core's existing interrupt API separately.
4. Keep TTS on the unprotected client network with no Core, HA effect,
   database, or Hermes secrets. Provide a narrow service token only to the
   voice transport. Evaluate actual retention before using household audio.
5. Add isolated Cortex integration tests for authoritative speech, denied and
   uncertain results, cancellation, no stale audio, and eSpeak fallback. Then
   validate physical Satellite playback and barge-in in a coordinated task.

Existing Cortex/Satellite repositories are intentionally untouched by this
standalone implementation.
