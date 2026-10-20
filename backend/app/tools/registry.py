"""Tool registry + the single execution path (validate -> availability -> policy -> approval -> run -> audit)."""
from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import Any

from jsonschema import Draft202012Validator

from ..permissions import GROUP_LABELS, PolicyViolation
from ..redaction import redact, redact_obj
from ..types import Risk, TaskState
from .base import Evidence, ToolContext, ToolError, ToolResult, ToolSpec, failure

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,48}$")


def shorten(obj: Any, limit: int = 200) -> Any:
    if isinstance(obj, str):
        return obj if len(obj) <= limit else obj[:limit] + f"…[+{len(obj) - limit} chars]"
    if isinstance(obj, dict):
        return {k: shorten(v, limit) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shorten(v, limit) for v in obj[:20]]
    return obj


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self.svc: Any = None  # set by Services

    # ---- registration -------------------------------------------------
    def register(self, spec: ToolSpec) -> None:
        if not _NAME.match(spec.name):
            raise ValueError(f"invalid tool name {spec.name!r}")
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool {spec.name!r}")
        Draft202012Validator.check_schema(spec.input_schema)
        if spec.risk == Risk.HIGH and spec.approval == "never":
            raise ValueError(f"{spec.name}: high-risk tools must require approval")
        if spec.state_changing and not spec.verification:
            raise ValueError(f"{spec.name}: state-changing tools must declare a verification strategy")
        if spec.approval == "dynamic" and not spec.needs_approval:
            raise ValueError(f"{spec.name}: dynamic approval needs a needs_approval callback")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[ToolSpec]:
        return [self._tools[n] for n in self.names()]

    # ---- state --------------------------------------------------------
    def _platform_ok(self, spec: ToolSpec) -> bool:
        return spec.platforms is None or any(sys.platform.startswith(p) for p in spec.platforms)

    def availability(self, spec: ToolSpec) -> tuple[bool, str | None]:
        if not self._platform_ok(spec):
            return False, f"Not supported on this operating system ({sys.platform})."
        if spec.availability:
            return spec.availability()
        return True, None

    def is_enabled(self, name: str) -> bool:
        row = self.svc.db.one("SELECT enabled FROM tool_records WHERE name=?", (name,))
        return bool(row["enabled"]) if row else True

    def sync_records(self) -> None:
        db = self.svc.db
        for s in self.all():
            db.execute(
                "INSERT INTO tool_records(name, version, description, schema_json, permission, validation_state) VALUES (?,?,?,?,?,'builtin') "
                "ON CONFLICT(name) DO UPDATE SET version=excluded.version, description=excluded.description, schema_json=excluded.schema_json, permission=excluded.permission",
                (s.name, s.version, s.description, json.dumps(s.input_schema), s.permission.value if s.permission else None),
            )

    def set_enabled(self, name: str, enabled: bool) -> bool:
        if name not in self._tools:
            return False
        self.svc.db.execute("UPDATE tool_records SET enabled=? WHERE name=?", (1 if enabled else 0, name))
        return True

    def status_of(self, spec: ToolSpec) -> tuple[str, str | None]:
        ok, why = self.availability(spec)
        if not ok:
            return "unavailable", why
        if not self.is_enabled(spec.name):
            return "disabled", "Disabled by you in Skills & Tools."
        if spec.permission is not None and not self.svc.policy.granted(spec.permission):
            return "permission_gated", f"Needs permission: {GROUP_LABELS[spec.permission]}."
        return "available", None

    def catalog(self) -> list[dict[str, Any]]:
        out = []
        for s in self.all():
            status, reason = self.status_of(s)
            out.append({
                "name": s.name, "version": s.version, "description": s.description, "input_schema": s.input_schema,
                "permission": s.permission.value if s.permission else None, "risk": s.risk.value, "side_effect": s.side_effect,
                "timeout_s": s.timeout_s, "verification": s.verification or "n/a (read-only)", "approval": s.approval,
                "status": status, "reason": reason, "enabled": self.is_enabled(s.name), "model_visible": s.model_visible,
            })
        return out

    def model_tools(self) -> list[dict[str, Any]]:
        """OpenAI-style function definitions. Permission-gated tools are included (flagged) so the model can explain the gap."""
        defs = []
        for s in self.all():
            if not s.model_visible:
                continue
            status, reason = self.status_of(s)
            if status in ("unavailable", "disabled"):
                continue
            desc = s.description + (f" [CURRENTLY NOT PERMITTED: {reason}]" if status == "permission_gated" else "")
            defs.append({"type": "function", "function": {"name": s.name, "description": desc, "parameters": s.input_schema}})
        return defs

    # ---- execution ----------------------------------------------------
    def validate_args(self, spec: ToolSpec, args: Any) -> str | None:
        if not isinstance(args, dict):
            return "arguments must be a JSON object"
        errs = sorted(Draft202012Validator(spec.input_schema).iter_errors(args), key=lambda e: [str(p) for p in e.path])
        if errs:
            return "; ".join(f"{'.'.join(map(str, e.path)) or 'arguments'}: {e.message}" for e in errs[:3])
        return None

    async def execute(self, name: str, args: Any, ctx: ToolContext) -> ToolResult:
        svc = ctx.svc
        spec = self._tools.get(name)
        if spec is None:
            return self._finish(ctx, name, args, failure("unknown_tool", f"There is no registered tool named '{name}'."))
        bad = self.validate_args(spec, args)
        if bad:
            return self._finish(ctx, name, args, failure("invalid_arguments", f"Invalid arguments for {name}: {bad}"))
        status, reason = self.status_of(spec)
        if status == "unavailable":
            return self._finish(ctx, name, args, failure("tool_unavailable", reason or "Tool unavailable."))
        if status == "disabled":
            return self._finish(ctx, name, args, failure("tool_disabled", reason or "Tool disabled."))
        decision = svc.policy.decide(spec, args, ctx)
        if decision.outcome == "deny":
            return self._finish(ctx, name, args, failure(decision.code, decision.reason))
        if decision.outcome == "approval":
            if ctx.task_id:
                svc.tasks.set_state(ctx.task_id, TaskState.WAITING_FOR_APPROVAL, message=f"Waiting for approval: {decision.summary}")
            aid = await svc.approvals.request(task_id=ctx.task_id, summary=decision.summary, risk=decision.risk, payload={"tool": name, "args": shorten(redact_obj(args))})
            outcome = await svc.approvals.wait(aid, ctx.cancel)
            if ctx.task_id and outcome != "cancelled":
                svc.tasks.set_state(ctx.task_id, TaskState.RUNNING, message=f"Approval {outcome}")
            if outcome == "cancelled":
                return self._finish(ctx, name, args, failure("cancelled", "Task was cancelled while waiting for approval."))
            if outcome != "approved":
                return self._finish(ctx, name, args, failure("approval_denied" if outcome == "denied" else "approval_expired", f"The action was not approved ({outcome}). Nothing was changed."))
        result = await self._run(spec, args, ctx)
        return self._finish(ctx, name, args, result)

    async def _run(self, spec: ToolSpec, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        handler = asyncio.ensure_future(spec.handler(args, ctx))
        canceller = asyncio.ensure_future(ctx.cancel.wait())
        try:
            done, _ = await asyncio.wait({handler, canceller}, timeout=spec.timeout_s, return_when=asyncio.FIRST_COMPLETED)
            if handler in done:
                try:
                    return handler.result()
                except ToolError as e:
                    return failure(e.code, e.message)
                except PolicyViolation as e:
                    return failure(e.code, e.message)
                except Exception as e:  # tool bug or environment failure; never crash the agent loop
                    return failure("tool_error", f"{spec.name} failed: {type(e).__name__}: {redact(str(e))[:300]}")
            handler.cancel()
            await asyncio.gather(handler, return_exceptions=True)
            if canceller in done:
                return failure("cancelled", f"{spec.name} was cancelled.")
            return failure("timeout", f"{spec.name} did not finish within {spec.timeout_s:g}s and was stopped.")
        finally:
            canceller.cancel()

    def _finish(self, ctx: ToolContext, name: str, args: Any, result: ToolResult) -> ToolResult:
        svc = ctx.svc
        outcome = "ok" if result.ok else (result.error_code or "failed")
        svc.audit.record("agent", f"tool:{name}", outcome, task_id=ctx.task_id, details={
            "args": shorten(redact_obj(args)) if isinstance(args, dict) else str(args)[:200],
            "summary": result.summary, "verified": result.verified,
            "evidence": [e.model_dump() for e in result.evidence][:5], "error_code": result.error_code,
        })
        if ctx.task_id:
            svc.tasks.add_event(ctx.task_id, "tool_result", f"{name}: {result.summary}", {
                "tool": name, "ok": result.ok, "verified": result.verified, "error_code": result.error_code,
                "evidence": [e.model_dump() for e in result.evidence][:5],
            })
        return result
