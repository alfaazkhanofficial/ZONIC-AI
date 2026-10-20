"""HTTP/SSE/WebSocket API. Every route except /health requires the per-launch token."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any, Literal

import psutil
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from . import __version__
from .db import now_iso
from .events import sse_stream
from .memory import MemoryDisabled, SensitiveContentError
from .providers.base import ConnectionTest
from .secrets_store import KNOWN
from .services import Services
from .settings_service import GROUPS, ConsentRequired
from .types import PermissionGroup

STARTED = time.monotonic()


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(status_code=status, detail={"code": code, "message": message})


def svc_of(request: Request) -> Services:
    return request.app.state.svc


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        d = exc.detail if isinstance(exc.detail, dict) else {"code": f"http_{exc.status_code}", "message": str(exc.detail)}
        return JSONResponse({"error": d}, status_code=exc.status_code)

    @app.exception_handler(ValidationError)
    async def _pyd(_: Request, exc: ValidationError) -> JSONResponse:
        msg = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:4])
        return JSONResponse({"error": {"code": "invalid_settings", "message": msg}}, status_code=422)

    @app.exception_handler(ConsentRequired)
    async def _consent(_: Request, exc: ConsentRequired) -> JSONResponse:
        return JSONResponse({"error": {"code": "consent_required", "message": str(exc)}}, status_code=409)

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def _req(_: Request, exc: RequestValidationError) -> JSONResponse:
        msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors()[:4])
        return JSONResponse({"error": {"code": "invalid_request", "message": msg}}, status_code=422)


def token_ok(request_token: str | None, expected: str) -> bool:
    return bool(request_token) and bool(expected) and hmac.compare_digest(request_token, expected)


async def require_auth(request: Request) -> None:
    got = request.headers.get("x-zonic-token") or request.query_params.get("token")
    if not token_ok(got, request.app.state.svc.config.api_token):
        raise ApiError(401, "unauthorized", "Missing or invalid session token.")


# ------------------------------------------------------------------ bodies
class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None


class DecisionBody(BaseModel):
    decision: Literal["approve", "deny"]


class SettingsBody(BaseModel):
    group: str
    patch: dict[str, Any]
    confirm_permission_change: bool = False


class SecretBody(BaseModel):
    value: str = Field(min_length=8, max_length=600)


class MemoryBody(BaseModel):
    content: str
    category: str = "knowledge"
    importance: float = 0.5


class MemoryPatch(BaseModel):
    content: str | None = None
    category: str | None = None
    importance: float | None = None
    user_approved: bool | None = None


class OnboardingPatch(BaseModel):
    step: int | None = Field(None, ge=1, le=10)
    skipped: list[str] | None = None


class ToolPatch(BaseModel):
    enabled: bool


class SkillBody(BaseModel):
    definition: dict[str, Any]


class RollbackBody(BaseModel):
    version: int


class DiscoveryBody(BaseModel):
    consent: bool
    audio_devices: list[dict[str, str]] | None = None


public = APIRouter()
router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


# ------------------------------------------------------------------ health / status / readiness
@public.get("/health")
async def health(request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    try:
        db_ok = svc.db.one("SELECT 1 AS ok") is not None
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "version": __version__, "uptime_s": round(time.monotonic() - STARTED, 1), "pid": os.getpid(),
            "dependencies": {"database": "ok" if db_ok else "error", "fts5": svc.db.fts5, "secret_backend": svc.secrets.backend}}


def _last_test(svc: Services, which: str) -> dict[str, Any] | None:
    return svc.db.get_setting(f"last_test.{which}")


def _store_test(svc: Services, which: str, t: ConnectionTest) -> dict[str, Any]:
    d = {"ok": t.ok, "code": t.code, "message": t.message, "latency_ms": t.latency_ms, "model": t.model, "hint": t.hint, "at": now_iso()}
    svc.db.set_setting(f"last_test.{which}", d)
    svc.bus.publish("status_changed", {"what": which})
    return d


def _service_state(configured: bool, last: dict[str, Any] | None) -> tuple[str, str]:
    if not configured:
        return "not_configured", "No API key saved."
    if last is None:
        return "untested", "Key saved, connection not tested yet."
    return ("ready", f"Last test passed ({last['at'][:19]}Z).") if last["ok"] else ("error", f"Last test failed: {last['message']}")


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    cat = svc.registry.catalog()
    counts = {s: sum(1 for t in cat if t["status"] == s) for s in ("available", "permission_gated", "unavailable", "disabled")}
    m_state, m_detail = _service_state(svc.provider.configured(), _last_test(svc, "nemotron"))
    v_state, v_detail = _service_state(svc.voice.configured(), _last_test(svc, "gemini"))
    now = now_iso()
    return {
        "checked_at": now, "limited_mode": not svc.provider.configured(),
        "backend": {"state": "ready", "version": __version__, "uptime_s": round(time.monotonic() - STARTED, 1), "detail": "API responding"},
        "model": {**svc.provider.describe(), "state": m_state, "detail": m_detail, "last_test": _last_test(svc, "nemotron")},
        "voice": {"state": v_state, "detail": v_detail, "session_state": svc.voice.state(), "model": svc.settings.get("gemini")["model"], "last_test": _last_test(svc, "gemini")},
        "memory": svc.memory.status(),
        "pc_control": {"granted": svc.policy.granted_groups(), "workspaces": len(svc.settings.get("workspaces")["items"]), "tools": counts},
        "onboarding": svc.settings.get("onboarding"),
        "active_tasks": len(svc.tasks.list(active_only=True)), "pending_approvals": len(svc.approvals.pending()),
        "secrets": {"backend": svc.secrets.backend, **svc.secrets.status()},
    }


async def _readiness(svc: Services, live: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add(key: str, label: str, state: str, detail: str, action: str | None = None, step: int | None = None) -> None:
        items.append({"key": key, "label": label, "state": state, "detail": detail, "action": action, "step": step})

    add("backend", "Backend", "ready", f"Python {platform.python_version()}, API v{__version__} responding.")
    ok = svc.db.integrity_ok()
    add("database", "Local database", "ready" if ok else "error", "SQLite integrity check passed." if ok else "Integrity check failed.", None if ok else "Back up and reset the data folder.")
    if live and svc.provider.configured():
        _store_test(svc, "nemotron", await svc.provider.test_connection())
    m_state, m_detail = _service_state(svc.provider.configured(), _last_test(svc, "nemotron"))
    add("model", "Main brain (Nemotron 3 Super)", {"ready": "ready", "not_configured": "needs_setup", "untested": "limited", "error": "error"}[m_state], m_detail,
        "Open model setup" if m_state != "ready" else None, 3)
    if live and svc.voice.configured():
        _store_test(svc, "gemini", await svc.voice.test_connection())
    v_state, v_detail = _service_state(svc.voice.configured(), _last_test(svc, "gemini"))
    if v_state == "ready":
        v_detail += " A real microphone round trip is confirmed only after you talk to it."
    add("voice", "Voice (Gemini Live)", {"ready": "ready", "not_configured": "needs_setup", "untested": "limited", "error": "error"}[v_state], v_detail, "Open voice setup" if v_state != "ready" else None, 4)
    cat = svc.registry.catalog()
    unavailable = [t for t in cat if t["status"] == "unavailable"]
    add("tools", "Tool registry", "ready" if not unavailable else "limited",
        f"{len(cat)} tools registered, {len(cat) - len(unavailable)} usable on this system." + (f" Unavailable: {', '.join(t['name'] for t in unavailable)}." if unavailable else ""))
    granted = svc.policy.granted_groups()
    add("permissions", "Computer permissions", "ready" if granted else "limited",
        f"Granted: {', '.join(granted)}." if granted else "Least privilege: ZONIC cannot touch files or apps until you grant permissions.", "Review permissions" if not granted else None, 7)
    mem = svc.memory.status()
    add("memory", "Memory", "ready" if mem["keyword_index"] == "fts5" else "limited", f"{mem['count']} memories; keyword index: {mem['keyword_index']}; semantic: {mem['semantic_index']['embedder'] if mem['semantic_index']['enabled'] else 'off'}.")
    return items


@router.get("/readiness")
async def readiness(request: Request, live: bool = False) -> dict[str, Any]:
    items = await _readiness(svc_of(request), live)
    return {"checked_at": now_iso(), "items": items, "can_enter": True}


@router.post("/shutdown")
async def shutdown(request: Request) -> dict[str, bool]:
    server = getattr(request.app.state, "server", None)
    if server is not None:
        server.should_exit = True
    return {"ok": server is not None}


# ------------------------------------------------------------------ events
@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    last = request.headers.get("last-event-id")
    gen = sse_stream(svc_of(request).bus, int(last) if last and last.isdigit() else None)
    return StreamingResponse(gen, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ chat / tasks / approvals
@router.post("/chat", status_code=202)
async def chat(body: ChatBody, request: Request) -> dict[str, Any]:
    return await svc_of(request).agent.submit(body.message, body.conversation_id)


@router.get("/conversations")
async def conversations(request: Request) -> dict[str, Any]:
    return {"items": svc_of(request).chat.list()}


@router.get("/conversations/{cid}/messages")
async def conversation_messages(cid: str, request: Request) -> dict[str, Any]:
    return {"items": svc_of(request).chat.messages(cid)}


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str, request: Request) -> dict[str, bool]:
    return {"deleted": svc_of(request).chat.delete(cid)}


@router.delete("/conversations")
async def clear_conversations(request: Request, confirm: bool = False) -> dict[str, bool]:
    if not confirm:
        raise ApiError(400, "confirmation_required", "Pass confirm=true to delete all conversation history.")
    svc_of(request).chat.clear_all()
    return {"cleared": True}


@router.get("/tasks")
async def list_tasks(request: Request, status: str | None = None, active: bool = False, limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    return {"items": svc_of(request).tasks.list(status=status, limit=limit, active_only=active)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict[str, Any]:
    t = svc_of(request).tasks.get(task_id, with_events=True)
    if not t:
        raise ApiError(404, "not_found", "No such task.")
    return t


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> dict[str, Any]:
    res = svc_of(request).tasks.request_cancel(task_id)
    if res.get("reason") == "not_found":
        raise ApiError(404, "not_found", "No such task.")
    return res


@router.get("/approvals")
async def approvals(request: Request) -> dict[str, Any]:
    return {"items": svc_of(request).approvals.pending()}


def _apply_approval(svc: Services, approval_id: str, approve: bool) -> dict[str, Any]:
    row = svc.approvals.decide(approval_id, approve)
    if row is None:
        raise ApiError(409, "not_pending", "That approval is no longer pending.")
    if row["kind"] == "register_skill":
        payload = json.loads(row["payload_json"]) if "payload_json" in row else {}
        svc.skills.apply_decision(payload["name"], int(payload["version"]), approve)
    return {"id": approval_id, "state": row["state"]}


@router.post("/approvals/{approval_id}")
async def decide_approval(approval_id: str, body: DecisionBody, request: Request) -> dict[str, Any]:
    return _apply_approval(svc_of(request), approval_id, body.decision == "approve")


# ------------------------------------------------------------------ memory
@router.get("/memories")
async def list_memories(request: Request, q: str | None = None, category: str | None = None, approved: bool | None = None, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    m = svc_of(request).memory
    return {"items": m.search(q, limit, include_unapproved=True) if q else m.list(category=category, approved=approved, limit=limit), "status": m.status()}


@router.post("/memories", status_code=201)
async def create_memory(body: MemoryBody, request: Request) -> dict[str, Any]:
    try:
        return svc_of(request).memory.create(body.content, body.category, "user_ui", importance=body.importance, user_approved=True)
    except SensitiveContentError as e:
        raise ApiError(422, "sensitive_content", str(e))
    except MemoryDisabled as e:
        raise ApiError(409, "memory_disabled", str(e))
    except ValueError as e:
        raise ApiError(422, "invalid_memory", str(e))


@router.patch("/memories/{mid}")
async def patch_memory(mid: str, body: MemoryPatch, request: Request) -> dict[str, Any]:
    try:
        m = svc_of(request).memory.update(mid, **body.model_dump(exclude_none=True))
    except SensitiveContentError as e:
        raise ApiError(422, "sensitive_content", str(e))
    except ValueError as e:
        raise ApiError(422, "invalid_memory", str(e))
    if not m:
        raise ApiError(404, "not_found", "No such memory.")
    return m


@router.delete("/memories/{mid}")
async def delete_memory(mid: str, request: Request) -> dict[str, bool]:
    if not svc_of(request).memory.delete(mid):
        raise ApiError(404, "not_found", "No such memory.")
    return {"deleted": True}


@router.delete("/memories")
async def clear_memories(request: Request, confirm: bool = False) -> dict[str, int]:
    if not confirm:
        raise ApiError(400, "confirmation_required", "Pass confirm=true to delete ALL memories.")
    n = svc_of(request).memory.clear()
    svc_of(request).audit.record("user", "memory_clear", "ok", details={"deleted": n})
    return {"deleted": n}


# ------------------------------------------------------------------ tools & skills
@router.get("/tools")
async def tools(request: Request) -> dict[str, Any]:
    return {"items": svc_of(request).registry.catalog()}


@router.patch("/tools/{name}")
async def patch_tool(name: str, body: ToolPatch, request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    if not svc.registry.set_enabled(name, body.enabled):
        raise ApiError(404, "not_found", "No such tool.")
    svc.audit.record("user", "tool_toggle", "ok", details={"tool": name, "enabled": body.enabled})
    return {"name": name, "enabled": body.enabled}


@router.get("/skills")
async def skills(request: Request) -> dict[str, Any]:
    return {"items": svc_of(request).skills.list()}


@router.post("/skills", status_code=201)
async def create_skill(body: SkillBody, request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    res = svc.skills.propose(body.definition, created_by="user")
    if res["status"] == "pending_approval":
        res["approval_id"] = await svc.skills.request_approval(res["name"], res["version"], None)
    return res


@router.post("/skills/{name}/versions/{version}/request-approval")
async def request_skill_approval(name: str, version: int, request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    row = svc.skills.get_version(name, version)
    if not row or row["status"] != "pending_approval":
        raise ApiError(404, "not_found", "That version is not waiting for approval.")
    if any(a["kind"] == "register_skill" and a["payload"].get("name") == name and a["payload"].get("version") == version for a in svc.approvals.pending()):
        raise ApiError(409, "already_pending", "An approval request is already open.")
    return {"approval_id": await svc.skills.request_approval(name, version, None)}


@router.post("/skills/{name}/rollback")
async def rollback_skill(name: str, body: RollbackBody, request: Request) -> dict[str, bool]:
    if not svc_of(request).skills.rollback(name, body.version):
        raise ApiError(404, "not_found", "That version cannot be activated.")
    return {"ok": True}


@router.delete("/skills/{name}")
async def delete_skill(name: str, request: Request) -> dict[str, bool]:
    if not svc_of(request).skills.delete(name):
        raise ApiError(404, "not_found", "No such skill.")
    return {"deleted": True}


# ------------------------------------------------------------------ settings, secrets, onboarding
@router.get("/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    return {"settings": svc.settings.all(), "secrets": svc.secrets.status(), "secret_backend": svc.secrets.backend, "permission_labels": {g.value: g.name for g in PermissionGroup}}


@router.patch("/settings")
async def patch_settings(body: SettingsBody, request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    if body.group not in GROUPS:
        raise ApiError(404, "unknown_group", f"Unknown settings group '{body.group}'.")
    if body.group == "permissions" and body.patch.get("elevated"):
        raise ApiError(422, "unsupported", "Elevated actions are not available in this release.")
    new = svc.settings.update(body.group, body.patch, confirmed=body.confirm_permission_change)
    svc.audit.record("user", f"settings:{body.group}", "ok", details={"patch": body.patch if body.group in ("permissions", "workspaces", "app_allowlist", "limits") else list(body.patch)})
    svc.bus.publish("status_changed", {"what": body.group})
    return {"group": body.group, "value": new}


@router.put("/secrets/{name}")
async def put_secret(name: str, body: SecretBody, request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    if name not in KNOWN:
        raise ApiError(404, "unknown_secret", "Unknown credential name.")
    value = body.value.strip()
    if any(c.isspace() for c in value):
        raise ApiError(422, "invalid_secret", "Keys cannot contain spaces or line breaks.")
    svc.secrets.set(name, value)
    svc.db.execute("DELETE FROM settings WHERE key=?", (f"last_test.{'nemotron' if name == 'nvidia_api_key' else 'gemini'}",))
    svc.audit.record("user", "secret_saved", "ok", details={"name": name})
    svc.bus.publish("status_changed", {"what": name})
    return {name: svc.secrets.status()[name]}


@router.delete("/secrets/{name}")
async def delete_secret(name: str, request: Request) -> dict[str, bool]:
    svc = svc_of(request)
    if name not in KNOWN:
        raise ApiError(404, "unknown_secret", "Unknown credential name.")
    svc.secrets.delete(name)
    svc.audit.record("user", "secret_deleted", "ok", details={"name": name})
    svc.bus.publish("status_changed", {"what": name})
    return {"deleted": True}


@router.post("/providers/nemotron/test")
async def test_nemotron(request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    return _store_test(svc, "nemotron", await svc.provider.test_connection())


@router.post("/providers/gemini/test")
async def test_gemini(request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    return _store_test(svc, "gemini", await svc.voice.test_connection())


@router.get("/onboarding")
async def get_onboarding(request: Request) -> dict[str, Any]:
    return svc_of(request).settings.get("onboarding")


@router.patch("/onboarding")
async def patch_onboarding(body: OnboardingPatch, request: Request) -> dict[str, Any]:
    return svc_of(request).settings.update("onboarding", body.model_dump(exclude_none=True))


@router.post("/onboarding/complete")
async def complete_onboarding(request: Request) -> dict[str, Any]:
    return svc_of(request).settings.mark_onboarding_complete()


@router.post("/onboarding/restart")
async def restart_onboarding(request: Request) -> dict[str, Any]:
    return svc_of(request).settings.update("onboarding", {"completed": False, "completed_at": None, "step": 1})  # preferences are kept


@router.post("/discovery/run")
async def run_discovery(body: DiscoveryBody, request: Request) -> dict[str, Any]:
    svc = svc_of(request)
    if not body.consent:
        raise ApiError(400, "consent_required", "Discovery only runs with your consent.")
    mem = psutil.virtual_memory()
    result = {
        "os": platform.platform(), "machine": platform.machine(), "cpu_threads": psutil.cpu_count(logical=True), "ram_gb": round(mem.total / 1e9, 1),
        "tools_found": {t: shutil.which(t) is not None for t in ("python", "py", "node", "npm", "git", "code", "winget")},
        "approved_workspaces": [{"name": w["name"], "path": w["path"]} for w in svc.settings.get("workspaces")["items"]],
        "audio_devices": (body.audio_devices or [])[:40],
        "inspected": ["OS version", "common developer tools on PATH", "approved workspace names", "audio device names (from your browser engine)"],
        "not_inspected": ["personal files and folders", "browser data", "installed-program inventory", "network"],
    }
    svc.settings.update("discovery", {"result": result, "ran_at": now_iso()})
    svc.audit.record("user", "discovery_run", "ok")
    return result


@router.get("/projects")
async def projects(request: Request) -> dict[str, Any]:
    out = []
    for w in svc_of(request).settings.get("workspaces")["items"]:
        p = Path(w["path"])
        exists = p.is_dir()
        try:
            names = sorted(c.name for c in p.iterdir())[:50] if exists else []
            total = sum(1 for _ in p.iterdir()) if exists else 0
        except OSError:
            names, total = [], 0
        out.append({**w, "exists": exists, "entry_count": total, "preview": names})
    return {"items": out}


@router.get("/activity")
async def activity(request: Request, limit: int = Query(100, ge=1, le=300)) -> dict[str, Any]:
    svc = svc_of(request)
    items = [{"ts": e["timestamp"], "source": "task", "kind": e["kind"], "message": e["message"], "task_id": e["task_id"], "outcome": (e["data"] or {}).get("ok")} for e in svc.tasks.recent_events(limit)]
    items += [{"ts": a["timestamp"], "source": "audit", "kind": a["action"], "message": f"{a['actor']}: {a['action']}", "task_id": a["task_id"], "outcome": a["outcome"]} for a in svc.audit.recent(limit)]
    items.sort(key=lambda x: x["ts"], reverse=True)
    return {"items": items[:limit]}


@router.get("/logs")
async def logs(request: Request, tail: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    path = svc_of(request).config.log_path
    if not path.exists():
        return {"lines": []}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return {"lines": fh.read().splitlines()[-tail:]}


# ------------------------------------------------------------------ voice websocket
@public.websocket("/api/voice/ws")
async def voice_ws(ws: WebSocket) -> None:
    svc: Services = ws.app.state.svc
    if not token_ok(ws.query_params.get("token"), svc.config.api_token):
        await ws.close(code=4401)
        return
    await ws.accept()
    lock = asyncio.Lock()

    async def emit(msg: dict[str, Any]) -> None:
        async with lock:
            try:
                await ws.send_json(msg)
            except Exception:
                pass

    async def send_audio(b: bytes) -> None:
        async with lock:
            try:
                await ws.send_bytes(b)
            except Exception:
                pass

    session = svc.voice.new_session(emit, send_audio)
    try:
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                break
            if m.get("bytes") is not None:
                await session.feed_audio(m["bytes"])
            elif m.get("text"):
                try:
                    cmd = json.loads(m["text"]).get("type")
                except ValueError:
                    continue
                if cmd == "start":
                    await session.start()
                elif cmd == "stop":
                    await session.stop()
                elif cmd == "interrupt":
                    await session.interrupt()
    finally:
        await session.stop()
        svc.voice.release(session)


def mount(app: FastAPI) -> None:
    app.include_router(public)
    app.include_router(router)
