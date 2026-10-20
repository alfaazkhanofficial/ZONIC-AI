from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from app.voice import DELEGATE_TOOL, LiveEvent, VoiceError, VoiceManager, VoiceSession, classify_live_error
from conftest import say, call, grant


class FakeLive:
    def __init__(self):
        self.q: asyncio.Queue[LiveEvent] = asyncio.Queue()
        self.audio_in: list[bytes] = []
        self.tool_responses: list[tuple[str, str, dict]] = []
        self.closed = False

    async def send_audio(self, pcm):
        self.audio_in.append(pcm)

    async def send_tool_response(self, call_id, name, result):
        self.tool_responses.append((call_id, name, result))

    async def events(self) -> AsyncIterator[LiveEvent]:
        while True:
            ev = await self.q.get()
            yield ev
            if ev.kind == "closed":
                return

    async def close(self):
        self.closed = True


class FakeConnector:
    def __init__(self, *, fail: Exception | None = None, configured=True):
        self.fail, self._configured, self.sessions, self.args = fail, configured, [], []

    def configured(self):
        return self._configured

    async def connect(self, *, model, system_instruction, voice_name):
        self.args.append((model, system_instruction, voice_name))
        if self.fail:
            raise self.fail
        s = FakeLive()
        self.sessions.append(s)
        return s


class Rig:
    def __init__(self, env, connector):
        self.env, self.connector = env, connector
        self.out: list[dict[str, Any]] = []
        self.audio: list[bytes] = []

        async def emit(m): self.out.append(m)
        async def send_audio(b): self.audio.append(b)
        self.session = VoiceSession(env.svc, connector, emit, send_audio, backoff=(0.01, 0.01))

    def states(self):
        return [m["state"] for m in self.out if m["type"] == "state"]


async def settle(n=5):
    for _ in range(n):
        await asyncio.sleep(0.02)


async def test_state_machine_audio_and_transcripts(env):
    r = Rig(env, FakeConnector())
    assert await r.session.start()
    live = r.connector.sessions[0]
    assert r.states() == ["connecting", "listening"]
    await r.session.feed_audio(b"\x01\x02")
    assert live.audio_in == [b"\x01\x02"]
    await live.q.put(LiveEvent("input_text", "what time "))
    await live.q.put(LiveEvent("input_text", "is it"))
    await live.q.put(LiveEvent("audio", b"AAAA"))
    await live.q.put(LiveEvent("output_text", "It is noon."))
    await live.q.put(LiveEvent("turn_complete"))
    await settle()
    assert r.audio == [b"AAAA"] and r.states()[-2:] == ["speaking", "listening"]
    msgs = env.svc.chat.messages(r.session._conversation_id)
    assert [(m["role"], m["content"]) for m in msgs] == [("user", "what time is it"), ("assistant", "It is noon.")]
    await r.session.stop()
    assert r.states()[-1] == "disconnected" and live.closed
    assert env.svc.bus.since(0)[-1].kind in ("voice_state", "message_added")


async def test_user_interrupt_drops_rest_of_model_turn(env):
    r = Rig(env, FakeConnector())
    await r.session.start()
    live = r.connector.sessions[0]
    await live.q.put(LiveEvent("audio", b"1"))
    await settle()
    await r.session.interrupt()
    await live.q.put(LiveEvent("audio", b"2"))  # arrives after the interrupt: must not be played
    await settle()
    assert r.audio == [b"1"] and {"type": "clear_playback"} in r.out and "interrupted" in r.states()
    await live.q.put(LiveEvent("turn_complete"))
    await live.q.put(LiveEvent("audio", b"3"))
    await settle()
    assert r.audio == [b"1", b"3"]
    await r.session.stop()


async def test_server_side_interruption_clears_playback(env):
    r = Rig(env, FakeConnector())
    await r.session.start()
    live = r.connector.sessions[0]
    await live.q.put(LiveEvent("audio", b"1"))
    await live.q.put(LiveEvent("interrupted"))
    await settle()
    assert {"type": "clear_playback"} in r.out and r.states()[-2:] == ["interrupted", "listening"]
    await r.session.stop()


async def test_voice_delegates_to_agent_and_returns_honest_result(env):
    grant(env.svc, env.ws, "read_workspace")
    (env.ws / "n.txt").write_text("alpha")
    env.provider.script = [call("read_approved_file", path="n.txt"), say("The file says alpha.")]
    r = Rig(env, FakeConnector())
    await r.session.start()
    live = r.connector.sessions[0]
    await live.q.put(LiveEvent("tool_call", {"id": "fc1", "name": DELEGATE_TOOL, "args": {"request": "read n.txt"}}))
    for _ in range(100):
        if live.tool_responses:
            break
        await asyncio.sleep(0.03)
    cid, name, result = live.tool_responses[0]
    assert cid == "fc1" and name == DELEGATE_TOOL and result["status"] == "completed" and "alpha" in result["answer"]
    assert "thinking" in r.states()
    await r.session.stop()


async def test_voice_cannot_bypass_permissions(env):
    env.provider.script = [call("write_approved_file", path="x.txt", content="hi"), say("I can't write files: the permission is off.")]
    r = Rig(env, FakeConnector())
    await r.session.start()
    live = r.connector.sessions[0]
    await live.q.put(LiveEvent("tool_call", {"id": "fc2", "name": DELEGATE_TOOL, "args": {"request": "write x.txt"}}))
    for _ in range(100):
        if live.tool_responses:
            break
        await asyncio.sleep(0.03)
    assert not (env.ws / "x.txt").exists()
    assert any(a["outcome"] == "permission_not_granted" for a in env.svc.audit.recent())
    await r.session.stop()


async def test_connect_failure_goes_to_error_state_with_text_fallback(env):
    r = Rig(env, FakeConnector(fail=RuntimeError("403 PERMISSION_DENIED api key not valid")))
    assert not await r.session.start()
    last = [m for m in r.out if m["type"] == "state"][-1]
    assert last["state"] == "error" and last["code"] == "invalid_credentials" and "Text chat still works" in last["detail"]


async def test_reconnects_after_drop_then_gives_up(env):
    conn = FakeConnector()
    r = Rig(env, conn)
    await r.session.start()
    await conn.sessions[0].q.put(LiveEvent("closed"))
    await settle(10)
    assert len(conn.sessions) == 2 and r.states()[-1] == "listening" and "connecting" in r.states()[2:]
    conn.fail = RuntimeError("network down")
    await conn.sessions[1].q.put(LiveEvent("closed"))
    await settle(20)
    last = [m for m in r.out if m["type"] == "state"][-1]
    assert last["state"] == "disconnected" and last["code"] == "connection_lost"
    await r.session.stop()


async def test_manager_connection_test_and_error_classification(env):
    env.svc.voice = VoiceManager(env.svc, FakeConnector(configured=False))
    t = await env.svc.voice.test_connection()
    assert not t.ok and t.code == "not_configured"
    env.svc.voice = VoiceManager(env.svc, FakeConnector())
    t = await env.svc.voice.test_connection()
    assert t.ok and "microphone round trip" in t.message
    env.svc.voice = VoiceManager(env.svc, FakeConnector(fail=RuntimeError("429 RESOURCE_EXHAUSTED")))
    assert (await env.svc.voice.test_connection()).code == "rate_limited"
    assert classify_live_error(asyncio.TimeoutError()).code == "timeout"
    assert classify_live_error(VoiceError("x", "y")).code == "x"
    assert classify_live_error(RuntimeError("model not found")).code == "unsupported_model"


async def test_voice_websocket_requires_token(client, env):
    from app.api import token_ok
    assert token_ok("a" * 24, "a" * 24) and not token_ok("", "a" * 24) and not token_ok("b" * 24, "a" * 24) and not token_ok(None, "a" * 24)
