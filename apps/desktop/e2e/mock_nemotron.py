"""A local OpenAI-compatible chat-completions server (HTTP + SSE) that plays the model for end-to-end tests.
The app's REAL provider adapter talks to it over real HTTP; only the model's decisions are scripted."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

GOOD_KEY = "nvapi-MOCKGOODKEY0123456789abcdef"

SCRIPTS: dict[str, list[Any]] = {
    "hello": [("text", "Hello from the mock model.")],
    "make note": [("tool", "Plan: create a folder, write the note, read it back.", "create_directory_in_workspace", {"path": "notes"}),
                  ("tool", "", "write_approved_file", {"path": "notes/todo.txt", "content": "buy milk\n"}),
                  ("tool", "", "read_approved_file", {"path": "notes/todo.txt"}),
                  ("text", "Created notes/todo.txt and confirmed it contains: buy milk.")],
    "overwrite": [("tool", "", "write_approved_file", {"path": "keep.txt", "content": "NEW CONTENT", "overwrite": True}), ("text", "I replaced keep.txt.")],
    "open site": [("tool", "", "open_url", {"url": "https://example.com/"}), ("text", "Opened example.com in your browser.")],
    "launch it": [("tool", "", "launch_allowlisted_application", {"app": "sleeper"}), ("text", "Launched the sleeper app.")],
    "slow": [("slow",)],
}


class State:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.auth_seen: list[str] = []
        self.aborted = 0
        self.ratelimit_pending = False
        self.lock = threading.Lock()


STATE = State()


def decide(messages: list[dict[str, Any]]) -> Any:
    last_user_idx = max(i for i, m in enumerate(messages) if m["role"] == "user")
    text = (messages[last_user_idx].get("content") or "").lower()
    tool_msgs = [m for m in messages[last_user_idx + 1:] if m["role"] == "tool"]
    for kw, script in SCRIPTS.items():
        if kw in text:
            return script[min(len(tool_msgs), len(script) - 1)]
    return ("text", "I am the mock model. You said: " + text[:80])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a: Any) -> None:  # silence
        pass

    def _json(self, status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(raw)

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            return self._json(404, {"error": {"message": "not found"}})
        n = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(n))
        with STATE.lock:
            STATE.auth_seen.append(self.headers.get("Authorization", ""))
            STATE.requests.append(body)
        if self.headers.get("Authorization") != f"Bearer {GOOD_KEY}":
            return self._json(401, {"error": {"message": "invalid api key"}})
        if STATE.ratelimit_pending:
            STATE.ratelimit_pending = False
            return self._json(429, {"error": {"message": "slow down"}}, {"Retry-After": "1"})
        action = decide(body["messages"]) if body.get("max_tokens", 9999) > 100 else ("text", "pong")
        stream = bool(body.get("stream"))
        if action[0] == "slow":
            return self._slow()
        if not stream:
            msg: dict[str, Any] = {"role": "assistant", "content": action[1] if action[0] == "text" else action[1] or None}
            if action[0] == "tool":
                msg["tool_calls"] = [{"id": "call_1", "type": "function", "function": {"name": action[2], "arguments": json.dumps(action[3])}}]
            return self._json(200, {"choices": [{"message": msg, "finish_reason": "stop"}], "usage": {"total_tokens": 9}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def sse(delta: dict[str, Any], finish: str | None = None) -> None:
            self.wfile.write(f"data: {json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]})}\n\n".encode()); self.wfile.flush()

        if action[0] == "text":
            t = action[1]
            for i in range(0, len(t), 6):
                sse({"content": t[i:i + 6]}); time.sleep(0.01)
            sse({}, "stop")
        else:
            _, pre, name, args = action
            if pre:
                sse({"content": pre})
            raw = json.dumps(args)
            cut = max(1, len(raw) // 2)  # fragment the arguments like real providers do
            sse({"reasoning_content": "(hidden reasoning)", "tool_calls": [{"index": 0, "id": f"call_{name}", "function": {"name": name, "arguments": raw[:cut]}}]})
            sse({"tool_calls": [{"index": 0, "function": {"arguments": raw[cut:]}}]})
            sse({}, "tool_calls")
        self.wfile.write(b"data: [DONE]\n\n"); self.wfile.flush()

    def _slow(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        try:
            for i in range(200):
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': f'token{i} '}}]})}\n\n".encode()); self.wfile.flush()
                time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError):
            with STATE.lock:
                STATE.aborted += 1


def start(port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
