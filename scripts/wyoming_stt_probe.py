"""Transcribe one WAV through an isolated Wyoming Whisper service."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path


async def send(writer: asyncio.StreamWriter, kind: str, data: dict | None = None,
               payload: bytes = b"") -> None:
    body = json.dumps(data or {}).encode() if data else b""
    header = {"type": kind}
    if body:
        header["data_length"] = len(body)
    if payload:
        header["payload_length"] = len(payload)
    writer.write(json.dumps(header).encode() + b"\n" + body + payload)
    await writer.drain()


async def receive(reader: asyncio.StreamReader) -> tuple[str, dict]:
    header = json.loads(await reader.readline())
    data = json.loads(await reader.readexactly(header["data_length"])) if header.get("data_length") else {}
    if header.get("payload_length"):
        await reader.readexactly(header["payload_length"])
    return header["type"], data


async def transcribe(host: str, port: int, audio: Path) -> dict:
    with wave.open(str(audio), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError("WAV must be mono 16-bit PCM")
        fmt = {"rate": wav.getframerate(), "width": 2, "channels": 1}
        pcm = wav.readframes(wav.getnframes())
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 10)
    started = time.monotonic()
    try:
        await send(writer, "transcribe", {"language": "en"})
        await send(writer, "audio-start", fmt)
        await send(writer, "audio-chunk", fmt, pcm)
        await send(writer, "audio-stop")
        stopped = time.monotonic()
        while True:
            kind, data = await asyncio.wait_for(receive(reader), 120)
            if kind == "transcript":
                return {"text": data.get("text", ""),
                        "after_audio_stop_s": time.monotonic() - stopped,
                        "total_s": time.monotonic() - started,
                        "audio_s": len(pcm) / (fmt["rate"] * 2)}
            if kind == "error":
                raise RuntimeError(str(data))
    finally:
        writer.close()
        await writer.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=10300)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(transcribe(args.host, args.port, args.wav))))


if __name__ == "__main__":
    main()
