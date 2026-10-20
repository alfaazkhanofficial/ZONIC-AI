"""NVIDIA Nemotron 3 Super adapter (OpenAI-compatible Chat Completions on integrate.api.nvidia.com).
Endpoint/model verified against NVIDIA docs (Oct 2026); both are configuration, not code."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from ..redaction import redact
from ..secrets_store import SecretStore
from ..settings_service import SettingsService
from .base import (HINTS, ChatMessage, ChatResult, ConnectionTest, DeltaCallback, ProviderError, ProviderErrorCode, ToolCall)

MAX_ATTEMPTS = 3


def map_http_error(status: int, body: str, headers: httpx.Headers | dict[str, str]) -> ProviderError:
    msg = ""
    try:
        j = json.loads(body)
        err = j.get("error", j) if isinstance(j, dict) else {}
        msg = (err.get("message") if isinstance(err, dict) else None) or j.get("detail") or j.get("title") or ""
        if not isinstance(msg, str):
            msg = json.dumps(msg)
    except (ValueError, AttributeError):
        msg = body[:200]
    msg = redact(msg)[:300]
    low = msg.lower()
    if status in (401, 403):
        return ProviderError(ProviderErrorCode.INVALID_CREDENTIALS, f"Credentials rejected by the provider (HTTP {status}). {msg}".strip(), status=status)
    if status == 404 or (status in (400, 422) and "model" in low and ("not found" in low or "does not exist" in low or "unsupported" in low)):
        return ProviderError(ProviderErrorCode.UNSUPPORTED_MODEL, f"Model or endpoint not found (HTTP {status}). {msg}".strip(), status=status)
    if status == 429:
        ra = headers.get("retry-after") if hasattr(headers, "get") else None
        try:
            retry_after = float(ra) if ra else None
        except ValueError:
            retry_after = None
        return ProviderError(ProviderErrorCode.RATE_LIMITED, "Rate limit reached.", retryable=True, status=status, retry_after=retry_after)
    if status in (400, 422):
        return ProviderError(ProviderErrorCode.BAD_REQUEST, f"The provider rejected the request (HTTP {status}). {msg}".strip(), status=status)
    if status >= 500:
        return ProviderError(ProviderErrorCode.PROVIDER_OUTAGE, f"Provider error (HTTP {status}). {msg}".strip(), retryable=status in (502, 503, 504), status=status)
    return ProviderError(ProviderErrorCode.BAD_REQUEST, f"Unexpected response (HTTP {status}). {msg}".strip(), status=status)


class NemotronProvider:
    def __init__(self, settings: SettingsService, secrets: SecretStore, *, transport: httpx.AsyncBaseTransport | None = None, sleep=asyncio.sleep):
        self.settings, self.secrets, self._transport, self._sleep = settings, secrets, transport, sleep

    def configured(self) -> bool:
        return bool(self.secrets.get("nvidia_api_key"))

    def describe(self) -> dict[str, Any]:
        c = self.settings.get("nemotron")
        return {"provider": "NVIDIA", "model": c["model"], "base_url": c["base_url"], "streaming": c["streaming"], "configured": self.configured()}

    # ---- wire ---------------------------------------------------------
    @staticmethod
    def _wire(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in messages:
            d: dict[str, Any] = {"role": m.role, "content": m.content if m.content is not None else ""}
            if m.tool_calls:
                d["tool_calls"] = [{"id": t.id, "type": "function", "function": {"name": t.name, "arguments": t.arguments}} for t in m.tool_calls]
                if not m.content:
                    d["content"] = None
            if m.tool_call_id:
                d["tool_call_id"] = m.tool_call_id
            out.append(d)
        return out

    async def chat(self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None, *, cancel: asyncio.Event | None = None,
                   on_delta: DeltaCallback | None = None, max_tokens: int | None = None) -> ChatResult:
        key = self.secrets.get("nvidia_api_key")
        if not key:
            raise ProviderError(ProviderErrorCode.NOT_CONFIGURED, "No NVIDIA API key is configured.")
        cfg = self.settings.get("nemotron")
        stream = bool(cfg["streaming"]) and max_tokens is None
        body: dict[str, Any] = {"model": cfg["model"], "messages": self._wire(messages), "stream": stream, "max_tokens": max_tokens or 4096}
        if cfg["temperature"] is not None:
            body["temperature"] = cfg["temperature"]
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        url = cfg["base_url"].rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "text/event-stream" if stream else "application/json"}
        timeout = httpx.Timeout(cfg["timeout_s"], connect=10.0)

        last: ProviderError | None = None
        for attempt in range(MAX_ATTEMPTS):
            if cancel and cancel.is_set():
                raise ProviderError(ProviderErrorCode.CANCELLED, "Cancelled.")
            try:
                async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                    if stream:
                        return await self._stream(client, url, headers, body, cancel, on_delta)
                    return await self._complete(client, url, headers, body, cancel)
            except ProviderError as e:
                last = e
                if not e.retryable or attempt == MAX_ATTEMPTS - 1:
                    raise
                delay = min(e.retry_after if e.retry_after is not None else 0.8 * (2 ** attempt), 8.0)
                if e.code == ProviderErrorCode.RATE_LIMITED and e.retry_after and e.retry_after > 8:
                    raise
                await self._sleep(delay)
            except httpx.TimeoutException:
                raise ProviderError(ProviderErrorCode.TIMEOUT, f"The provider did not respond within {cfg['timeout_s']:g}s.")
            except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as e:
                last = ProviderError(ProviderErrorCode.NETWORK, f"Network error: {type(e).__name__}.", retryable=True)
                if attempt == MAX_ATTEMPTS - 1:
                    raise last
                await self._sleep(0.8 * (2 ** attempt))
        raise last or ProviderError(ProviderErrorCode.NETWORK, "Request failed.")

    async def _complete(self, client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any], cancel: asyncio.Event | None) -> ChatResult:
        req = asyncio.ensure_future(client.post(url, headers=headers, json=body))
        waiter = asyncio.ensure_future(cancel.wait()) if cancel else None
        try:
            done, _ = await asyncio.wait({req, *([waiter] if waiter else [])}, return_when=asyncio.FIRST_COMPLETED)
            if req not in done:
                req.cancel()
                await asyncio.gather(req, return_exceptions=True)
                raise ProviderError(ProviderErrorCode.CANCELLED, "Cancelled.")
            resp = req.result()
        finally:
            if waiter:
                waiter.cancel()
        if resp.status_code >= 400:
            raise map_http_error(resp.status_code, resp.text, resp.headers)
        try:
            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "The provider returned a response without choices.")
        calls = [ToolCall(id=t.get("id") or f"call_{i}", name=t["function"]["name"], arguments=t["function"].get("arguments") or "{}")
                 for i, t in enumerate(msg.get("tool_calls") or []) if t.get("function", {}).get("name")]
        return ChatResult(content=msg.get("content") or "", tool_calls=calls, finish_reason=choice.get("finish_reason"), usage=data.get("usage"))

    async def _stream(self, client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any], cancel: asyncio.Event | None, on_delta: DeltaCallback | None) -> ChatResult:
        content: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish: str | None = None
        usage = None
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code >= 400:
                text = (await resp.aread()).decode("utf-8", "replace")
                raise map_http_error(resp.status_code, text, resp.headers)
            async for line in resp.aiter_lines():
                if cancel and cancel.is_set():
                    raise ProviderError(ProviderErrorCode.CANCELLED, "Cancelled.")
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    continue
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        content.append(delta["content"])
                        if on_delta:
                            on_delta(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        slot = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
                    finish = choice.get("finish_reason") or finish
        text = "".join(content)
        tool_calls = [ToolCall(id=c["id"] or f"call_{i}", name=c["name"], arguments=c["arguments"] or "{}") for i, c in sorted(calls.items()) if c["name"]]
        if not text and not tool_calls and finish is None:
            raise ProviderError(ProviderErrorCode.INVALID_RESPONSE, "The stream ended without any content.")
        return ChatResult(content=text, tool_calls=tool_calls, finish_reason=finish, usage=usage)

    async def test_connection(self) -> ConnectionTest:
        model = self.settings.get("nemotron")["model"]
        t0 = time.monotonic()
        try:
            res = await self.chat([ChatMessage("user", "Reply with the single word: pong")], max_tokens=64)
        except ProviderError as e:
            return ConnectionTest(False, e.code.value, e.message, None, model, HINTS.get(e.code))
        ms = int((time.monotonic() - t0) * 1000)
        if not (res.content or res.tool_calls):  # auth, endpoint and model all worked; a reasoning model may spend the tiny budget on thinking
            return ConnectionTest(True, "ok", f"Connected to {model} ({ms} ms). The test reply had no visible text, which can happen with a tiny token budget.", ms, model)
        return ConnectionTest(True, "ok", f"Connected. {model} replied in {ms} ms.", ms, model)
