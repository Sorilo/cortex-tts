"""Bounded admission and a transparent session bridge to Breeze WebSocket.

Breeze owns phrase splitting. The wrapper owns admission and client lifetime.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

import aiohttp

from .config import Settings


class Busy(Exception):
    pass


class ProtocolError(Exception):
    pass


class BackendError(Exception):
    pass


class Admission:
    def __init__(self, limit: int, timeout: float) -> None:
        self.lock = asyncio.Lock()
        self.limit = limit
        self.timeout = timeout
        self.waiters = 0

    async def __aenter__(self) -> None:
        if self.lock.locked():
            if self.waiters >= self.limit:
                raise Busy("synthesis queue full")
            self.waiters += 1
            try:
                await asyncio.wait_for(self.lock.acquire(), self.timeout)
            except TimeoutError as exc:
                raise Busy("synthesis queue timeout") from exc
            finally:
                self.waiters -= 1
        else:
            await self.lock.acquire()

    async def __aexit__(self, *_: object) -> None:
        self.lock.release()


def validate_client_message(message: object, settings: Settings, started: bool) -> dict:
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("expected JSON object with type")
    kind = message["type"]
    allowed = {"start", "text", "flush", "instruction", "cancel", "end"}
    if kind not in allowed:
        raise ProtocolError("unknown message type")
    if kind == "start" and started:
        raise ProtocolError("session already started")
    if kind != "start" and not started:
        raise ProtocolError("start required")
    if kind in {"text", "flush", "end"}:
        value = message.get("text", "")
        if not isinstance(value, str) or len(value) > settings.max_text_chars:
            raise ProtocolError("text exceeds limit or is invalid")
    if kind in {"start", "instruction"}:
        instruction = message.get("instruction", "")
        if not isinstance(instruction, str) or len(instruction) > 1000:
            raise ProtocolError("invalid instruction")
    if kind == "start":
        voice = message.get("voice_id", "")
        if not isinstance(voice, str) or len(voice) > 100 or "/" in voice or ".." in voice:
            raise ProtocolError("invalid voice_id")
    return message


class BackendSession:
    def __init__(self, client: aiohttp.ClientSession, url: str):
        self.client = client
        self.url = url
        self.ws: aiohttp.ClientWebSocketResponse | None = None

    async def __aenter__(self) -> "BackendSession":
        self.ws = await self.client.ws_connect(self.url, heartbeat=20, max_msg_size=8 * 1024 * 1024)
        try:
            ready = await self.ws.receive(timeout=10)
            if ready.type != aiohttp.WSMsgType.TEXT or json.loads(ready.data).get("type") != "ready":
                raise BackendError("backend did not announce ready")
        except BaseException:
            await self.ws.close()
            raise
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.ws and not self.ws.closed:
            await self.ws.close()

    async def send(self, message: dict) -> None:
        assert self.ws is not None
        await self.ws.send_json(message)

    async def events(self) -> AsyncIterator[tuple[str, bytes | dict]]:
        assert self.ws is not None
        async for event in self.ws:
            if event.type == aiohttp.WSMsgType.BINARY:
                if len(event.data) % 2:
                    raise BackendError("backend returned odd-length PCM")
                yield "audio", event.data
            elif event.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(event.data)
                if not isinstance(data, dict) or "type" not in data:
                    raise BackendError("invalid backend event")
                yield "event", data
                if data["type"] in {"done", "error"}:
                    return
            elif event.type in {aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED}:
                break
        raise BackendError("backend closed before completion")


class Metrics:
    def __init__(self) -> None:
        self.requests = 0
        self.failures = 0
        self.cancelled = 0
        self.audio_bytes = 0
        self.first_audio_seconds: list[float] = []

    def snapshot(self, admission: Admission) -> dict:
        return {
            "requests": self.requests,
            "failures": self.failures,
            "cancelled": self.cancelled,
            "audio_bytes": self.audio_bytes,
            "first_audio_seconds_recent": self.first_audio_seconds[-20:],
            "active": admission.lock.locked(),
            "queued": admission.waiters,
        }


class Engine:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.admission = Admission(settings.queue_limit, settings.queue_timeout)
        self.metrics = Metrics()
        self.client: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        self.client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=5))

    async def close(self) -> None:
        if self.client:
            await self.client.close()

    def session(self) -> BackendSession:
        assert self.client is not None
        return BackendSession(self.client, self.settings.backend_ws)

    async def health(self) -> bool:
        assert self.client is not None
        try:
            async with self.client.get(self.settings.backend_http + "/health", timeout=3) as resp:
                return resp.status == 200
        except (aiohttp.ClientError, TimeoutError):
            return False

    async def voices(self) -> list[str]:
        assert self.client is not None
        try:
            async with self.client.get(self.settings.backend_http + "/v1/voices", timeout=3) as resp:
                resp.raise_for_status()
                payload = await resp.json()
                if isinstance(payload, list):
                    return [str(v.get("id")) for v in payload if isinstance(v, dict) and v.get("id")]
                if isinstance(payload, dict):
                    rows = payload.get("voices", [])
                    return [str(v.get("id")) for v in rows if isinstance(v, dict) and v.get("id")]
        except (aiohttp.ClientError, TimeoutError, ValueError):
            pass
        return []
