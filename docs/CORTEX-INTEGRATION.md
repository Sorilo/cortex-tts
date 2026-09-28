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
The runnable `scripts/core_turn_client.py` demonstrates this handoff from a
trusted voice client: it polls authenticated Core GET results, checks the
requested `audio_turn_id` and stable `action_id`, ignores partial/model fields,
and speaks only nonempty Core `speech_text` in selected speakable states. It
waits for a terminal state by default; `--allow-approval-pending` opts into
Core's approval-pending phrase. It can cancel its own TTS stream for a test,
but never calls Core's action-interrupt endpoint. Tokens remain in the client
environment, not in the TTS containers or JSON output. The example saves
received PCM as a WAV after the stream; it is not a physical playback client.
Its Python `synthesize_core_turn(..., on_audio=async_packet_handler)` entry
point forwards each PCM packet before `done`, with natural backpressure while
the handler runs. Keep that handler short and enqueue into a bounded playback
queue. The caller still owns speaker start, buffer depth, barge-in and any Core
action interruption. Without a WAV output path, the example retains packet
timings and byte counts but not the complete waveform.
The same Python entry point accepts `cancel_event=asyncio.Event()`; setting it
while synthesis is active sends TTS `cancel` without waiting for another audio
packet, stops further PCM callbacks, and waits for the TTS cancellation ack.
If the event is set before Core has provided speakable text, it interrupts the
pending GET or polling interval and raises `PlaybackCancelled` without opening
a TTS stream. The caller can catch that exception to end the local playback
turn; Core's action may still continue and its later receipt remains valid.
The caller must immediately stop the speaker and discard its playback queue.
This event never invokes Core's `/interrupt` route or reverses a completed
action.

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

Each `text`, `flush`, or `end` message may add at most 2,000 characters, and
the whole session may add at most 12,000 characters across those messages.
Wyoming legacy synthesis and streaming chunks follow the same limits.
Exceeding either limit ends the current request with a protocol error and
releases its backend session; start a new request for a separate reply.
For Wyoming streaming, `synthesize-stop` ends input to that request. A later
chunk or duplicate stop is a terminal protocol error; the wrapper closes its
backend session rather than leaving text in an unconsumed queue. A new
`synthesize-start` or legacy `synthesize` may then begin on the same connection.
`voice_id`, `seed`, and `cfg_scale` are chosen at `start` and cannot be updated
within that session. Only `instruction` changes delivery mid-session, from the
next piece rather than retroactively changing audio already being spoken.
For a local synthetic demonstration, `scripts/stream_client.py` accepts
`--instruction-after-first` with at least two text pieces and checks the
correlated `instruction_set` event. It does not make unapproved Core fragments
speakable: the current Core integration sends one complete authorized
`speech_text` and does not use this diagnostic option.

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
   text to Assist. It is not the PCM playback layer. Current Satellite Python
   supervises pinned Linux Voice Assistant (LVA); LVA and the selected HA Assist
   pipeline own TTS interaction and speaker playback. LVA sends audio to its
   configured `pipewire/<playback_sink>` output, and Wyoming TTS is a server-side
   HA provider. The current development Assist pipeline has `tts_engine=None`.
   For the first physical Breeze path, register this service as a Wyoming TTS
   provider in the isolated voice HA and select it in a dedicated Assist
   pipeline only after gating which conversation-agent speech may reach it.
   Verify the selected pipeline, returned audio, and actual Satellite playback.
   The adapter currently emits some fixed local failure phrases in
   addition to Core `speech_text`; a generic pipeline TTS selection would
   synthesize those too. Keep that existing fallback path separate unless its
   authority is explicitly reviewed. Preserve the voice HA's allowlisted
   integrations and device/room bridge checks. Do not assume HA's pipeline
   preserves first-PCM timing through to the physical speaker.
3. `scripts/core_turn_client.py` demonstrates an authorized client with a
   progressive PCM callback, but it is not connected to current Satellite
   playback. A direct PCM path would need a separately designed and authorized
   LVA/HA integration or replacement playback transport with measured buffering,
   audio focus, and barge-in. A callback in Satellite Python alone cannot feed
   LVA's current playback path. If such a path is built, correlate Core
   `audio_turn_id` and `action_id` with the TTS `turn_id` at that caller; they
   are distinct IDs. Stop device playback and send TTS `cancel`/disconnect on
   barge-in. Route any action interruption through Core's existing `/interrupt`
   endpoint separately; preserve completed effects and receipts.
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

## Coordinated first-speaker acceptance run

Use the current LVA/HA playback path for the first physical run when the owner
has a Satellite pause window. Before changing the isolated development voice
HA, recheck the Core, Deploy, Satellite, and pinned LVA contracts below. Keep
production HA, Pi, household devices outside the test, and every existing
Cortex service running under its own owner. Use a separate digest-pinned TTS
Compose project, dedicated ports/network/voice volume, and a verified GPU
window. Wyoming TCP is not bearer-authenticated; expose it only to the trusted
isolated voice HA path with `CORTEX_TTS_WYOMING_BIND`, leaving the Cortex API
on `CORTEX_TTS_BIND=127.0.0.1`. Keep the Cortex API token out of HA effects.

The isolated voice HA currently has no TTS engine selected. Before selecting
Breeze as its Wyoming provider, establish an authority gate for the adapter's
fixed local rejection/unavailable phrases: a generic HA pipeline would speak
them as well as Core `speech_text`. The first end-to-end case should use a
synthetic, non-effect reply that Core authorizes. Confirm that HA selected the
dedicated Cortex Assist pipeline and Wyoming provider, and that LVA routes the
returned audio to its configured `pipewire/<playback_sink>` for the intended
room. This path does not use `scripts/core_turn_client.py`'s PCM callback.

Capture a per-turn timeline of Core's terminal state and `audio_turn_id` /
`action_id`, the HA TTS request, Wyoming `audio-start` and first `audio-chunk`,
first audible speaker output, and any rebuffers or interruption. Use a local
test-run ID where HA/Wyoming do not carry the Cortex TTS `turn_id`; do not
silently equate those identifiers. Compare first PCM with first audible sound
and report both. Keep synthetic transcripts and timing only unless recording
retention is explicitly chosen for the test.

Run at least an ordinary authorized reply, denied/uncertain Core results, a
long first-shape reply and its warm repeat, wrong-room/no-playback separation,
and barge-in followed by a fresh reply. Check that device playback stops and
queued audio is cleared, no late audio crosses turns, and Core action receipts
remain unchanged unless a separate Core `/interrupt` request was actually
made. Exercise approval-pending narration only after the HA adapter supports
that state. Keep the fake software voice bridge's eSpeak route selectable and
run its existing regression separately. Record audible continuity, perceived
Q4 voice quality, cancellation, and Breeze-plus-active-Whisper GPU residency;
the synthetic loopback numbers in `docs/VALIDATION.md` are not physical
acceptance evidence.

If the dedicated pipeline fails its authority, room, playback, or barge-in
checks, restore that isolated HA pipeline's previous TTS selection and stop
only the dedicated TTS project. `docs/ROLLBACK.md` gives the immutable image
and chunk-setting fallback within this repository. Do not alter the Satellite
runtime or deploy the direct PCM client as an implicit workaround.

Existing Cortex/Satellite repositories are intentionally untouched by this
standalone implementation.
This checklist was checked read-only against `cortex-core` commit
`5ed4d07cec56fca89954ac377ef4b5162b4c0c61` and `cortex-deploy` commit
`3cf01af1e7abd96e3f5b9798a50907cc05924a12`, plus `cortex-satellite`
commit `d332fb3da791c0c53106ef46a41715ba14079c33` (which pins LVA
`2d460b672871547701c9a0389a7873a70153b014`), on 2026-09-28.
Satellite's historical audible diagnostic replies do not validate this isolated
Cortex/Breeze pipeline. Recheck these contracts before a coordinated change.
