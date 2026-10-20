from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.providers.base import ChatMessage, ProviderError, ProviderErrorCode
from app.providers.nemotron import NemotronProvider
from app.secrets_store import SecretStore
from app.settings_service import SettingsService
from app.db import Database

KEY = "nvapi-TESTKEY1234567890abcdef"


def make(tmp_path, handler, key=KEY, **cfg):
    db = Database(tmp_path / "p.db")
    settings = SettingsService(db)
    if cfg:
        settings.update("nemotron", cfg)
    secrets = SecretStore(tmp_path, use_keyring=False)
    if key:
        secrets.set("nvidia_api_key", key)
    sleeps: list[float] = []

    async def fake_sleep(s):
        sleeps.append(s)

    p = NemotronProvider(settings, secrets, transport=httpx.MockTransport(handler), sleep=fake_sleep)
    return p, sleeps


def ok_body(content="hi", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg, "finish_reason": "stop"}], "usage": {"total_tokens": 5}}


async def test_non_stream_success_and_request_shape(tmp_path):
    seen = {}

    def h(req: httpx.Request):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return httpx.Response(200, json=ok_body("hello"))

    p, _ = make(tmp_path, h, streaming=False)
    r = await p.chat([ChatMessage("system", "s"), ChatMessage("user", "u")], tools=[{"type": "function", "function": {"name": "t", "parameters": {"type": "object"}}}])
    assert r.content == "hello"
    assert seen["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["body"]["model"] == "nvidia/nemotron-3-super-120b-a12b" and seen["body"]["tool_choice"] == "auto" and seen["body"]["stream"] is False


async def test_tool_calls_parsed(tmp_path):
    tc = [{"id": "c1", "type": "function", "function": {"name": "get_system_status", "arguments": "{}"}}]
    p, _ = make(tmp_path, lambda r: httpx.Response(200, json=ok_body(None, tc)), streaming=False)
    r = await p.chat([ChatMessage("user", "x")])
    assert r.tool_calls[0].name == "get_system_status" and r.tool_calls[0].id == "c1" and r.content == ""


async def test_streaming_assembles_text_and_fragmented_tool_calls(tmp_path):
    chunks = [
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo", "reasoning_content": "secret thoughts"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c9", "function": {"name": "read_appr", "arguments": '{"pa'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "oved_file", "arguments": 'th":"a.txt"}'}}]}, "finish_reason": "tool_calls"}]},
    ]
    sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    p, _ = make(tmp_path, lambda r: httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"}))
    deltas = []
    r = await p.chat([ChatMessage("user", "x")], on_delta=deltas.append)
    assert r.content == "Hello" and deltas == ["Hel", "lo"]  # reasoning_content is never surfaced
    assert r.tool_calls[0].name == "read_approved_file" and json.loads(r.tool_calls[0].arguments) == {"path": "a.txt"}


@pytest.mark.parametrize("status,code", [(401, ProviderErrorCode.INVALID_CREDENTIALS), (403, ProviderErrorCode.INVALID_CREDENTIALS), (404, ProviderErrorCode.UNSUPPORTED_MODEL),
                                          (400, ProviderErrorCode.BAD_REQUEST), (500, ProviderErrorCode.PROVIDER_OUTAGE)])
async def test_http_errors_map_to_normalized_codes(tmp_path, status, code):
    p, _ = make(tmp_path, lambda r: httpx.Response(status, json={"error": {"message": f"boom {KEY}"}}), streaming=False)
    with pytest.raises(ProviderError) as e:
        await p.chat([ChatMessage("user", "x")])
    assert e.value.code == code and KEY not in e.value.message  # provider messages are redacted


async def test_rate_limit_retries_with_retry_after_then_succeeds(tmp_path):
    n = {"c": 0}

    def h(req):
        n["c"] += 1
        return httpx.Response(429, headers={"retry-after": "2"}, json={}) if n["c"] == 1 else httpx.Response(200, json=ok_body("ok"))

    p, sleeps = make(tmp_path, h, streaming=False)
    assert (await p.chat([ChatMessage("user", "x")])).content == "ok" and n["c"] == 2 and sleeps == [2.0]


async def test_outage_retries_are_bounded(tmp_path):
    n = {"c": 0}

    def h(req):
        n["c"] += 1
        return httpx.Response(503, json={})

    p, _ = make(tmp_path, h, streaming=False)
    with pytest.raises(ProviderError) as e:
        await p.chat([ChatMessage("user", "x")])
    assert e.value.code == ProviderErrorCode.PROVIDER_OUTAGE and n["c"] == 3


async def test_timeout_network_missing_key_and_bad_payload(tmp_path):
    def boom_timeout(req):
        raise httpx.ReadTimeout("slow")

    p, _ = make(tmp_path, boom_timeout, streaming=False)
    with pytest.raises(ProviderError) as e:
        await p.chat([ChatMessage("user", "x")])
    assert e.value.code == ProviderErrorCode.TIMEOUT

    def boom_net(req):
        raise httpx.ConnectError("down")

    p, _ = make(tmp_path, boom_net, streaming=False)
    with pytest.raises(ProviderError) as e:
        await p.chat([ChatMessage("user", "x")])
    assert e.value.code == ProviderErrorCode.NETWORK

    p, _ = make(tmp_path, lambda r: httpx.Response(200, json={"nope": 1}), streaming=False)
    with pytest.raises(ProviderError) as e:
        await p.chat([ChatMessage("user", "x")])
    assert e.value.code == ProviderErrorCode.INVALID_RESPONSE

    p, _ = make(tmp_path / "nokey", lambda r: httpx.Response(200, json=ok_body()), key=None)
    assert not p.configured()
    with pytest.raises(ProviderError) as e:
        await p.chat([ChatMessage("user", "x")])
    assert e.value.code == ProviderErrorCode.NOT_CONFIGURED


async def test_cancel_during_request(tmp_path):
    async def slow(req):
        await asyncio.sleep(5)
        return httpx.Response(200, json=ok_body())

    p, _ = make(tmp_path, slow, streaming=False)
    cancel = asyncio.Event()
    task = asyncio.ensure_future(p.chat([ChatMessage("user", "x")], cancel=cancel))
    await asyncio.sleep(0.1)
    cancel.set()
    with pytest.raises(ProviderError) as e:
        await asyncio.wait_for(task, 2)
    assert e.value.code == ProviderErrorCode.CANCELLED


async def test_connection_test_results(tmp_path):
    p, _ = make(tmp_path, lambda r: httpx.Response(200, json=ok_body("pong")))
    t = await p.test_connection()
    assert t.ok and t.model == "nvidia/nemotron-3-super-120b-a12b"
    p, _ = make(tmp_path, lambda r: httpx.Response(401, json={}))
    t = await p.test_connection()
    assert not t.ok and t.code == "invalid_credentials" and t.hint


def test_settings_reject_insecure_base_url(tmp_path):
    s = SettingsService(Database(tmp_path / "s.db"))
    with pytest.raises(Exception):
        s.update("nemotron", {"base_url": "http://evil.example.com/v1"})
    s.update("nemotron", {"base_url": "http://localhost:8000/v1"})
