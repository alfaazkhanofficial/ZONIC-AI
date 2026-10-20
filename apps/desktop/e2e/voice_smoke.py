"""Real-renderer voice test: Chromium's synthetic microphone -> app capture code -> WebSocket -> backend -> scripted Live stand-in -> playback.
Also covers the 'no microphone' failure path. Real Gemini and a physical microphone/speaker are NOT exercised here."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cdp import Page  # noqa: E402
import smoke  # noqa: E402
from smoke import App, api, check, conn_of, PORT, SHOTS  # noqa: E402

E2E = Path(__file__).resolve().parent
FAKE_MEDIA = ("--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required")


async def label(p: Page) -> str:
    return await p.js("document.querySelector('[role=img]') ? document.querySelector('[role=img]').getAttribute('aria-label') : ''")


async def sample(p: Page, seconds: float) -> list[str]:
    seen, end = [], time.time() + seconds
    while time.time() < end:
        l = (await label(p)).replace("ZONIC avatar. Current state: ", "")
        if not seen or seen[-1] != l:
            seen.append(l)
        await asyncio.sleep(0.08)
    return seen


async def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="zonic-voice-"))
    os.environ["ZONIC_DATA_DIR"] = str(root / "data")
    stats = root / "stats.json"
    SHOTS.mkdir(parents=True, exist_ok=True)
    env = {"ZONIC_PYTHON": str(E2E / "fake_python.sh"), "REAL_PY": sys.executable, "ZONIC_FAKE_VOICE_STATS": str(stats)}
    app = App(root, FAKE_MEDIA, env)
    try:
        app.start()
        p = await Page.attach(PORT)
        await p.wait("!!document.querySelector('.ob, .shell')", 40, "UI")
        conn = await conn_of(p)
        api(conn, "POST", "/api/onboarding/complete")
        await p.js("location.reload()")
        await p.wait("!!document.querySelector('.shell')", 20, "shell")
        check("voice shown as configured/untested (stand-in connector)", api(conn, "GET", "/api/status").json()["voice"]["state"] == "untested")
        await p.click_text("Start voice", "button", exact=False)
        seen: list[str] = []
        t0 = time.time()
        seen += await sample(p, 9)
        check("voice session reached Listening", "Listening" in seen, str(seen))
        check("microphone audio really streamed to the backend", stats.exists() and json.loads(stats.read_text())["bytes_in"] > 32000, stats.read_text() if stats.exists() else "no stats")
        st = json.loads(stats.read_text())
        per = st["bytes_in"] / max(1, st["chunks"])
        check("capture chunks are 16 kHz PCM16 (≈2.7 KB per 4096-sample block @48k)", 2000 < per < 3500, f"{per:.0f} bytes/chunk")
        check("avatar went Listening -> Speaking while audio played", "Speaking" in seen and seen.index("Speaking") > seen.index("Listening"), str(seen))
        await p.shot(str(SHOTS / "11-voice-speaking.png")) if "Speaking" in await label(p) else None
        text = await p.text()
        check("live transcript shown in the UI", "hello zonic" in text or "scripted voice reply" in text, text[-300:])
        convs = api(conn, "GET", "/api/conversations").json()["items"]
        check("voice conversation saved to history", bool(convs))
        if convs:
            msgs = api(conn, "GET", f"/api/conversations/{convs[0]['id']}/messages").json()["items"]
            check("voice transcripts stored as user + assistant messages", {m["role"] for m in msgs} == {"user", "assistant"} and all(m["metadata"].get("voice") for m in msgs), str(msgs)[:200])
        # a fresh long reply is needed to test interrupt: restart the session
        await p.click_text("Stop voice", "button", exact=False)
        await p.wait("document.body.innerText.includes('Start voice')", 10, "stopped")
        await asyncio.sleep(1.0)
        check("stopping voice closed the backend session", json.loads(stats.read_text())["closed"] is True)
        check("session state back to disconnected", api(conn, "GET", "/api/status").json()["voice"]["session_state"] == "disconnected")
        stats.unlink()
        await p.click_text("Start voice", "button", exact=False)
        await p.wait("(document.querySelector('[role=img]').getAttribute('aria-label')||'').includes('Speaking')", 15, "speaking again")
        await asyncio.sleep(0.6)
        await p.click_text("Interrupt")
        post = await sample(p, 1.6)
        check("Interrupt stops playback and returns to Listening", "Listening" in post and "Speaking" not in post[1:], str(post))
        await p.click_text("Stop voice", "button", exact=False)
        await asyncio.sleep(0.8)
        check("no console errors during voice", not p.console_errors and not p.exceptions, f"{p.console_errors[:2]} {p.exceptions[:2]}")
        await p.close()
        app.proc.terminate(); app.proc.wait(timeout=20)

        # ---- failure path: no microphone available (default Chromium in Xvfb has none)
        app2 = App(root, (), env)
        app2.xvfb = app.xvfb
        app2.start()
        p = await Page.attach(PORT)
        await p.wait("!!document.querySelector('.shell')", 40, "shell 2")
        await p.click_text("Start voice", "button", exact=False)
        await p.wait("document.body.innerText.includes('Text chat still works')", 20, "final mic error text")
        t = await p.text()
        check("missing microphone => specific actionable error + text still works", ("No microphone was found" in t or "permission was denied" in t or "Could not open the microphone" in t) and "Text chat still works" in t, t[-300:])
        await p.shot(str(SHOTS / "12-voice-no-mic.png"))
        await p.close()
        app2.proc.terminate(); app2.proc.wait(timeout=20)
    finally:
        app.stop_all()
    bad = [r for r in smoke.RESULTS if not r[1]]
    print(f"\n{len(smoke.RESULTS) - len(bad)}/{len(smoke.RESULTS)} voice checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
