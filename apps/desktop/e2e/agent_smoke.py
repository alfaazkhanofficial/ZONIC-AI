"""Full agent loop in the REAL app: React UI -> Electron -> Python backend -> real Nemotron adapter (HTTP+SSE) -> local mock model -> real tools on the real file system.
Proves the integration path. It does NOT prove behaviour against NVIDIA's actual service (no key/network here)."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cdp import Page  # noqa: E402
import mock_nemotron as mock  # noqa: E402
import smoke  # noqa: E402
from smoke import App, PORT, SHOTS, api, check, conn_of  # noqa: E402


async def send(p: Page, text: str) -> None:
    await p.set_value("textarea[aria-label='Message ZONIC']", text)
    await p.click_text("Send")


async def latest(conn: dict) -> dict:
    return api(conn, "GET", "/api/tasks").json()["items"][0]


async def wait_task(conn: dict, status: str | tuple[str, ...], timeout: float = 40) -> dict:
    end = time.time() + timeout
    status = (status,) if isinstance(status, str) else status
    while time.time() < end:
        t = await latest(conn)
        if t["status"] in status:
            return t
        await asyncio.sleep(0.3)
    raise TimeoutError(f"task never reached {status}; last={await latest(conn)}")


async def approve(p: Page, label: str) -> None:
    await p.wait("!!document.querySelector('[role=alertdialog]')", 20, "approval dialog")
    await p.click_text(label)
    await asyncio.sleep(0.5)


async def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="zonic-agent-"))
    os.environ["ZONIC_DATA_DIR"] = str(root / "data")
    ws = root / "workspace"; ws.mkdir()
    (ws / "keep.txt").write_text("ORIGINAL")
    SHOTS.mkdir(parents=True, exist_ok=True)
    srv, mport = mock.start()
    app = App(root)
    sleeper = None
    try:
        app.start()
        p = await Page.attach(PORT)
        await p.wait("!!document.querySelector('.ob, .shell')", 40, "UI")
        conn = await conn_of(p)
        # configure like a user would (settings API == what the UI forms call)
        api(conn, "PATCH", "/api/settings", json={"group": "nemotron", "patch": {"base_url": f"http://127.0.0.1:{mport}/v1"}})
        api(conn, "PUT", "/api/secrets/nvidia_api_key", json={"value": mock.GOOD_KEY})
        api(conn, "PATCH", "/api/settings", json={"group": "workspaces", "patch": {"items": [{"name": "WS", "path": str(ws)}]}, "confirm_permission_change": True})
        api(conn, "PATCH", "/api/settings", json={"group": "permissions", "patch": {"read_workspace": True, "write_workspace": True, "browser": True, "launch_apps": True}, "confirm_permission_change": True})
        api(conn, "PATCH", "/api/settings", json={"group": "app_allowlist", "patch": {"items": {"sleeper": {"exe": sys.executable, "args": ["-c", "import time; time.sleep(60)"], "label": "Sleeper", "process_names": [Path(sys.executable).resolve().name.lower()]}}}, "confirm_permission_change": True})
        api(conn, "POST", "/api/onboarding/complete")
        await p.js("location.reload()")
        await p.wait("!!document.querySelector('.shell')", 20, "shell")

        # --- connection test through the real adapter, via the Settings UI
        await p.js("document.querySelector('.nav button[title=Settings]').click()")
        await p.wait("document.body.innerText.includes('Test connection')", 8)
        await p.click_text("Test connection")
        await p.wait("document.body.innerText.includes('Connected')", 20, "connected")
        t = await p.text()
        check("Settings > Test connection succeeds through the real adapter", "replied in" in t or "Connected to" in t, t[t.find("Connected"):][:120])
        await p.js("document.querySelector('.nav button[title=Home]').click()")
        await p.wait("document.body.innerText.includes('Nemotron 3 Super')", 8)
        await asyncio.sleep(0.5)
        check("status card: model Ready after a passing test", "Ready" in (await p.text()).split("Nemotron 3 Super")[1][:200])

        # --- 1. plain chat streams and completes
        await send(p, "hello there")
        t1 = await wait_task(conn, "completed")
        check("plain chat completes with the model's text", "Hello from the mock model" in t1["result"]["final"])
        sent = mock.STATE.requests[-1]
        check("request carried tools, system prompt rules and the user text", len(sent["tools"]) >= 8 and "untrusted DATA" in sent["messages"][0]["content"] and sent["messages"][-1]["content"] == "hello there", str(sent["messages"][-1]))
        check("API key sent as Bearer header, never in the body", mock.STATE.auth_seen[-1] == f"Bearer {mock.GOOD_KEY}" and mock.GOOD_KEY not in str(sent))
        check("streaming was used (SSE)", sent.get("stream") is True)

        # --- 2. multi-step task: folder + write + read-back, all verified
        await send(p, "please make note todo")
        t2 = await wait_task(conn, "completed", 60)
        note = ws / "notes" / "todo.txt"
        check("multi-step task wrote the real file", note.exists() and note.read_text() == "buy milk\n")
        v = t2["result"]["verification"]
        check("verification: all state-changing steps verified by read-back evidence", v["status"] == "verified" and v["checked"] == 2, str(v))
        ev = api(conn, "GET", f"/api/tasks/{t2['id']}").json()["events"]
        check("timeline holds plan, tool calls and tool results with evidence", [e["kind"] for e in ev].count("tool_call") == 3 and any(e["kind"] == "plan" for e in ev) and any("sha256" in str(e["data"]) for e in ev))
        # the conversation lives in the right-hand panel on every view, so there is nothing to navigate to
        await p.wait("document.body.innerText.includes('confirmed it contains')", 10)
        check("conversation shows the final answer with a verified chip", "Actions verified" in await p.text())
        await p.shot(str(SHOTS / "13-conversation-verified.png"))

        # --- 3. overwrite requires approval: DENY keeps the file
        await send(p, "overwrite keep.txt please")
        await approve(p, "Deny") if False else None
        await p.wait("!!document.querySelector('[role=alertdialog]')", 25, "overwrite approval")
        t = await p.text()
        check("overwrite asks first, in plain language", "Approve this action?" in t and "Overwrite the existing file" in t and "keep.txt" in t)
        await p.shot(str(SHOTS / "14-overwrite-approval.png"))
        check("file untouched while waiting", (ws / "keep.txt").read_text() == "ORIGINAL")
        check("task state is waiting_for_approval", (await latest(conn))["status"] == "waiting_for_approval")
        await p.click_text("Deny")
        t3 = await wait_task(conn, ("failed", "completed"))  # repair files: a denied required action ends the task as failed
        check("denied overwrite changes nothing and is reported as failed", (ws / "keep.txt").read_text() == "ORIGINAL" and t3["result"]["verification"]["status"] == "failed")
        # approve path
        await send(p, "overwrite keep.txt please")
        await p.wait("!!document.querySelector('[role=alertdialog]')", 25, "overwrite approval 2")
        await p.click_text("Approve")
        t4 = await wait_task(conn, "completed")
        check("approved overwrite writes, verifies by read-back", (ws / "keep.txt").read_text() == "NEW CONTENT" and t4["result"]["verification"]["status"] == "verified")

        # --- 4. externally visible action: open URL needs approval and is labelled unverified
        await send(p, "open site now")
        await p.wait("!!document.querySelector('[role=alertdialog]')", 25, "url approval")
        check("opening a link shows the exact URL to approve", "https://example.com/" in await p.text())
        await p.click_text("Approve")
        t5 = await wait_task(conn, "completed")
        check("dispatch-only action is labelled not independently verified", t5["result"]["verification"]["status"] == "partial" and "not independently verified" in t5["result"]["final"])

        # --- 5. launch an allowlisted app and verify by process check
        await send(p, "launch it")
        t6 = await wait_task(conn, "completed", 40)
        evs = api(conn, "GET", f"/api/tasks/{t6['id']}").json()["events"]
        check("app launch verified by real process check", t6["result"]["verification"]["status"] == "verified" and any("process_check" in str(e["data"]) for e in evs), str(t6["result"]))
        subprocess.run("pkill -f 'time.sleep\\(60\\)'", shell=True)

        # --- 6. cancel mid-stream from the UI Stop button
        await send(p, "slow story")
        await p.wait("document.body.innerText.includes('token3')", 20, "tokens streaming into the UI")
        check("tokens stream live into the conversation", True)
        await p.js("document.querySelector(\"button[aria-label='Stop the running task']\").click()")  # composer stop control (icon button)
        t7 = await wait_task(conn, "cancelled", 15)
        await asyncio.sleep(1.5)
        check("Stop cancels the task and the provider stream is closed", t7["status"] == "cancelled" and mock.STATE.aborted >= 1, f"aborted={mock.STATE.aborted}")
        n_requests = len(mock.STATE.requests)
        await asyncio.sleep(1.5)
        check("no further model requests after cancellation", len(mock.STATE.requests) == n_requests)

        # --- 7. provider failures are normalized and shown with recovery hints
        mock.STATE.ratelimit_pending = True
        await send(p, "hello again")
        t8 = await wait_task(conn, "completed", 30)
        check("429 with Retry-After is retried transparently", "Hello from the mock model" in t8["result"]["final"])
        api(conn, "PUT", "/api/secrets/nvidia_api_key", json={"value": "nvapi-WRONGKEY-0123456789abcdef"})
        await send(p, "hello with bad key")
        t9 = await wait_task(conn, "failed", 30)
        check("invalid credentials: normalized error with hint", t9["result"]["error_code"] == "invalid_credentials" and "Re-create it" in t9["result"]["error"], t9["result"]["error"])
        await p.js("document.querySelector('.nav button[title=Home]').click()")
        await asyncio.sleep(0.8)
        await p.shot(str(SHOTS / "15-invalid-key-error.png"))
        check("UI shows the credential failure", "Credentials rejected" in await p.text() or "rejected" in await p.text())
        log = (root / "ud" / "logs" / "backend.log").read_text() if (root / "ud" / "logs" / "backend.log").exists() else (root / "data" / "logs" / "backend.log").read_text()
        check("logs contain neither API keys nor the session token", mock.GOOD_KEY not in log and "WRONGKEY" not in log and conn["token"] not in log)
        check("no console errors/exceptions in the UI during the whole agent run", not p.console_errors and not p.exceptions, f"{p.console_errors[:2]} {p.exceptions[:2]}")
        await p.close()
    finally:
        subprocess.run("pkill -f 'time.sleep\\(60\\)'", shell=True)
        app.stop_all(); srv.shutdown()
    bad = [r for r in smoke.RESULTS if not r[1]]
    print(f"\n{len(smoke.RESULTS) - len(bad)}/{len(smoke.RESULTS)} agent checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
