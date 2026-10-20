from __future__ import annotations

import asyncio

import httpx

from app.events import EventBus, sse_stream
from conftest import TOKEN, call, grant, say


async def test_health_public_but_everything_else_needs_token(client, env):
    assert (await client.get("/health", headers={"X-Zonic-Token": ""})).json()["status"] == "ok"
    for path in ("/api/status", "/api/tasks", "/api/settings", "/api/memories"):
        r = await client.get(path, headers={"X-Zonic-Token": "wrong"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert (await client.get("/api/status")).status_code == 200
    assert (await client.get(f"/api/status?token={TOKEN}", headers={"X-Zonic-Token": ""})).status_code == 200


async def test_cors_only_for_allowed_origins(client):
    ok = await client.options("/api/status", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = await client.options("/api/status", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


async def test_status_reports_real_state_and_never_secrets(client, env):
    s = (await client.get("/api/status")).json()
    assert s["limited_mode"] is False and s["model"]["state"] == "untested" or s["model"]["state"] in ("ready", "untested")
    assert s["voice"]["state"] == "not_configured"
    r = await client.put("/api/secrets/gemini_api_key", json={"value": "AIzaSyTESTKEY1234567890abcdefgh"})
    assert r.json()["gemini_api_key"]["configured"] is True and "AIza" not in r.text
    full = (await client.get("/api/settings")).text + (await client.get("/api/status")).text
    assert "AIzaSyTESTKEY" not in full
    assert (await client.put("/api/secrets/gemini_api_key", json={"value": "has space inside key"})).status_code == 422
    assert (await client.delete("/api/secrets/gemini_api_key")).json()["deleted"] is True
    assert (await client.get("/api/status")).json()["voice"]["state"] == "not_configured"


async def test_permission_patch_requires_confirmation_and_elevated_rejected(client, env):
    r = await client.patch("/api/settings", json={"group": "permissions", "patch": {"launch_apps": True}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "consent_required"
    r = await client.patch("/api/settings", json={"group": "permissions", "patch": {"launch_apps": True}, "confirm_permission_change": True})
    assert r.status_code == 200 and r.json()["value"]["launch_apps"] is True
    r = await client.patch("/api/settings", json={"group": "permissions", "patch": {"elevated": True}, "confirm_permission_change": True})
    assert r.status_code == 422
    r = await client.patch("/api/settings", json={"group": "limits", "patch": {"max_steps": 999}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_settings"


async def test_onboarding_persists_resumes_and_restarts_without_losing_prefs(client, env):
    assert (await client.get("/api/onboarding")).json()["step"] == 1
    await client.patch("/api/onboarding", json={"step": 4, "skipped": ["voice"]})
    await client.patch("/api/settings", json={"group": "personalization", "patch": {"address_as": "Boss"}})
    # "restart the app": new services over the same data dir
    from conftest import make_services
    from app.main import create_app
    await env.svc.shutdown()
    svc2, *_ = make_services(env.svc.config.data_dir.parent)
    app2 = create_app(svc2.config, svc2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app2), base_url="http://t", headers={"X-Zonic-Token": TOKEN}) as c2:
        ob = (await c2.get("/api/onboarding")).json()
        assert ob["step"] == 4 and ob["skipped"] == ["voice"] and ob["completed"] is False
        assert (await c2.post("/api/onboarding/complete")).json()["completed"] is True
        await c2.post("/api/onboarding/restart")
        ob = (await c2.get("/api/onboarding")).json()
        assert ob["completed"] is False and ob["step"] == 1
        assert (await c2.get("/api/settings")).json()["settings"]["personalization"]["address_as"] == "Boss"
    await svc2.shutdown()


async def test_chat_task_approval_flow_over_http(client, env):
    grant(env.svc, env.ws, "browser")
    env.provider.script = [call("open_url", url="https://example.com/a"), say("Opened.")]
    r = await client.post("/api/chat", json={"message": "open example"})
    assert r.status_code == 202
    tid, cid = r.json()["task_id"], r.json()["conversation_id"]
    for _ in range(100):
        pend = (await client.get("/api/approvals")).json()["items"]
        if pend:
            break
        await asyncio.sleep(0.05)
    assert pend[0]["task_id"] == tid
    assert (await client.get(f"/api/tasks/{tid}")).json()["status"] == "waiting_for_approval"
    assert (await client.post(f"/api/approvals/{pend[0]['id']}", json={"decision": "approve"})).json()["state"] == "approved"
    assert (await client.post(f"/api/approvals/{pend[0]['id']}", json={"decision": "approve"})).status_code == 409  # no double-decide
    t = await env.svc.tasks.wait(tid)
    assert t["status"] == "completed"
    msgs = (await client.get(f"/api/conversations/{cid}/messages")).json()["items"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert (await client.get("/api/activity")).json()["items"]


async def test_chat_validation_and_unknown_task(client):
    assert (await client.post("/api/chat", json={"message": ""})).status_code == 422
    assert (await client.get("/api/tasks/nope")).status_code == 404
    assert (await client.post("/api/tasks/nope/cancel")).status_code == 404


async def test_memory_api_blocks_secrets_and_requires_confirmation_to_clear(client):
    r = await client.post("/api/memories", json={"content": "I like tea", "category": "preference"})
    assert r.status_code == 201 and r.json()["user_approved"] is True
    mid = r.json()["id"]
    assert (await client.post("/api/memories", json={"content": "key nvapi-ABCDEFGHIJKLMNOPQRSTUV"})).json()["error"]["code"] == "sensitive_content"
    assert (await client.get("/api/memories", params={"q": "tea"})).json()["items"][0]["id"] == mid
    assert (await client.patch(f"/api/memories/{mid}", json={"content": "I like green tea"})).json()["content"] == "I like green tea"
    assert (await client.delete("/api/memories")).status_code == 400
    assert (await client.delete("/api/memories", params={"confirm": "true"})).json()["deleted"] == 1


async def test_tools_catalog_and_toggle(client, env):
    items = {t["name"]: t for t in (await client.get("/api/tools")).json()["items"]}
    assert items["write_approved_file"]["status"] == "permission_gated" and items["mouse_action"]["risk"] == "high"
    assert items["get_active_window"]["status"] in ("unavailable", "permission_gated")  # Windows-only tool
    await client.patch("/api/tools/get_system_status", json={"enabled": False})
    assert {t["name"]: t for t in (await client.get("/api/tools")).json()["items"]}["get_system_status"]["status"] == "disabled"
    assert "get_system_status" not in [t["function"]["name"] for t in env.svc.registry.model_tools()]


async def test_readiness_and_discovery(client, env):
    r = (await client.get("/api/readiness")).json()
    by = {i["key"]: i for i in r["items"]}
    assert by["database"]["state"] == "ready" and by["permissions"]["state"] == "limited"
    assert by["voice"]["state"] == "needs_setup"
    assert (await client.post("/api/discovery/run", json={"consent": False})).status_code == 400
    d = (await client.post("/api/discovery/run", json={"consent": True, "audio_devices": [{"id": "d", "label": "Mic"}]})).json()
    assert d["audio_devices"][0]["label"] == "Mic" and "personal files and folders" in d["not_inspected"]


async def test_sse_replays_missed_events_and_signals_resync():
    bus = EventBus(buffer=3)
    for i in range(5):
        bus.publish("tick", {"i": i})
    frames = [f async for f in sse_stream(bus, last_id=3, max_events=2)]
    assert frames[0].startswith("event: hello") and "id: 4" in frames[1] and "id: 5" in frames[2]
    frames = [f async for f in sse_stream(bus, last_id=0, max_events=3)]
    assert any(f.startswith("event: resync") for f in frames)  # gap exceeds buffer
    got = []

    async def consume():
        async for f in sse_stream(bus, None, max_events=1):
            got.append(f)

    t = asyncio.ensure_future(consume())
    await asyncio.sleep(0.05)
    bus.publish("live", {"secret": "x", "token": "should-not-appear"})
    await asyncio.wait_for(t, 2)
    assert "event: live" in got[-1] and "should-not-appear" not in got[-1]
