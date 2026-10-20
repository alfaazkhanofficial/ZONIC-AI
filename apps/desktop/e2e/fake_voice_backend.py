"""TEST-ONLY backend entry point: the real app, but Gemini Live is replaced by a scripted stand-in (no Google calls).
It records how much microphone audio the renderer really streamed, and answers with a synthetic 24 kHz tone."""
from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
import uvicorn  # noqa: E402

from app.config import RuntimeConfig, load_config  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import build_services  # noqa: E402
from app.voice import LiveEvent  # noqa: E402

STATS = Path(os.environ.get("ZONIC_FAKE_VOICE_STATS", "/tmp/zonic_voice_stats.json"))


def tone(seconds: float, hz: float = 440.0, rate: int = 24000) -> bytes:
    n = int(seconds * rate)
    return b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * hz * i / rate))) for i in range(n))


class ScriptedLive:
    def __init__(self) -> None:
        self.q: asyncio.Queue[LiveEvent] = asyncio.Queue()
        self.bytes_in = 0
        self.chunks = 0
        self.responded = False
        self.closed = False

    def _save(self) -> None:
        STATS.write_text(json.dumps({"bytes_in": self.bytes_in, "chunks": self.chunks, "closed": self.closed, "responded": self.responded}))

    async def send_audio(self, pcm: bytes) -> None:
        self.bytes_in += len(pcm)
        self.chunks += 1
        self._save()
        if not self.responded and self.bytes_in >= 16000 * 2 * 1.0:  # after ~1 s of real microphone audio
            self.responded = True
            asyncio.ensure_future(self._respond())

    async def _respond(self) -> None:
        await self.q.put(LiveEvent("input_text", "hello zonic"))
        await self.q.put(LiveEvent("output_text", "Hello! This is the scripted voice reply."))
        for _ in range(30):  # ~6 s of audio in 0.2 s pieces, so the UI test can interrupt mid-reply
            await self.q.put(LiveEvent("audio", tone(0.2)))
            await asyncio.sleep(0.2)
        await self.q.put(LiveEvent("turn_complete"))

    async def send_tool_response(self, call_id: str, name: str, result: dict) -> None:
        pass

    async def events(self):
        while True:
            ev = await self.q.get()
            yield ev
            if ev.kind == "closed":
                return

    async def close(self) -> None:
        self.closed = True
        self._save()


class ScriptedConnector:
    def configured(self) -> bool:
        return True

    async def connect(self, *, model: str, system_instruction: str, voice_name: str) -> ScriptedLive:
        return ScriptedLive()


def main() -> None:
    cfg = load_config()
    setup_logging(cfg.log_level, cfg.log_path)
    svc = build_services(cfg, live_connector=ScriptedConnector())
    parent = int(os.environ["ZONIC_PARENT_PID"]) if os.environ.get("ZONIC_PARENT_PID", "").isdigit() else None
    app = create_app(cfg, svc, parent_pid=parent)
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.host, port=cfg.port, log_config=None, access_log=False))
    app.state.server = server
    server.run()


if __name__ == "__main__":
    main()
