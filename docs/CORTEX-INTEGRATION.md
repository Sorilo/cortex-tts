# Cortex integration contract (version 1)

The service synthesizes text supplied by its caller. It cannot authenticate a
person, authorize an action, or decide which agent output is safe to speak.
Only Core's authoritative `speech_text` should reach it. Stopping audio and
cancelling a Core action are separate operations; completed effects and receipts
remain authoritative after playback interruption.

In the current Core contract, `POST /v1/voice/device/turns` admits a turn and
returns `audio_turn_id` and `action_id`; `GET /v1/voice/device/turns/{turn_id}`
returns `state`, those IDs, and `speech_text`. That field can be `null` while
Core has no speakable result; it can also contain Core's approval-pending
phrase before a terminal state. The software voice path has corresponding
`/v1/voice/turns` endpoints. There is
no current Core stream of authorized speech fragments, so the initial Cortex
integration should send the complete nonempty `speech_text` in one TTS `text`
message followed by `end`. The incremental TTS API is reserved for a future
Core contract that authorizes each fragment before it is sent.

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
stores the encoded voice profile. `GET /readyz` checks backend availability
and wrapper warmup state; it returns 503 during backend recovery rewarm. A new
Cortex stream during that interval gets one terminal `code:backend` event with
`message:backend warming` and no `ready` event. `GET /livez` only checks the wrapper.
Authenticated `/v1/metrics` exposes
counts and timing without utterance text or audio.

## Later integration checklist

1. For the development software-voice bridge,
   `cortex-deploy/fakes/voice.py` currently reads Core `speech_text` from the
   turn result and returns an eSpeak WAV as `speech_wav_base64`. Add an
   opt-in Breeze streaming transport only after agreeing a bridge/client
   response contract; keep the eSpeak/full-WAV route selectable for existing
   deterministic tests. Never synthesize the submitted transcript, a partial
   transcript, model prose, or a pending `speech_text: null` response.
2. The dedicated voice Home Assistant adapter at
   `cortex-deploy/config/custom_components/cortex_assist/__init__.py` is a
   conversation agent: after Core reaches a terminal state, it returns speech
   text to Assist. It is not the PCM playback layer. The current development
   Assist pipeline has `tts_engine=None`. For Wyoming compatibility, register
   this service as a Wyoming TTS provider in that isolated voice HA, select it
   in a dedicated Assist pipeline only after gating which conversation-agent
   speech may reach it, and verify which audio events actually reach the
   Satellite. The adapter currently emits some fixed local failure phrases in
   addition to Core `speech_text`; a generic pipeline TTS selection would
   synthesize those too. Keep that existing fallback path separate unless its
   authority is explicitly reviewed. Preserve the voice HA's allowlisted
   integrations and device/room bridge checks. Do not assume HA's pipeline
   preserves first-PCM timing through to the physical speaker.
3. For direct low-latency Cortex playback, adapt the authorized voice client
   or Satellite transport in a coordinated task to consume Cortex binary PCM
   frames into a measured queue. Correlate Core `audio_turn_id` and `action_id`
   with the TTS `turn_id` at that caller; they are distinct IDs. Stop device
   playback and send TTS `cancel`/disconnect on barge-in. Route any action
   interruption through Core's existing `/interrupt` endpoint separately;
   preserve completed effects and receipts.
4. Speak Core's nonempty authoritative `speech_text` for the appropriate
   succeeded, denied, failed, cancelled, uncertain and approval-pending
   outcomes. The current HA adapter waits only for terminal states and thus
   does not yet return Core's `awaiting_approval` phrase; coordinate that
   state handoff before relying on approval narration. Keep the HA adapter's
   fixed local rejection/unavailable phrases on its existing fallback path
   unless Core or an explicit authority policy approves their Breeze routing.
   Do not forward arbitrary upstream error detail or start Breeze from
   generic HA/agent text outside this authority path.
5. Keep TTS on the unprotected client network with no Core, HA effect,
   database, or Hermes secrets. Provide a narrow service token only to the
   voice transport. Evaluate actual retention before using household audio.
   Add isolated Cortex tests for authoritative speech, denied and uncertain
   results, cancellation, stale-audio prevention, room/device separation,
   eSpeak fallback and both Wyoming and direct-PCM paths. Then validate
   physical Satellite playback and barge-in in a coordinated task.

Existing Cortex/Satellite repositories are intentionally untouched by this
standalone implementation.
This checklist was checked read-only against `cortex-core` commit
`5ed4d07cec56fca89954ac377ef4b5162b4c0c61` and `cortex-deploy` commit
`3cf01af1e7abd96e3f5b9798a50907cc05924a12` on 2026-09-28; recheck
their contracts before a coordinated integration change.
