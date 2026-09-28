import asyncio

import pytest

from cortex_tts.config import Settings
from cortex_tts.engine import Admission, Busy, Metrics, ProtocolError, validate_client_message


def test_protocol_limits_and_voice_path():
    settings = Settings(max_text_chars=5)
    assert validate_client_message({"type": "start", "voice_id": "warm"}, settings, False)
    with pytest.raises(ProtocolError):
        validate_client_message({"type": "text", "text": "too long"}, settings, True)
    with pytest.raises(ProtocolError):
        validate_client_message({"type": "start", "voice_id": "../escape"}, settings, False)
    with pytest.raises(ProtocolError):
        validate_client_message({"type": "text", "text": "hi"}, settings, False)


@pytest.mark.asyncio
async def test_admission_is_bounded():
    admission = Admission(limit=0, timeout=0.01)
    async with admission:
        with pytest.raises(Busy):
            async with admission:
                pass
    async with admission:
        assert admission.lock.locked()


def test_metrics_keep_only_recent_first_audio_samples():
    metrics = Metrics()
    for sample in range(1000):
        metrics.first_audio_seconds.append(float(sample))

    recent = metrics.snapshot(Admission(limit=0, timeout=0))["first_audio_seconds_recent"]
    assert recent == [float(sample) for sample in range(980, 1000)]
    assert len(metrics.first_audio_seconds) == 20
