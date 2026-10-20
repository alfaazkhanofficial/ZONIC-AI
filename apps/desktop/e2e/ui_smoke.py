"""Real-app UI robustness: startup failure + Retry, design tokens, window sizes, reduced motion, WebGL fallback, setup resume/re-run."""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cdp import Page  # noqa: E402
import smoke  # noqa: E402
from smoke import App, PORT, SHOTS, api, check, conn_of  # noqa: E402

E2E = Path(__file__).resolve().parent
SHARED_XVFB = None


def mk(root: Path, args: tuple[str, ...] = (), env: dict[str, str] | None = None) -> App:
    global SHARED_XVFB
    a = App(root, args, env)
    a.xvfb = SHARED_XVFB
    a.start()
    SHARED_XVFB = a.xvfb
    return a


def kill(a: App) -> None:
    a.proc.send_signal(signal.SIGKILL); a.proc.wait()
    time.sleep(0.5)
    import subprocess
    subprocess.run(["pkill", "-9", "-f", "electron/dist/electron --type="])  # Chromium helpers outlive a SIGKILLed main and keep the debug port
    time.sleep(0.5)


async def clip_shot(p: Page, selector: str) -> bytes:
    import base64
    r = await p.js(f"(() => {{ const b = document.querySelector({selector!r}).getBoundingClientRect(); return [b.x, b.y, b.width, b.height]; }})()")
    out = await p.send("Page.captureScreenshot", {"format": "png", "clip": {"x": r[0], "y": r[1], "width": r[2], "height": r[3], "scale": 1}})
    return base64.b64decode(out["data"])


async def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    # ---------------- A. backend fails to start -> accurate message -> Retry works
    root = Path(tempfile.mkdtemp(prefix="zonic-ui-"))
    os.environ["ZONIC_DATA_DIR"] = str(root / "data")
    env = {"ZONIC_PYTHON": str(E2E / "flaky_python.sh"), "REAL_PY": sys.executable, "FLAKY_MARKER": str(root / "marker")}
    a = mk(root, (), env)
    p = await Page.attach(PORT)
    await p.wait("document.body.innerText.includes('could not start')", 30, "startup failure screen")
    t = await p.text()
    check("startup failure is shown accurately (real reason + log tail)", "exited unexpectedly (code 3)" in t and "simulated backend crash" in t, t[:300])
    check("failure screen offers Retry and Open logs", "Retry" in t and "Open logs folder" in t)
    await p.shot(str(SHOTS / "16-backend-failure.png"))
    await p.click_text("Retry")
    await p.wait("!!document.querySelector('.ob, .shell')", 40, "UI after retry")
    check("Retry recovers: the app loads after the backend starts", True)
    conn = await conn_of(p)
    check("renderer localStorage/sessionStorage hold nothing (no secrets there)", await p.js("localStorage.length === 0 && sessionStorage.length === 0"))
    tok = await p.js("(() => { const s = getComputedStyle(document.documentElement); return ['--bg-app','--bg-card','--blue-primary','--blue-bright','--text-muted','--titanium','--warning','--danger','--radius-card'].map(k => s.getPropertyValue(k).trim().toUpperCase()).join('|'); })()")
    check("design tokens match the spec", tok == "#080A0D|#11161D|#258BFF|#49ADFF|#737F90|#D6DDE6|#F2B84B|#FF6B6B|14PX", tok)

    # ---------------- B. layout at three window sizes, reduced motion
    api(conn, "POST", "/api/onboarding/complete")
    await p.js("location.reload()")
    await p.wait("!!document.querySelector('.workspace .dash')", 20, "home dashboard")
    for w, h in ((1440, 900), (1100, 700), (960, 640)):
        await p.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
        await asyncio.sleep(1.2)  # the column widths animate (240 ms); the Xvfb CI box is slow
        m = await p.js("({sw: document.documentElement.scrollWidth, iw: innerWidth, cols: getComputedStyle(document.querySelector('.workspace')).gridTemplateColumns.split(' ').length, chat: document.querySelector('.panel-right').getBoundingClientRect().width, composer: document.querySelector('.composer').getBoundingClientRect().width, nav: document.querySelector('.nav').getBoundingClientRect().width})")
        check(f"layout {w}x{h}: no horizontal overflow, composer usable", m["sw"] <= m["iw"] + 1 and m["composer"] > 250, str(m))
        if w == 1440:
            check("wide layout: labelled navigation (left), workspace (centre), conversation (right)", m["cols"] == 3 and m["nav"] >= 240 and m["chat"] >= 300, str(m))
        if w <= 1100:
            check(f"narrow layout {w}: navigation collapses to an icon rail, conversation stays on the right", m["cols"] == 3 and m["nav"] <= 70 and m["chat"] >= 280, str(m))
        await p.shot(str(SHOTS / f"17-layout-{w}x{h}.png"))
    await p.send("Emulation.clearDeviceMetricsOverride")
    await asyncio.sleep(0.5)
    api(conn, "PATCH", "/api/settings", json={"group": "interaction", "patch": {"reduced_motion": "off", "animation_intensity": 1.0}})
    await asyncio.sleep(1.0)
    f1 = await clip_shot(p, ".avatar-box"); await asyncio.sleep(0.7); f2 = await clip_shot(p, ".avatar-box")
    check("avatar animates when motion is allowed", f1 != f2)
    api(conn, "PATCH", "/api/settings", json={"group": "interaction", "patch": {"reduced_motion": "on"}})
    await asyncio.sleep(1.2)
    static, prev = False, await clip_shot(p, ".avatar-box")
    for _ in range(12):  # software-rendered frames can lag; it must settle and stay identical
        await asyncio.sleep(0.6)
        cur = await clip_shot(p, ".avatar-box")
        if cur == prev:
            await asyncio.sleep(0.8)
            static = (await clip_shot(p, ".avatar-box")) == cur
            break
        prev = cur
    check("reduced motion: avatar becomes and stays static", static)
    check("reduced motion: setting applied to the document", await p.js("document.documentElement.dataset.motion") == "on")
    anim = await p.js("(() => { const el = document.createElement('span'); el.className = 'spinner'; document.body.appendChild(el); const n = getComputedStyle(el).animationName; el.remove(); return n; })()")
    check("reduced motion ON: CSS animations really disabled", anim == "none", str(anim))
    api(conn, "PATCH", "/api/settings", json={"group": "interaction", "patch": {"reduced_motion": "off"}})
    await asyncio.sleep(1.0)
    anim2 = await p.js("(() => { const el = document.createElement('span'); el.className = 'spinner'; document.body.appendChild(el); const n = getComputedStyle(el).animationName; el.remove(); return n; })()")
    check("reduced motion OFF: CSS animations run", anim2 == "spin", str(anim2))
    api(conn, "PATCH", "/api/settings", json={"group": "interaction", "patch": {"reduced_motion": "on"}})
    api(conn, "PATCH", "/api/settings", json={"group": "interaction", "patch": {"reduced_motion": "system"}})
    await p.close(); kill(a)

    # ---------------- C. WebGL unavailable -> useful fallback
    a = mk(root, ("--disable-gpu", "--disable-software-rasterizer", "--disable-3d-apis"), {"ZONIC_PYTHON": sys.executable})
    p = await Page.attach(PORT)
    await p.wait("!!document.querySelector('.shell, .ob')", 40, "UI no webgl")
    await asyncio.sleep(1.0)
    check("WebGL unavailable: fallback avatar shown, no canvas, state label still works", await p.js("!!document.querySelector('.avatar-fallback') && !document.querySelector('canvas')") and "Idle" in await p.text() or "Disconnected" in await p.text())
    await p.shot(str(SHOTS / "18-webgl-fallback.png"))
    await p.close(); kill(a)

    # ---------------- D. onboarding progress survives a hard kill; choices persist; setup can be re-run from Settings
    root2 = Path(tempfile.mkdtemp(prefix="zonic-ui2-"))
    os.environ["ZONIC_DATA_DIR"] = str(root2 / "data")
    a = mk(root2, (), {"ZONIC_PYTHON": sys.executable})
    p = await Page.attach(PORT)
    await p.wait("!!document.querySelector('.ob')", 40, "onboarding")
    conn = await conn_of(p)
    await p.click_text("Initialize ZONIC")
    for target in ("Main brain", "Voice setup"):
        await p.wait("!!document.querySelector('.ob-foot')", 8)
        await p.click_text("Continue")
        await asyncio.sleep(0.4)
    await p.wait("document.body.innerText.includes('Step 4 of 10')", 8, "step 4")
    await p.click_text("Skip — text only")
    await p.wait("document.body.innerText.includes('Step 5 of 10')", 8)
    await p.click_text("Continue")
    await p.wait("document.body.innerText.includes('What ZONIC may remember')", 8, "memory step")
    await p.click_text("Conversation history", "label", exact=False)
    await asyncio.sleep(0.8)
    check("memory choice saved immediately", api(conn, "GET", "/api/settings").json()["settings"]["memory"]["conversation_history"] is False)
    await p.close(); kill(a)
    a = mk(root2, (), {"ZONIC_PYTHON": sys.executable})
    p = await Page.attach(PORT)
    await p.wait("!!document.querySelector('.ob')", 40, "onboarding resumed")
    await asyncio.sleep(0.8)
    t = await p.text()
    check("onboarding resumes where it stopped after a hard kill", "Step 6 of 10" in t and "What ZONIC may remember" in t, t[:120])
    conn = await conn_of(p)
    s = api(conn, "GET", "/api/settings").json()["settings"]
    check("choices and skipped steps persisted", s["memory"]["conversation_history"] is False and "voice" in s["onboarding"]["skipped"], str(s["onboarding"]))
    api(conn, "POST", "/api/onboarding/complete")
    await p.js("location.reload()")
    await p.wait("!!document.querySelector('.shell')", 20)
    await p.js("document.querySelector('.nav button[title=Settings]').click()")
    await p.wait("document.body.innerText.includes('Diagnostics')", 8)
    await p.click_text("Diagnostics")
    await p.click_text("Re-run setup…")
    await p.wait("!!document.querySelector('[role=dialog]')", 5)
    await p.click_text("Re-run setup")
    await p.wait("!!document.querySelector('.ob')", 10, "onboarding re-run")
    check("setup can be re-run from Settings", "Step 1 of 10" in await p.text())
    s = api(conn, "GET", "/api/settings").json()["settings"]
    check("re-running setup keeps existing preferences", s["memory"]["conversation_history"] is False and s["onboarding"]["completed"] is False)
    check("no console errors in UI robustness run", not p.console_errors and not p.exceptions, f"{p.console_errors[:2]} {p.exceptions[:2]}")
    await p.close(); kill(a)
    if SHARED_XVFB:
        SHARED_XVFB.kill()
    bad = [r for r in smoke.RESULTS if not r[1]]
    print(f"\n{len(smoke.RESULTS) - len(bad)}/{len(smoke.RESULTS)} UI robustness checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
