"""Boots the REAL server process (python -m app.main) and talks to it over real HTTP/SSE/WebSocket."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

TOKEN = "e2e-token-0123456789abcdef"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def boot(tmp_path: Path, **extra: str) -> tuple[subprocess.Popen, int]:
    port = free_port()
    env = {**os.environ, "ZONIC_DATA_DIR": str(tmp_path / "data"), "ZONIC_API_TOKEN": TOKEN, "ZONIC_PORT": str(port), "PYTHONUNBUFFERED": "1", **extra}
    env.pop("NVIDIA_API_KEY", None)
    proc = subprocess.Popen([sys.executable, "-m", "app.main"], cwd=str(Path(__file__).parent.parent), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return proc, port
        except httpx.HTTPError:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("backend did not start:\n" + (proc.stdout.read() if proc.stdout else ""))


def test_real_server_lifecycle(tmp_path):
    proc, port = boot(tmp_path)
    base, h = f"http://127.0.0.1:{port}", {"X-Zonic-Token": TOKEN}
    try:
        assert httpx.get(f"{base}/api/status").status_code == 401
        st = httpx.get(f"{base}/api/status", headers=h).json()
        assert st["backend"]["state"] == "ready" and st["limited_mode"] is True  # no key saved -> honest limited mode
        # chat without a model fails honestly, over the real stack
        sub = httpx.post(f"{base}/api/chat", headers=h, json={"message": "hello"}).json()
        for _ in range(50):
            t = httpx.get(f"{base}/api/tasks/{sub['task_id']}", headers=h).json()
            if t["status"] in ("failed", "completed"):
                break
            time.sleep(0.1)
        assert t["status"] == "failed" and t["result"]["error_code"] == "not_configured"
        # real SSE stream delivers a hello frame
        with httpx.stream("GET", f"{base}/api/events", headers=h, timeout=5) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            first = next(r.iter_lines())
            assert first.startswith("event: hello")
        # real WebSocket: wrong token is refused, right token is accepted
        import asyncio
        import websockets

        async def ws_check() -> tuple[bool, bool]:
            refused = False
            try:
                async with websockets.connect(f"ws://127.0.0.1:{port}/api/voice/ws?token=nope"):
                    pass
            except Exception:
                refused = True
            async with websockets.connect(f"ws://127.0.0.1:{port}/api/voice/ws?token={TOKEN}") as ws:
                await ws.send('{"type":"start"}')  # no Gemini key -> error state, not a crash
                msgs = []
                for _ in range(3):
                    msgs.append(await asyncio.wait_for(ws.recv(), 5))
                    if '"error"' in msgs[-1]:
                        break
                return refused, any('"error"' in m and "Text chat still works" in m for m in msgs)

        refused, got_error = asyncio.run(ws_check())
        assert refused and got_error
        # graceful shutdown via API
        assert httpx.post(f"{base}/api/shutdown", headers=h).json()["ok"] is True
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    assert (tmp_path / "data" / "zonic.db").exists()
    log = (tmp_path / "data" / "logs" / "backend.log").read_text()
    assert TOKEN not in log and "stopped cleanly" in log


def test_refuses_to_start_without_token_or_on_public_interface(tmp_path):
    base_env = {**os.environ, "ZONIC_DATA_DIR": str(tmp_path / "d")}
    cwd = str(Path(__file__).parent.parent)
    p = subprocess.run([sys.executable, "-m", "app.main"], cwd=cwd, env={k: v for k, v in base_env.items() if k != "ZONIC_API_TOKEN"}, capture_output=True, text=True, timeout=20)
    assert p.returncode == 2 and "ZONIC_API_TOKEN" in p.stderr
    p = subprocess.run([sys.executable, "-m", "app.main", "--host", "0.0.0.0"], cwd=cwd, env={**base_env, "ZONIC_API_TOKEN": TOKEN}, capture_output=True, text=True, timeout=20)
    assert p.returncode == 2 and "non-loopback" in p.stderr


def test_backend_exits_when_parent_disappears(tmp_path):
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    proc, port = boot(tmp_path, ZONIC_PARENT_PID=str(sleeper.pid))
    try:
        assert httpx.get(f"http://127.0.0.1:{port}/health").status_code == 200
        sleeper.kill(); sleeper.wait()
        assert proc.wait(timeout=15) == 0  # no orphaned backend
    finally:
        if proc.poll() is None:
            proc.kill()


def test_shutdown_is_not_blocked_by_an_open_event_stream(tmp_path):
    """Regression: a UI left attached to /api/events made uvicorn wait forever, so the backend never exited."""
    import threading
    proc, port = boot(tmp_path)
    h = {"X-Zonic-Token": TOKEN}
    started, stop = threading.Event(), threading.Event()

    def hold_stream():
        try:
            with httpx.stream("GET", f"http://127.0.0.1:{port}/api/events", headers=h, timeout=None) as r:
                for _ in r.iter_lines():
                    started.set()
                    if stop.is_set():
                        break
        except httpx.HTTPError:
            started.set()

    t = threading.Thread(target=hold_stream, daemon=True)
    t.start()
    try:
        assert started.wait(10)
        assert httpx.post(f"http://127.0.0.1:{port}/api/shutdown", headers=h).json()["ok"] is True
        assert proc.wait(timeout=12) == 0  # exits despite the still-open stream
    finally:
        stop.set()
        if proc.poll() is None:
            proc.kill()
