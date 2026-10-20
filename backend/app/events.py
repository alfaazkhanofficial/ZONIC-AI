"""In-process event bus with replay buffer, exposed to the UI through one SSE stream."""
from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator

from .db import now_iso
from .redaction import redact_obj


@dataclass
class Event:
    id: int
    kind: str
    data: dict[str, Any]
    ts: str

    def sse(self) -> str:
        return f"id: {self.id}\nevent: {self.kind}\ndata: {json.dumps({**self.data, '_ts': self.ts})}\n\n"


class EventBus:
    def __init__(self, buffer: int = 1000):
        self._seq = 0
        self._buf: deque[Event] = deque(maxlen=buffer)
        self._subs: set[asyncio.Queue[Event]] = set()

    def publish(self, kind: str, data: dict[str, Any] | None = None) -> Event:
        self._seq += 1
        ev = Event(self._seq, kind, redact_obj(data or {}), now_iso())
        self._buf.append(ev)
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:  # slow consumer: drop it; client reconnects and re-snapshots
                self._subs.discard(q)
        return ev

    def since(self, last_id: int) -> list[Event]:
        return [e for e in self._buf if e.id > last_id]

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self._subs.discard(q)

    @property
    def last_id(self) -> int:
        return self._seq


async def sse_stream(bus: EventBus, last_id: int | None, *, keepalive_s: float = 15.0, max_events: int | None = None) -> AsyncIterator[str]:
    """Yield SSE frames. If last_id is given, replay missed events first; if the buffer no longer
    covers the gap the client is told to resync with a `resync` event."""
    q = bus.subscribe()
    sent = 0
    try:
        yield f"event: hello\ndata: {json.dumps({'last_id': bus.last_id})}\n\n"
        if last_id is not None:
            missed = bus.since(last_id)
            if last_id < bus.last_id and (not missed or missed[0].id > last_id + 1):
                yield "event: resync\ndata: {}\n\n"
            for ev in missed:
                yield ev.sse()
                sent += 1
                if max_events is not None and sent >= max_events:
                    return
            seen = max((e.id for e in missed), default=last_id)
        else:
            seen = bus.last_id
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=keepalive_s)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            if ev.id <= seen:
                continue
            seen = ev.id
            yield ev.sse()
            sent += 1
            if max_events is not None and sent >= max_events:
                return
    finally:
        bus.unsubscribe(q)
