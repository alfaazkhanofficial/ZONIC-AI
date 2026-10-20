from __future__ import annotations

import asyncio
import os
import sys

import psutil
import pytest

from app.tools.base import ToolContext
from app.tools.windows import prune_screenshots
from conftest import TOKEN, call, grant, make_services, say, run_task


def ctx(env, task_id=None):
    return ToolContext(task_id, asyncio.Event(), env.svc)


async def ex(env, name, **args):
    return await env.svc.registry.execute(name, args, ctx(env))


async def test_filesystem_tools_roundtrip_and_guards(env):
    grant(env.svc, env.ws, "read_workspace", "write_workspace")
    assert (await ex(env, "create_directory_in_workspace", path="docs/sub")).verified
    w = await ex(env, "write_approved_file", path="docs/a.txt", content="héllo wörld")
    assert w.ok and w.verified and "sha256" in w.evidence[0].value
    r = await ex(env, "read_approved_file", path="docs/a.txt")
    assert r.data["content"] == "héllo wörld" and r.data["untrusted_content"] is True
    again = await ex(env, "write_approved_file", path="docs/a.txt", content="x")
    assert not again.ok and again.error_code == "already_exists"
    listing = await ex(env, "list_approved_workspace", path="docs")
    assert {e["name"] for e in listing.data["entries"]} == {"a.txt", "sub"}
    assert (await ex(env, "read_approved_file", path="../../etc/passwd")).error_code == "outside_workspace"
    assert (await ex(env, "write_approved_file", path="missing_dir/f.txt", content="x")).error_code == "parent_missing"
    (env.ws / "bin.dat").write_bytes(b"\x00\x01\x02")
    assert (await ex(env, "read_approved_file", path="bin.dat")).error_code == "binary_file"
    (env.ws / "big.txt").write_text("a" * 5000)
    big = await ex(env, "read_approved_file", path="big.txt", max_bytes=100)
    assert big.data["truncated"] is True and len(big.data["content"]) == 100
    assert not list(env.ws.rglob("*.zonic-tmp"))  # no temp files left behind


async def test_launch_allowlisted_app_is_verified_with_real_process(env):
    grant(env.svc, env.ws, "launch_apps")
    env.svc.settings.update("app_allowlist", {"items": {"sleeper": {"exe": sys.executable, "args": ["-c", "import time; time.sleep(30)"], "process_names": [os.path.basename(sys.executable).lower()], "label": "Sleeper"}}}, confirmed=True)
    r = await ex(env, "launch_allowlisted_application", app="sleeper")
    try:
        assert r.ok and r.verified and r.evidence[0].type == "process_check", r
        pid = r.data["pid"]
        assert psutil.pid_exists(pid)
    finally:
        for p in psutil.process_iter(["cmdline"]):
            if p.info["cmdline"] and "time.sleep(30)" in " ".join(p.info["cmdline"]):
                p.kill()
    bad = await ex(env, "launch_allowlisted_application", app="powershell")
    assert bad.error_code == "not_allowlisted" and "sleeper" in bad.summary


async def test_allowlist_rejects_relative_path_exe(env):
    with pytest.raises(Exception):
        env.svc.settings.update("app_allowlist", {"items": {"evil": {"exe": "..\\tools\\evil.exe"}}}, confirmed=True)


async def test_open_url_validates_scheme(env):
    grant(env.svc, env.ws, "browser")
    from app.tools.windows import _open_url
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "https://user:pw@example.com/"):
        with pytest.raises(Exception):
            await _open_url({"url": bad}, ctx(env))
    assert env.opened == []


async def test_screenshot_saved_locally_with_evidence_and_retention(env):
    grant(env.svc, env.ws, "screenshot")
    r = await ex(env, "capture_screenshot")
    assert r.ok and r.verified and os.path.exists(r.data["path"]) and "text-only" in r.data["note"]
    assert str(env.svc.config.screenshot_dir) in r.data["path"] and not r.data["path"].startswith(str(env.ws))
    old = env.svc.config.screenshot_dir / "screenshot_old.png"
    old.write_bytes(b"x")
    os.utime(old, (1, 1))
    assert prune_screenshots(env.svc.config.screenshot_dir, 24) == 1 and not old.exists()


async def test_mouse_and_keyboard_after_approval_with_guards(env):
    env.svc.settings.update("permissions", {"input_control": True}, confirmed=True)

    async def approve_next():
        for _ in range(100):
            if env.svc.approvals.pending():
                env.svc.approvals.decide(env.svc.approvals.pending()[0]["id"], True)
                return
            await asyncio.sleep(0.02)

    t = asyncio.ensure_future(approve_next())
    r = await ex(env, "mouse_action", action="move", x=100, y=200)
    await t
    assert r.ok and r.verified and env.inp.actions == [("move", 100, 200)]
    t = asyncio.ensure_future(approve_next())
    r = await ex(env, "mouse_action", action="click", x=100, y=200)
    await t
    assert r.ok and not r.verified and "re-observe" in r.summary
    t = asyncio.ensure_future(approve_next())
    assert (await ex(env, "mouse_action", action="click", x=5000, y=5)).error_code == "out_of_bounds"
    await t
    for args, code in [({"action": "hotkey", "keys": ["win", "r"]}, "blocked_key_combo"), ({"action": "hotkey", "keys": ["alt", "f4"]}, "blocked_key_combo"),
                       ({"action": "type", "text": "my password=hunter2hunter2"}, "sensitive_text_blocked")]:
        t = asyncio.ensure_future(approve_next())
        assert (await ex(env, "keyboard_action", **args)).error_code == code
        await t
    t = asyncio.ensure_future(approve_next())
    r = await ex(env, "keyboard_action", action="type", text="hello")
    await t
    assert r.ok and not r.verified and ("type", "hello") in env.inp.actions


async def test_denied_input_action_does_nothing(env):
    env.svc.settings.update("permissions", {"input_control": True}, confirmed=True)

    async def deny():
        for _ in range(100):
            if env.svc.approvals.pending():
                env.svc.approvals.decide(env.svc.approvals.pending()[0]["id"], False)
                return
            await asyncio.sleep(0.02)

    t = asyncio.ensure_future(deny())
    r = await ex(env, "keyboard_action", action="type", text="hello")
    await t
    assert r.error_code == "approval_denied" and env.inp.actions == []


async def test_tool_timeout_and_crash_do_not_kill_the_agent(env):
    from app.tools.base import ToolSpec, success
    async def slow(a, c):
        await asyncio.sleep(5)
        return success("never")
    async def crash(a, c):
        raise RuntimeError(f"boom nvapi-ABCDEFGHIJKLMNOPQRSTUV")
    env.svc.registry.register(ToolSpec("slow_tool", "s", {"type": "object"}, slow, timeout_s=0.2))
    env.svc.registry.register(ToolSpec("crash_tool", "c", {"type": "object"}, crash))
    assert (await ex(env, "slow_tool")).error_code == "timeout"
    r = await ex(env, "crash_tool")
    assert r.error_code == "tool_error" and "nvapi-" not in r.summary


SKILL = {"name": "daily-note", "description": "Create a dated note file in the workspace", "parameters": {"filename": {"type": "string"}, "text": {"type": "string"}},
         "steps": [{"tool": "write_approved_file", "args": {"path": "{{filename}}", "content": "{{text}}"}}, {"tool": "read_approved_file", "args": {"path": "{{filename}}"}}]}


async def test_skill_validation_computes_permissions_and_rejects_unsafe(env):
    sk = env.svc.skills
    ok = sk.validate(SKILL)
    assert ok["valid"] and ok["permissions"] == ["read_workspace", "write_workspace"] and ok["executed_code"] is False
    selfgrant = {**SKILL, "permissions": ["elevated"]}
    assert not sk.validate(selfgrant)["valid"]  # unknown field: skills cannot declare/grant permissions
    assert not sk.validate({**SKILL, "name": "Bad Name!"})["valid"]
    assert not sk.validate({**SKILL, "steps": [{"tool": "run_skill", "args": {"name": "x"}}]})["valid"]
    assert not sk.validate({**SKILL, "steps": [{"tool": "format_disk", "args": {}}]})["valid"]
    assert not sk.validate({**SKILL, "steps": [{"tool": "write_approved_file", "args": {"path": "{{nope}}", "content": "x"}}]})["valid"]
    assert not sk.validate({**SKILL, "steps": [{"tool": "write_approved_file", "args": {"path": "a"}}]})["valid"]  # missing required arg
    assert sk.validate({"name": "danger", "description": "click things around", "steps": [{"tool": "mouse_action", "args": {"action": "click", "x": 1, "y": 1}}]})["risk"] == "high"


async def test_skill_lifecycle_approval_run_rollback(env):
    grant(env.svc, env.ws, "read_workspace", "write_workspace")
    sk = env.svc.skills
    p = sk.propose(SKILL, created_by="user")
    assert p["status"] == "pending_approval" and p["version"] == 1
    r = await sk.run("daily-note", {"filename": "n.txt", "text": "hi"}, ctx(env))
    assert not r.ok and r.error_code == "skill_not_active"  # pending skills cannot run
    aid = await sk.request_approval("daily-note", 1, None)
    row = env.svc.approvals.decide(aid, True)
    sk.apply_decision("daily-note", 1, True)
    r = await sk.run("daily-note", {"filename": "n.txt", "text": "hi"}, ctx(env))
    assert r.ok and r.verified and (env.ws / "n.txt").read_text() == "hi"
    v2 = {**SKILL, "description": "Create a note (v2)"}
    p2 = sk.propose(v2, created_by="agent:t")
    sk.apply_decision("daily-note", p2["version"], True)
    assert sk.active("daily-note")["version"] == 2
    assert sk.rollback("daily-note", 1) and sk.active("daily-note")["version"] == 1
    miss = await sk.run("daily-note", {"filename": "n2.txt"}, ctx(env))
    assert miss.error_code == "missing_parameters"
    bad_type = await sk.run("daily-note", {"filename": 5, "text": "x"}, ctx(env))
    assert bad_type.error_code == "invalid_parameters"


async def test_skill_steps_still_obey_policy(env):
    grant(env.svc, env.ws, "read_workspace")  # write NOT granted
    sk = env.svc.skills
    sk.propose(SKILL, created_by="user")
    sk.apply_decision("daily-note", 1, True)
    r = await sk.run("daily-note", {"filename": "n.txt", "text": "hi"}, ctx(env))
    assert not r.ok and r.error_code == "permission_not_granted" and not (env.ws / "n.txt").exists()


async def test_agent_proposed_skill_waits_for_user_approval_over_api(client, env):
    env.provider.script = [call("propose_skill", definition=SKILL), say("I drafted a skill; approve it in Skills & Tools.")]
    t = await run_task(env, "make me a reusable daily note skill")
    assert t["status"] == "completed"
    pend = env.svc.approvals.pending()
    assert len(pend) == 1 and pend[0]["kind"] == "register_skill" and "daily-note" in pend[0]["action_summary"]
    assert env.svc.skills.active("daily-note") is None  # not usable yet
    r = await client.post(f"/api/approvals/{pend[0]['id']}", json={"decision": "approve"})
    assert r.status_code == 200 and env.svc.skills.active("daily-note")["version"] == 1
    skills = (await client.get("/api/skills")).json()["items"]
    assert skills[0]["created_by"].startswith("agent:") and skills[0]["validation"]["executed_code"] is False


def test_parent_watchdog_helper():
    from app.main import parent_alive
    assert parent_alive(None) and parent_alive(os.getpid()) and not parent_alive(2 ** 22 + 12345)


async def test_skill_reapproval_endpoint_after_restart(client, env):
    r = await client.post("/api/skills", json={"definition": SKILL})
    assert r.status_code == 201 and r.json()["approval_id"]
    first = r.json()["approval_id"]
    assert (await client.post("/api/skills/daily-note/versions/1/request-approval")).status_code == 409  # still pending
    env.svc.approvals.decide(first, False)  # e.g. expired/denied approval; skill stays pending_approval
    r2 = await client.post("/api/skills/daily-note/versions/1/request-approval")
    assert r2.status_code == 200
    assert (await client.post(f"/api/approvals/{r2.json()['approval_id']}", json={"decision": "approve"})).status_code == 200
    assert env.svc.skills.active("daily-note")["version"] == 1
    assert (await client.post("/api/skills/daily-note/versions/9/request-approval")).status_code == 404


async def test_gui_library_that_exits_on_import_cannot_crash_the_backend(tmp_path):
    """Regression: pyautogui->mouseinfo calls sys.exit() on import without tkinter/display; that killed the real server."""
    def exits():
        raise SystemExit("NOTE: You must install tkinter on Linux")
    svc, *_ = make_services(tmp_path)
    svc.adapters.input_factory, svc.adapters._input, svc.adapters._input_error = exits, None, ""
    ok, why = svc.adapters.input_available()
    assert ok is False and "unavailable" in why
    assert svc.adapters.input_available()[0] is False  # cached, no repeated import attempts
    cat = {t["name"]: t for t in svc.registry.catalog()}
    assert cat["mouse_action"]["status"] == "unavailable" and cat["keyboard_action"]["status"] == "unavailable"
    await svc.shutdown()
