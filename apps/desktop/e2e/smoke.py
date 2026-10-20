"""End-to-end smoke test of the REAL app: Electron main -> Python backend -> React UI, driven over DevTools.

Linux/CI usage (needs Xvfb, a built UI and compiled Electron main):
    npm run build && npm run build:electron
    python e2e/smoke.py            # from apps/desktop, using backend/.venv or $ZONIC_PYTHON
Native dialogs (folder picker) cannot be automated, so workspaces are added through the same API the dialog feeds."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from cdp import Page  # noqa: E402

HERE = Path(__file__).resolve().parent
DESKTOP = HERE.parent
PORT = 9333
SHOTS = Path(os.environ.get("ZONIC_E2E_SHOTS", tempfile.mkdtemp(prefix="zonic-shots-")))
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


class App:
    def __init__(self, root: Path, extra_args: tuple[str, ...] = (), extra_env: dict[str, str] | None = None):
        self.root, self.extra_args, self.extra_env = root, extra_args, extra_env or {}
        self.proc: subprocess.Popen | None = None
        self.xvfb: subprocess.Popen | None = None
        self.log = open(root / "electron.log", "ab")

    def start(self) -> None:
        env = {**os.environ, "DISPLAY": ":99", "HOME": str(self.root / "home"), "ZONIC_DATA_DIR": str(self.root / "data")}
        env.setdefault("ZONIC_PYTHON", sys.executable)
        env.update(self.extra_env)
        (self.root / "home").mkdir(exist_ok=True)
        if self.xvfb is None:
            if subprocess.run(["pgrep", "-x", "Xvfb"], capture_output=True).returncode != 0:  # no live X server: remove stale lock/socket
                for stale in ("/tmp/.X99-lock", "/tmp/.X11-unix/X99"):
                    try:
                        os.remove(stale)
                    except FileNotFoundError:
                        pass
            self.xvfb = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1440x900x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
        import socket
        for _ in range(60):  # a previous instance's helpers may still hold the debug port for a moment
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", PORT)) != 0:
                    break
            time.sleep(0.5)
        exe = DESKTOP / "node_modules" / "electron" / "dist" / "electron"
        self.proc = subprocess.Popen([str(exe), ".", "--no-sandbox", "--disable-dev-shm-usage", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                                      f"--remote-debugging-port={PORT}", f"--user-data-dir={self.root / 'ud'}", *self.extra_args], cwd=str(DESKTOP), env=env, stdout=self.log, stderr=self.log, start_new_session=True)

    def backend_pids(self) -> list[int]:
        out = subprocess.run(["pgrep", "-f", "-x", ".*-m app\\.main"], capture_output=True, text=True).stdout.split()
        return [int(p) for p in out]

    def kill_group(self) -> None:
        """Chromium helper processes can outlive a SIGKILLed main process; clean the whole group between launches."""
        if self.proc:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def stop_all(self) -> None:
        self.kill_group()
        for p in (self.proc, self.xvfb):
            if p and p.poll() is None:
                p.kill()


async def conn_of(p: Page) -> dict:
    return await p.js("window.zonic.getConnection()")


def api(conn: dict, method: str, path: str, **kw):
    r = httpx.request(method, conn["baseUrl"] + path, headers={"X-Zonic-Token": conn["token"]}, timeout=20, **kw)
    return r


async def settle(p: Page, ms: int = 400) -> None:
    await asyncio.sleep(ms / 1000)


async def onboarding(p: Page, conn: dict, ws: Path) -> None:
    await p.wait("!!document.querySelector('.ob')", 30, "onboarding")
    t = await p.text()
    check("onboarding starts at step 1 with honest copy", "Welcome to ZONIC M4" in t and "Step 1 of 10" in t)
    check("3D avatar canvas renders (WebGL)", await p.js("!!document.querySelector('canvas')"))
    check("renderer has no Node access (isolation)", await p.js("typeof require === 'undefined' && typeof process === 'undefined'"))
    check("bridge exposes only the whitelisted functions", await p.js("Object.keys(window.zonic).sort().join(',')") == "getBackendState,getConnection,getStartupLaunch,onBackendState,openLogs,pickExecutable,pickFolder,retryBackend,setStartupLaunch")
    await p.click_text("Learn what it can do")
    check("capabilities are described with limits", "not magic or fully autonomous" in await p.text())
    await p.click_text("Initialize ZONIC")
    await p.wait("document.body.innerText.includes('How you’ll interact')", 8, "step 2")
    check("step persisted server-side", api(conn, "GET", "/api/onboarding").json()["step"] == 2)
    await p.click_text("Continue")  # -> 3
    await p.wait("document.body.innerText.includes('Connect the main brain')", 8, "step 3")
    await p.click_text("Test connection")
    await p.wait("document.body.innerText.includes('Failed')", 20, "failed test result")
    t = await p.text()
    check("no key => real failure shown, never success", "No NVIDIA API key" in t and "Connected" not in t.replace("Connected to", "x"))
    await p.set_value("input[type=password]", "nvapi-E2E-FAKE-KEY-0123456789abcdef")
    await p.click_text("Save key")
    await p.wait("document.body.innerText.includes('A key is saved')", 10, "key saved hint")
    t = await p.text()
    check("key is masked/cleared after saving and never shown again", "E2E-FAKE-KEY" not in t and await p.js("document.querySelector('input[type=password]').value === ''"))
    settings = api(conn, "GET", "/api/settings").text + api(conn, "GET", "/api/status").text
    check("API never returns the key", "E2E-FAKE-KEY" not in settings)
    sec = Path(os.environ["ZONIC_DATA_DIR"]) / "secrets.json"
    check("key stored outside settings DB (credential store/restricted file)", True if not sec.exists() else (sec.stat().st_mode & 0o077) == 0)
    await p.click_text("Test connection")
    await p.wait("document.body.innerText.includes('Failed')", 60, "network failure result")
    t = await p.text()
    check("unreachable provider reported specifically (network/credentials), not as success", any(s in t for s in ("Network error", "Credentials rejected", "Could not reach", "did not respond")), t[t.find("Failed"):t.find("Failed") + 160])
    await p.shot(str(SHOTS / "02-model-failure-honest.png"))
    await p.click_text("Skip — limited mode")  # -> 4
    await p.wait("document.body.innerText.includes('Voice setup')", 8, "step 4")
    await p.click_text("Test Gemini Live connection")
    await p.wait("document.body.innerText.includes('No Gemini API key')", 15, "voice not configured")
    check("voice test without key fails honestly", True)
    await p.click_text("Skip — text only")  # -> 5
    await p.wait("document.body.innerText.includes('Meet the avatar')", 8, "step 5")
    check("avatar preview is labelled as simulated", "simulated" in await p.text())
    for state in ("Thinking", "Speaking", "Executing", "Waiting for approval", "Error", "Idle"):
        await p.click_text(state)
        await settle(p, 250)
        check(f"avatar preview state: {state}", state in await p.js("document.querySelector('[role=img]').getAttribute('aria-label')"))
    await p.shot(str(SHOTS / "03-avatar-preview.png"))
    await p.click_text("Continue")  # -> 6
    await p.wait("document.body.innerText.includes('What ZONIC may remember')", 8, "step 6")
    await p.click_text("Continue")  # -> 7
    await p.wait("document.body.innerText.includes('Computer permissions')", 8, "step 7")
    perms = api(conn, "GET", "/api/settings").json()["settings"]["permissions"]
    check("every permission defaults to OFF (least privilege)", not any(perms.values()))
    await p.click_text("Read files in approved workspaces", "label", exact=False)
    await p.wait("!!document.querySelector('[role=dialog]')", 5, "consent dialog")
    check("granting a permission asks for explicit confirmation", "Allow this?" in await p.text())
    check("permission NOT granted before confirming", not api(conn, "GET", "/api/settings").json()["settings"]["permissions"]["read_workspace"])
    await p.click_text("Allow")
    await p.wait("document.querySelector('label.toggle input:checked')", 8, "toggle on")
    check("permission granted after confirming (backend)", api(conn, "GET", "/api/settings").json()["settings"]["permissions"]["read_workspace"])
    r = api(conn, "PATCH", "/api/settings", json={"group": "permissions", "patch": {"write_workspace": True}})
    check("backend refuses permission change without consent flag", r.status_code == 409)
    r = api(conn, "PATCH", "/api/settings", json={"group": "workspaces", "patch": {"items": [{"name": "E2E workspace", "path": str(ws)}]}, "confirm_permission_change": True})
    check("workspace added (same API the folder dialog uses)", r.status_code == 200, r.text)
    await settle(p, 800)
    check("UI shows the workspace live", "E2E workspace" in await p.text())
    await p.click_text("Continue")  # -> 8
    await p.wait("document.body.innerText.includes('System discovery')", 8, "step 8")
    check("run button disabled until consent", await p.js("[...document.querySelectorAll('button')].find(b=>b.textContent.includes('Run discovery')).disabled"))
    await p.click_text("I consent to this check", "label", exact=False)
    await p.click_text("Run discovery")
    await p.wait("document.body.innerText.includes('Result')", 15, "discovery result")
    check("discovery result honest about what was inspected", "Not inspected" in await p.text() and "OS:" in await p.text())
    await p.click_text("Continue")  # -> 9
    await p.wait("document.body.innerText.includes('Make it yours')", 8, "step 9")
    await p.set_value("input[placeholder^='A name or nickname']", "Boss")
    await p.js("document.querySelector(\"input[placeholder^='A name or nickname']\").dispatchEvent(new FocusEvent('focusout', {bubbles:true}))")
    await p.js("document.querySelector(\"input[placeholder^='A name or nickname']\").blur()")
    await settle(p, 800)
    check("personalization persisted", api(conn, "GET", "/api/settings").json()["settings"]["personalization"]["address_as"] == "Boss")
    await p.click_text("Continue")  # -> 10
    await p.wait("document.body.innerText.includes('Readiness report')", 8, "step 10")
    await p.wait("document.body.innerText.includes('Local database')", 10, "readiness items")
    t = await p.text()
    check("readiness: real states with recovery actions", "Needs setup" in t and "Ready" in t and "Add" in t or "Open voice setup" in t)
    await p.shot(str(SHOTS / "04-readiness.png"))
    await p.click_text("Enter ZONIC M4")
    await p.wait("!!document.querySelector('.shell')", 15, "app shell")
    check("onboarding completion persisted", api(conn, "GET", "/api/onboarding").json()["completed"] is True)


async def shell(p: Page, conn: dict) -> None:
    t = await p.text()
    check("dashboard: nav items present", all(x in t for x in ("Home", "Tasks", "Memory", "Skills & Tools", "Projects", "Permissions", "Activity", "Diagnostics", "Settings")))
    check("dashboard: status card rows from real checks", all(x in t for x in ("Python backend", "Nemotron 3 Super", "Gemini Live voice", "Memory", "PC control")))
    check("dashboard: Gemini shown as Needs setup (no key)", "Gemini Live voice" in t and "Needs setup" in t)
    check("dashboard: top bar shows real backend state", "Backend ready" in t)
    check("avatar label reflects real state", "Idle" in await p.js("document.querySelector('[role=img]').getAttribute('aria-label')") or "Error" in await p.js("document.querySelector('[role=img]').getAttribute('aria-label')"))
    await p.shot(str(SHOTS / "05-dashboard.png"))
    # chat against an unreachable/unauthorised provider: must fail honestly
    await p.set_value("textarea[aria-label='Message ZONIC']", "hello from the e2e test")
    await p.click_text("Send")
    await p.wait("document.body.innerText.includes('Failed')", 90, "failed task chip")
    await settle(p, 500)
    t = await p.text()
    check("failed chat is shown as Failed (never fake success)", "Failed" in t)
    label = await p.js("document.querySelector('[role=img]').getAttribute('aria-label')")
    check("avatar shows Error after a real failure", "Error" in label, label)
    await p.shot(str(SHOTS / "06-dashboard-error.png"))
    tasks = api(conn, "GET", "/api/tasks").json()["items"]
    check("task persisted with error details", tasks and tasks[0]["status"] == "failed" and tasks[0]["result"].get("error"))
    # every screen renders
    for label_, heading in [("Tasks", "Task center"), ("Memory", "Memory center"), ("Skills & Tools", "Skills & Tools"), ("Projects", "Approved workspaces"),
                            ("Permissions", "Permissions center"), ("Activity", "Activity"), ("Settings", "Settings")]:
        await p.click_text(label_, "button", exact=False) if label_ != "Settings" else await p.js("document.querySelector('.nav button[title=Settings]').click()")
        try:
            await p.wait(f"document.body.innerText.toLowerCase().includes({json.dumps(heading.lower())})", 8, label_)  # card titles render uppercase
            check(f"screen renders: {label_}", True)
        except TimeoutError as e:
            check(f"screen renders: {label_}", False, str(e))
    await p.shot(str(SHOTS / "07-settings.png"))


async def features(p: Page, conn: dict) -> None:
    # memory add / search / delete through the UI
    await p.js("document.querySelector('.nav button[title=Memory]').click()")
    await p.wait("document.body.innerText.includes('Memory center')", 8)
    await p.click_text("+ Add memory")
    await p.wait("!!document.querySelector('[role=dialog] textarea')", 5)
    await p.set_value("[role=dialog] textarea", "The e2e test project is called Falcon")
    await p.click_text("Save")
    await p.wait("document.body.innerText.includes('Falcon')", 8, "memory listed")
    check("memory saved and listed", True)
    await p.set_value("input[aria-label='Search memories']", "falcon")
    await settle(p, 700)
    check("memory search finds it", "Falcon" in await p.text())
    await p.click_text("+ Add memory")
    await p.wait("!!document.querySelector('[role=dialog] textarea')", 5)
    await p.set_value("[role=dialog] textarea", "my key is nvapi-ABCDEFGHIJKLMNOPQRSTUV")
    await p.click_text("Save")
    await p.wait("document.body.innerText.includes('looks like a secret')", 8, "secret refused")
    check("secrets are refused by memory", True)
    await p.js("document.querySelector('.scrim').dispatchEvent(new MouseEvent('mousedown', {bubbles:true}))")
    await settle(p, 300)
    await p.click_text("Delete")
    await p.wait("!!document.querySelector('[role=dialog]')", 5)
    check("delete asks for confirmation", "Delete this memory?" in await p.text())
    await p.click_text("Cancel")
    await settle(p, 300)
    check("cancelled delete keeps the memory", len(api(conn, "GET", "/api/memories").json()["items"]) == 1)
    # skill approval through the real approval dialog
    skill = {"name": "e2e-note", "description": "Write a note then read it back", "parameters": {"f": {"type": "string"}},
             "steps": [{"tool": "write_approved_file", "args": {"path": "{{f}}", "content": "hi"}}, {"tool": "read_approved_file", "args": {"path": "{{f}}"}}]}
    r = api(conn, "POST", "/api/skills", json={"definition": skill})
    check("skill passes validation", r.status_code == 201 and r.json()["status"] == "pending_approval", r.text)
    await p.wait("!!document.querySelector('[role=alertdialog]')", 10, "approval dialog")
    t = await p.text()
    check("approval dialog explains the request", "Approve a new skill?" in t and "e2e-note" in t and "no code" in t.lower())
    check("approval focus starts on Deny (safe default)", await p.js("document.activeElement && document.activeElement.textContent.trim()") == "Deny")
    await p.shot(str(SHOTS / "08-approval-dialog.png"))
    check("skill not usable before approval", api(conn, "GET", "/api/skills").json()["items"][0]["status"] == "pending_approval")
    await p.click_text("Approve")
    await settle(p, 800)
    check("skill active after approval", api(conn, "GET", "/api/skills").json()["items"][0]["status"] == "active")
    # tools screen reflects headless environment honestly
    await p.js("document.querySelector('.nav button[title=\"Skills & Tools\"]').click()")
    await p.wait("document.body.innerText.includes('mouse_action')", 8)
    t = await p.text()
    check("tools catalog lists permission/availability states", "Needs permission" in t and "Unavailable" in t)
    await p.shot(str(SHOTS / "09-tools.png"))
    check("no console errors or exceptions so far", not p.console_errors and not p.exceptions, f"{p.console_errors[:3]} {p.exceptions[:3]}")


async def run() -> int:
    root = Path(tempfile.mkdtemp(prefix="zonic-e2e-"))
    os.environ["ZONIC_DATA_DIR"] = str(root / "data")
    ws = root / "workspace"; ws.mkdir()
    SHOTS.mkdir(parents=True, exist_ok=True)
    app = App(root)
    try:
        app.start()
        p = await Page.attach(PORT)
        await p.wait("!!document.querySelector('.ob, .shell')", 40, "first UI")
        conn = await conn_of(p)
        await p.shot(str(SHOTS / "01-welcome.png"))
        await onboarding(p, conn, ws)
        await shell(p, conn)
        await features(p, conn)
        # ---- crash safety: kill Electron hard; backend must not be orphaned
        pids_before = app.backend_pids()
        check("backend process is running", len(pids_before) >= 1, str(pids_before))
        await p.close()
        app.proc.send_signal(signal.SIGKILL); app.proc.wait()
        subprocess.run(["pkill", "-9", "-f", "electron/dist/electron --type="])  # helper processes keep the debug port after a SIGKILL
        deadline = time.time() + 15
        while time.time() < deadline and app.backend_pids():
            time.sleep(0.5)
        check("backend exits by itself after the app is killed (no orphan)", not app.backend_pids(), str(app.backend_pids()))
        app.kill_group(); time.sleep(1)
        # ---- restart: state persists, onboarding is not repeated
        app.start()
        p = await Page.attach(PORT)
        await p.wait("!!document.querySelector('.ob, .shell')", 40, "UI after restart")
        check("after restart the app opens the dashboard directly", await p.js("!!document.querySelector('.shell')") and not await p.js("!!document.querySelector('.ob')"))
        conn = await conn_of(p)
        check("settings survive restart", api(conn, "GET", "/api/settings").json()["settings"]["personalization"]["address_as"] == "Boss")
        check("memory survives restart", any("Falcon" in m["content"] for m in api(conn, "GET", "/api/memories").json()["items"]))
        check("failed task history survives restart", any(t["status"] == "failed" for t in api(conn, "GET", "/api/tasks").json()["items"]))
        check("API key survives restart (not shown)", api(conn, "GET", "/api/settings").json()["secrets"]["nvidia_api_key"]["configured"] is True)
        await settle(p, 1500)
        await p.shot(str(SHOTS / "10-after-restart.png"))
        # ---- graceful shutdown: closing the window stops the backend cleanly
        pids = app.backend_pids()
        try:
            await asyncio.wait_for(p.send("Page.close"), 5)  # closes the BrowserWindow like the user clicking X
        except (asyncio.TimeoutError, Exception):
            pass
        deadline = time.time() + 20
        while time.time() < deadline and (app.proc.poll() is None or app.backend_pids()):
            time.sleep(0.5)
        check("closing the window quits the app and stops the backend", app.proc.poll() is not None and not app.backend_pids(), f"proc={app.proc.poll()} backend={app.backend_pids()} before={pids}")
        log = (root / "ud" / "logs" / "backend.log").read_text()
        check("backend log has clean shutdown and no leaked secrets", "stopped cleanly" in log and "E2E-FAKE-KEY" not in log and conn["token"] not in log)
    finally:
        app.stop_all()
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} checks passed. Screenshots: {SHOTS}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
