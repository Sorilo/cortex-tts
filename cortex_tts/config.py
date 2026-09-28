from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    backend_http: str = "http://breeze-backend:8080"
    backend_ws: str = "ws://breeze-backend:8081"
    api_host: str = "0.0.0.0"
    api_port: int = 18080
    wyoming_host: str = "0.0.0.0"
    wyoming_port: int = 10200
    api_token: str = ""
    default_voice: str = ""
    default_instruction: str = "Speak clearly and naturally."
    queue_limit: int = 2
    queue_timeout: float = 2.0
    max_text_chars: int = 2000
    max_session_seconds: float = 120.0

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            backend_http=os.getenv("BREEZE_HTTP", cls.backend_http),
            backend_ws=os.getenv("BREEZE_WS", cls.backend_ws),
            api_host=os.getenv("CORTEX_TTS_HOST", cls.api_host),
            api_port=int(os.getenv("CORTEX_TTS_PORT", str(cls.api_port))),
            wyoming_host=os.getenv("WYOMING_HOST", cls.wyoming_host),
            wyoming_port=int(os.getenv("WYOMING_PORT", str(cls.wyoming_port))),
            api_token=os.getenv("CORTEX_TTS_TOKEN", ""),
            default_voice=os.getenv("BREEZE_VOICE", ""),
            default_instruction=os.getenv("BREEZE_INSTRUCTION", cls.default_instruction),
            queue_limit=int(os.getenv("CORTEX_TTS_QUEUE_LIMIT", str(cls.queue_limit))),
            queue_timeout=float(os.getenv("CORTEX_TTS_QUEUE_TIMEOUT", str(cls.queue_timeout))),
        )
