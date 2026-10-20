from __future__ import annotations

import asyncio
import itertools
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import RuntimeConfig
from app.main import create_app
from app.providers.base import ChatMessage, ChatResult, ConnectionTest, ProviderError, ProviderErrorCode, ToolCall
from app.secrets_store import SecretStore
from app.services import Services, build_services
from app.tools.windows import Adapters

TOKEN = "t" * 24
_ids = itertools.count(1)


def say(text: str) -> ChatResult:
    return ChatResult(content=text, tool_calls=[], finish_reason="stop")


def call(name: str, _say: str = "", /, **args: Any) -> ChatResult:
    return ChatResult(content=_say, tool_calls=[ToolCall(f"call_{next(_ids)}", name, json.dumps(args))], finish_reason="tool_calls")


class FakeProvider:
    """Scripted stand-in for the model. Only used in tests (never in production paths)."""

    def __init__(self, script: list[Any] | None = None, *, configured: bool = True, delay: float = 0.0):
        self.script, self.calls, self._configured, self.delay = list(script or []), [], configured, delay

    def configured(self) -> bool:
        return self._configured

    def describe(self) -> dict[str, Any]:
        return {"provider": "fake", "model": "fake-model", "base_url": "", "streaming": False, "configured": self._configured}

    async def chat(self, messages: list[ChatMessage], tools: Any = None, *, cancel: asyncio.Event | None = None, on_delta: Any = None, max_tokens: int | None = None) -> ChatResult:
        self.calls.append({"messages": list(messages), "tools": tools})
        if self.delay and cancel is not None:
            try:
                await asyncio.wait_for(cancel.wait(), self.delay)
                raise ProviderError(ProviderErrorCode.CANCELLED, "Cancelled.")
            except asyncio.TimeoutError:
                pass
        item = self.script.pop(0) if self.script else say("(script exhausted)")
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(messages)
        if on_delta and item.content:
            on_delta(item.content)
        return item

    async def test_connection(self) -> ConnectionTest:
        return ConnectionTest(True, "ok", "fake ok", 1, "fake-model")


class FakeScreen:
    def grab(self) -> tuple[int, int, bytes]:
        return 4, 3, b"\x89PNG\r\n\x1a\nfakepng"


class FakeInput:
    def __init__(self) -> None:
        self.actions: list[tuple[Any, ...]] = []
        self._pos = (0, 0)

    def size(self) -> tuple[int, int]:
        return 1920, 1080

    def position(self) -> tuple[int, int]:
        return self._pos

    def move(self, x: int, y: int) -> None:
        self._pos = (x, y); self.actions.append(("move", x, y))

    def click(self, x: int, y: int, button: str, clicks: int) -> None:
        self._pos = (x, y); self.actions.append(("click", x, y, button, clicks))

    def scroll(self, amount: int) -> None:
        self.actions.append(("scroll", amount))

    def type_text(self, text: str) -> None:
        self.actions.append(("type", text))

    def press(self, key: str) -> None:
        self.actions.append(("press", key))

    def hotkey(self, keys: list[str]) -> None:
        self.actions.append(("hotkey", tuple(keys)))


class Env:
    def __init__(self, svc: Services, ws: Path, provider: FakeProvider, inp: FakeInput, opened: list[str]):
        self.svc, self.ws, self.provider, self.inp, self.opened = svc, ws, provider, inp, opened


def make_config(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(data_dir=tmp_path / "data", api_token=TOKEN)


def make_services(tmp_path: Path, provider: FakeProvider | None = None, **kw: Any) -> tuple[Services, FakeProvider, FakeInput, list[str]]:
    cfg = make_config(tmp_path)
    provider = provider or FakeProvider()
    inp, opened = FakeInput(), []
    adapters = Adapters(screen=FakeScreen(), input_factory=lambda: inp, active_window=lambda: {"title": "Untitled - Notepad", "process": "notepad.exe", "pid": 42}, open_url=lambda u: opened.append(u) or True)
    svc = build_services(cfg, provider=provider, adapters=adapters, secrets=SecretStore(cfg.data_dir, use_keyring=False), **kw)
    return svc, provider, inp, opened


def grant(svc: Services, ws: Path, *groups: str) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    svc.settings.update("workspaces", {"items": [{"name": "Test", "path": str(ws)}]}, confirmed=True)
    svc.settings.update("permissions", {g: True for g in groups}, confirmed=True)


@pytest.fixture
async def env(tmp_path: Path):
    svc, provider, inp, opened = make_services(tmp_path)
    ws = tmp_path / "workspace"
    ws.mkdir()
    e = Env(svc, ws, provider, inp, opened)
    yield e
    await svc.shutdown()


@pytest.fixture
async def client(env: Env):
    app = create_app(env.svc.config, env.svc)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"X-Zonic-Token": TOKEN}) as c:
        c.env = env  # type: ignore[attr-defined]
        yield c


async def run_task(env: Env, message: str, timeout: float = 15.0) -> dict[str, Any]:
    sub = await env.svc.agent.submit(message)
    return await env.svc.tasks.wait(sub["task_id"], timeout)
