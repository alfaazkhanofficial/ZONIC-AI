"""Gemini Live voice. The browser/renderer only captures and plays PCM; the API key and the Live session live here.
Voice is a conversational front-end: anything needing tools/memory/computer is delegated to the same agent runtime
(Nemotron brain + permission policy) through one function call, so voice can never bypass safety policy."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol

from .providers.base import ConnectionTest
from .redaction import redact

log = logging.getLogger(__name__)
STATES = ("disconnected", "connecting", "listening", "thinking", "speaking", "interrupted", "error")
DELEGATE_TOOL = "delegate_to_zonic_agent"
MAX_RECONNECTS = 2


class VoiceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def classify_live_error(exc: BaseException) -> VoiceError:
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if isinstance(exc, VoiceError):
        return exc
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return VoiceError("timeout", "Gemini Live did not answer in time.")
    if any(s in low for s in ("api key", "api_key", "permission_denied", "unauthenticated", "401", "403")):
        return VoiceError("invalid_credentials", "Google rejected the Gemini API key.")
    if any(s in low for s in ("not found", "not supported", "404", "unsupported")):
        return VoiceError("unsupported_model", "The Live model ID was not accepted. Check Settings → Voice for a current model name.")
    if any(s in low for s in ("429", "quota", "resource_exhausted", "rate")):
        return VoiceError("rate_limited", "Gemini quota or rate limit reached.")
    return VoiceError("network", f"Could not reach Gemini Live ({type(exc).__name__}).")


@dataclass
class LiveEvent:
    kind: str  # audio | interrupted | turn_complete | input_text | output_text | tool_call | go_away | closed
    data: Any = None


class LiveSession(Protocol):
    async def send_audio(self, pcm16_16k: bytes) -> None: ...
    async def send_tool_response(self, call_id: str, name: str, result: dict[str, Any]) -> None: ...
    def events(self) -> AsyncIterator[LiveEvent]: ...
    async def close(self) -> None: ...


class LiveConnector(Protocol):
    def configured(self) -> bool: ...
    async def connect(self, *, model: str, system_instruction: str, voice_name: str) -> LiveSession: ...


class GeminiLiveConnector:
    """Real adapter over the official google-genai SDK (client.aio.live.connect)."""

    def __init__(self, secrets: Any):
        self.secrets = secrets

    def configured(self) -> bool:
        return bool(self.secrets.get("gemini_api_key"))

    async def connect(self, *, model: str, system_instruction: str, voice_name: str) -> LiveSession:
        from google import genai
        from google.genai import types
        key = self.secrets.get("gemini_api_key")
        if not key:
            raise VoiceError("not_configured", "No Gemini API key is configured.")
        client = genai.Client(api_key=key)
        decl = types.FunctionDeclaration(
            name=DELEGATE_TOOL,
            description="Hand a task to the ZONIC agent when it needs tools, memory, files, apps, the browser or the computer. Returns the agent's result.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={"request": types.Schema(type=types.Type.STRING, description="What the user wants done, in plain language.")}, required=["request"]))
        cfg = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=types.Content(parts=[types.Part(text=system_instruction)]),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=[types.Tool(function_declarations=[decl])],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name))) if voice_name else None,
        )
        cm = client.aio.live.connect(model=model, config=cfg)
        try:
            session = await asyncio.wait_for(cm.__aenter__(), timeout=20)
        except BaseException as exc:
            raise classify_live_error(exc) from exc
        return _GeminiSession(cm, session, types)


class _GeminiSession:
    def __init__(self, cm: Any, session: Any, types_mod: Any):
        self._cm, self._s, self._t = cm, session, types_mod

    async def send_audio(self, pcm: bytes) -> None:
        await self._s.send_realtime_input(audio=self._t.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))

    async def send_tool_response(self, call_id: str, name: str, result: dict[str, Any]) -> None:
        await self._s.send_tool_response(function_responses=[self._t.FunctionResponse(id=call_id, name=name, response=result)])

    async def events(self) -> AsyncIterator[LiveEvent]:
        try:
            while True:
                n = 0
                async for msg in self._s.receive():  # one iteration of receive() == one model turn
                    n += 1
                    sc = msg.server_content
                    if sc:
                        if sc.model_turn:
                            for part in sc.model_turn.parts or []:
                                if part.inline_data and part.inline_data.data:
                                    yield LiveEvent("audio", part.inline_data.data)
                        if sc.input_transcription and sc.input_transcription.text:
                            yield LiveEvent("input_text", sc.input_transcription.text)
                        if sc.output_transcription and sc.output_transcription.text:
                            yield LiveEvent("output_text", sc.output_transcription.text)
                        if sc.interrupted:
                            yield LiveEvent("interrupted")
                        if sc.turn_complete:
                            yield LiveEvent("turn_complete")
                    if msg.tool_call:
                        for fc in msg.tool_call.function_calls or []:
                            yield LiveEvent("tool_call", {"id": fc.id or "", "name": fc.name, "args": dict(fc.args or {})})
                    if msg.go_away:
                        yield LiveEvent("go_away")
                if n == 0:
                    break
        except Exception as exc:
            log.info("live receive ended: %s", type(exc).__name__)
        yield LiveEvent("closed")

    async def close(self) -> None:
        try:
            await self._cm.__aexit__(None, None, None)
        except Exception:
            pass


def voice_system_prompt(svc: Any) -> str:
    p = svc.settings.get("personalization")
    s = ("You are the voice of ZONIC M4, a personal AI agent on the user's Windows PC. Speak naturally and keep replies short. "
         f"For anything that needs tools, memory, files, apps, the browser or the computer, call {DELEGATE_TOOL} with a clear request, wait for it, "
         "then report its answer faithfully, including failures, caveats and anything it could not verify. Never claim an action happened unless the tool result says so. "
         "Never read out secrets.")
    if p["address_as"]:
        s += f" Address the user as {p['address_as']}."
    if p["voice_behavior"]:
        s += f" Style notes from the user: {redact(p['voice_behavior'])}"
    return s


Emit = Callable[[dict[str, Any]], Awaitable[None]]
SendAudio = Callable[[bytes], Awaitable[None]]


class VoiceSession:
    def __init__(self, svc: Any, connector: LiveConnector, emit: Emit, send_audio: SendAudio, *, backoff: tuple[float, ...] = (1.0, 2.0)):
        self.svc, self.connector, self._emit, self._send_audio, self._backoff = svc, connector, emit, send_audio, backoff
        self.state = "disconnected"
        self._live: LiveSession | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stopping = False
        self._muted = False  # drop remaining model audio after the user pressed interrupt
        self._in_buf: list[str] = []
        self._out_buf: list[str] = []
        self._conversation_id: str | None = None
        self._bg: set[asyncio.Task[None]] = set()
        self._reconnects = 0

    async def _set(self, state: str, detail: str | None = None, code: str | None = None) -> None:
        if state == self.state and detail is None:
            return
        self.state = state
        payload = {"type": "state", "state": state, "detail": detail, "code": code}
        self.svc.bus.publish("voice_state", {"state": state, "detail": detail, "code": code})
        await self._emit(payload)

    async def start(self) -> bool:
        self._stopping = False
        await self._set("connecting", "Connecting to Gemini Live")
        cfg = self.svc.settings.get("gemini")
        try:
            self._live = await self.connector.connect(model=cfg["model"], system_instruction=voice_system_prompt(self.svc), voice_name=cfg["voice_name"])
        except Exception as exc:
            err = classify_live_error(exc)
            self._live = None
            await self._set("error", f"{err.message} Text chat still works.", err.code)
            return False
        await self._set("listening", "Listening")
        self._reader = asyncio.ensure_future(self._read_loop())
        return True

    async def feed_audio(self, pcm: bytes) -> None:
        if self._live and self.state in ("listening", "speaking", "thinking", "interrupted"):
            try:
                await self._live.send_audio(pcm)
            except Exception as exc:
                log.info("send_audio failed: %s", type(exc).__name__)

    async def interrupt(self) -> None:
        if self.state in ("speaking", "thinking"):
            self._muted = True
            await self._emit({"type": "clear_playback"})
            await self._set("interrupted", "You interrupted")
            await self._set("listening", "Listening")

    async def stop(self) -> None:
        self._stopping = True
        if self._reader:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        for t in list(self._bg):
            t.cancel()
        if self._live:
            await self._live.close()
            self._live = None
        await self._flush_transcripts()
        await self._set("disconnected", "Voice session ended")

    # ---- reading ------------------------------------------------------
    async def _read_loop(self) -> None:
        assert self._live
        try:
            async for ev in self._live.events():
                await self._handle(ev)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("voice read loop failed")
            await self._set("error", f"Voice stopped unexpectedly ({type(exc).__name__}). Text chat still works.", "internal")

    async def _handle(self, ev: LiveEvent) -> None:
        if ev.kind == "audio":
            if self._muted:
                return
            if self.state != "speaking":
                await self._set("speaking", "Speaking")
            await self._send_audio(ev.data)
        elif ev.kind == "interrupted":
            await self._emit({"type": "clear_playback"})
            await self._flush_transcripts()
            self._muted = False
            await self._set("interrupted", "Interrupted")
            await self._set("listening", "Listening")
        elif ev.kind == "turn_complete":
            self._muted = False
            await self._flush_transcripts()
            if self.state != "thinking":
                await self._set("listening", "Listening")
        elif ev.kind == "input_text":
            self._in_buf.append(ev.data)
            await self._emit({"type": "transcript", "role": "user", "text": ev.data})
        elif ev.kind == "output_text":
            self._out_buf.append(ev.data)
            await self._emit({"type": "transcript", "role": "assistant", "text": ev.data})
        elif ev.kind == "tool_call":
            t = asyncio.ensure_future(self._delegate(ev.data))
            self._bg.add(t)
            t.add_done_callback(self._bg.discard)
        elif ev.kind in ("go_away", "closed"):
            if self._stopping:
                return
            await self._reconnect("The voice connection was closed by the server.")

    async def _reconnect(self, why: str) -> None:
        if self._live:
            await self._live.close()
            self._live = None
        while self._reconnects < MAX_RECONNECTS and not self._stopping:
            delay = self._backoff[min(self._reconnects, len(self._backoff) - 1)]
            self._reconnects += 1
            await self._set("connecting", f"Reconnecting (attempt {self._reconnects}/{MAX_RECONNECTS})")
            await asyncio.sleep(delay)
            cfg = self.svc.settings.get("gemini")
            try:
                self._live = await self.connector.connect(model=cfg["model"], system_instruction=voice_system_prompt(self.svc), voice_name=cfg["voice_name"])
            except Exception as exc:
                log.info("voice reconnect failed: %s", type(exc).__name__)
                continue
            self._reconnects = 0
            await self._set("listening", "Reconnected")
            self._reader = asyncio.ensure_future(self._read_loop())
            return
        await self._set("disconnected", f"{why} Reconnect attempts failed; use the mic button to start again. Text chat still works.", "connection_lost")

    # ---- delegation to the agent -------------------------------------
    async def _delegate(self, call: dict[str, Any]) -> None:
        live = self._live
        if live is None:
            return
        await self._set("thinking", "Working on it")
        result: dict[str, Any]
        if call["name"] != DELEGATE_TOOL or not str(call["args"].get("request", "")).strip():
            result = {"status": "error", "error": "Unknown or empty request."}
        else:
            if self._conversation_id is None:
                self._conversation_id = self.svc.chat.ensure(None, "Voice conversation")
            sub = await self.svc.agent.submit(str(call["args"]["request"])[:2000], self._conversation_id)
            try:
                task = await self.svc.tasks.wait(sub["task_id"], timeout=900)
                r = task["result"]
                result = {"status": task["status"], "answer": r.get("final") or r.get("error") or "", "verification": (r.get("verification") or {}).get("status")}
            except asyncio.TimeoutError:
                result = {"status": "still_running", "answer": "The task is still running; tell the user to check the Tasks screen."}
        try:
            await live.send_tool_response(call["id"], call["name"], result)
        except Exception as exc:
            log.info("send_tool_response failed: %s", type(exc).__name__)

    async def _flush_transcripts(self) -> None:
        user, bot = "".join(self._in_buf).strip(), "".join(self._out_buf).strip()
        self._in_buf.clear(); self._out_buf.clear()
        if not (user or bot):
            return
        if self._conversation_id is None:
            self._conversation_id = self.svc.chat.ensure(None, user or "Voice conversation")
        for role, text in (("user", user), ("assistant", bot)):
            if text:
                m = self.svc.chat.add(self._conversation_id, role, text, {"voice": True})
                self.svc.bus.publish("message_added", {"conversation_id": self._conversation_id, "message": m})


class VoiceManager:
    def __init__(self, svc: Any, connector: LiveConnector | None = None):
        self.svc = svc
        self.connector: LiveConnector = connector or GeminiLiveConnector(svc.secrets)
        self.sessions: set[VoiceSession] = set()

    def configured(self) -> bool:
        return self.connector.configured()

    def new_session(self, emit: Emit, send_audio: SendAudio) -> VoiceSession:
        s = VoiceSession(self.svc, self.connector, emit, send_audio)
        self.sessions.add(s)
        return s

    def release(self, s: VoiceSession) -> None:
        self.sessions.discard(s)

    def state(self) -> str:
        return next((s.state for s in self.sessions if s.state != "disconnected"), "disconnected")

    async def stop_all(self) -> None:
        for s in list(self.sessions):
            await s.stop()

    async def test_connection(self) -> ConnectionTest:
        cfg = self.svc.settings.get("gemini")
        if not self.connector.configured():
            return ConnectionTest(False, "not_configured", "No Gemini API key is configured.", None, cfg["model"], "Add your Gemini API key in Settings → Voice.")
        t0 = time.monotonic()
        try:
            live = await asyncio.wait_for(self.connector.connect(model=cfg["model"], system_instruction="Connection test.", voice_name=""), timeout=25)
        except Exception as exc:
            e = classify_live_error(exc)
            return ConnectionTest(False, e.code, e.message, None, cfg["model"])
        await live.close()
        ms = int((time.monotonic() - t0) * 1000)
        return ConnectionTest(True, "ok", f"Live session opened and closed cleanly ({ms} ms). A real microphone round trip is still needed to confirm audio.", ms, cfg["model"])
