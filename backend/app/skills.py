"""Skills = versioned, declarative workflows over registered tools. They contain NO executable code and
cannot grant permissions: required permissions are computed from the tools they call, and every step still goes
through the normal registry/policy/approval path at run time. New skills are validated in isolation (static +
schema checks, nothing executed) and must be approved by the user before they can run."""
from __future__ import annotations

import json
import re
from typing import Any

from jsonschema import Draft202012Validator

from .approvals import ApprovalManager
from .audit import AuditLog
from .db import Database, now_iso
from .events import EventBus
from .tools.base import Evidence, ToolContext, ToolResult, ToolSpec, failure, success
from .tools.registry import ToolRegistry
from .types import Risk

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{2,40}$")
PLACEHOLDER = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
FORBIDDEN_STEP_TOOLS = {"propose_skill", "run_skill", "cancel_task"}  # no recursion, no self-management
MAX_STEPS = 15
SAMPLES = {"string": "sample", "integer": 1, "number": 1.0, "boolean": True}

SKILL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["name", "description", "steps"],
    "properties": {
        "name": {"type": "string"}, "description": {"type": "string", "minLength": 5, "maxLength": 300},
        "parameters": {"type": "object", "additionalProperties": {"type": "object", "required": ["type"], "properties": {
            "type": {"enum": ["string", "integer", "number", "boolean"]}, "description": {"type": "string", "maxLength": 200}}, "additionalProperties": False}},
        "steps": {"type": "array", "minItems": 1, "maxItems": MAX_STEPS, "items": {"type": "object", "required": ["tool"], "additionalProperties": False,
                  "properties": {"tool": {"type": "string"}, "args": {"type": "object"}, "note": {"type": "string", "maxLength": 200}}}},
    },
}


def _substitute(value: Any, params: dict[str, Any]) -> Any:
    if isinstance(value, str):
        whole = PLACEHOLDER.fullmatch(value.strip())
        if whole:
            return params[whole.group(1)]  # keeps the parameter's own type
        return PLACEHOLDER.sub(lambda m: str(params[m.group(1)]), value)
    if isinstance(value, dict):
        return {k: _substitute(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, params) for v in value]
    return value


def _placeholders(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(PLACEHOLDER.findall(value))
    if isinstance(value, dict):
        return set().union(*[_placeholders(v) for v in value.values()]) if value else set()
    if isinstance(value, list):
        return set().union(*[_placeholders(v) for v in value]) if value else set()
    return set()


class SkillService:
    def __init__(self, db: Database, registry: ToolRegistry, approvals: ApprovalManager, audit: AuditLog, bus: EventBus):
        self.db, self.registry, self.approvals, self.audit, self.bus = db, registry, approvals, audit, bus

    # ---- validation ---------------------------------------------------
    def validate(self, definition: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        for e in Draft202012Validator(SKILL_SCHEMA).iter_errors(definition):
            errors.append(f"{'.'.join(map(str, e.path)) or 'skill'}: {e.message}")
        if errors:
            return {"valid": False, "errors": errors[:8], "warnings": [], "permissions": [], "risk": None, "executed_code": False}
        if not NAME_RE.match(definition["name"]):
            errors.append("name must be 3-41 chars: lowercase letters, digits, '-' or '_', starting with a letter.")
        params = definition.get("parameters", {})
        used: set[str] = set()
        perms: set[str] = set()
        risk = Risk.LOW
        order = {Risk.LOW: 0, Risk.MEDIUM: 1, Risk.HIGH: 2}
        for i, step in enumerate(definition["steps"], 1):
            spec = self.registry.get(step["tool"])
            if spec is None:
                errors.append(f"step {i}: unknown tool '{step['tool']}'."); continue
            if step["tool"] in FORBIDDEN_STEP_TOOLS or not spec.skill_allowed:
                errors.append(f"step {i}: tool '{step['tool']}' cannot be used inside a skill."); continue
            args = step.get("args", {})
            refs = _placeholders(args)
            used |= refs
            missing = refs - set(params)
            if missing:
                errors.append(f"step {i}: undeclared parameter(s) {sorted(missing)}.")
                continue
            sample = {k: SAMPLES[v["type"]] for k, v in params.items()}
            try:
                bad = self.registry.validate_args(spec, _substitute(args, sample))
            except Exception as exc:  # e.g. substitution produced something unserialisable
                bad = str(exc)
            if bad and "sample" not in bad:  # sample strings can legitimately trip format/length rules
                errors.append(f"step {i} ({step['tool']}): {bad}")
            if spec.permission:
                perms.add(spec.permission.value)
            if order[spec.risk] > order[risk]:
                risk = spec.risk
        for unused in set(params) - used:
            warnings.append(f"parameter '{unused}' is declared but never used.")
        return {"valid": not errors, "errors": errors, "warnings": warnings, "permissions": sorted(perms), "risk": risk.value, "executed_code": False,
                "note": "Computed from the tools it calls. A skill cannot grant itself permissions; each step is checked by the policy engine when it runs."}

    # ---- lifecycle ----------------------------------------------------
    def propose(self, definition: dict[str, Any], *, created_by: str, task_id: str | None = None) -> dict[str, Any]:
        report = self.validate(definition)
        name = str(definition.get("name", ""))
        if not report["valid"]:
            return {"status": "rejected", "validation": report, "name": name, "version": None, "approval_id": None}
        ver = (self.db.one("SELECT MAX(version) v FROM skills WHERE name=?", (name,)) or {}).get("v") or 0
        version = ver + 1
        self.db.execute("INSERT INTO skills(name, version, status, definition_json, validation_json, created_at, created_by) VALUES (?,?,?,?,?,?,?)",
                        (name, version, "pending_approval", json.dumps(definition), json.dumps(report), now_iso(), created_by))
        return {"status": "pending_approval", "validation": report, "name": name, "version": version, "approval_id": None}

    async def request_approval(self, name: str, version: int, task_id: str | None) -> str:
        row = self.get_version(name, version)
        assert row
        v = row["validation"]
        summary = (f"Register skill “{name}” v{version}: {row['definition']['description']} — "
                   f"{len(row['definition']['steps'])} steps, tools needing permission: {', '.join(v['permissions']) or 'none'}, risk {v['risk']}.")
        risk = Risk(v["risk"])
        return await self.approvals.request(task_id=task_id, summary=summary, risk=risk, kind="register_skill", payload={"name": name, "version": version}, wait=False)

    def apply_decision(self, name: str, version: int, approve: bool) -> bool:
        row = self.get_version(name, version)
        if not row or row["status"] != "pending_approval":
            return False
        if approve:
            self.db.execute("UPDATE skills SET status='superseded', decided_at=? WHERE name=? AND status='active'", (now_iso(), name))
        self.db.execute("UPDATE skills SET status=?, decided_at=? WHERE name=? AND version=?", ("active" if approve else "rejected", now_iso(), name, version))
        self.audit.record("user", "skill_" + ("approved" if approve else "rejected"), "ok", details={"name": name, "version": version})
        self.bus.publish("skills_changed", {"name": name})
        return True

    def rollback(self, name: str, version: int) -> bool:
        row = self.get_version(name, version)
        if not row or row["status"] not in ("superseded", "active"):
            return False
        self.db.execute("UPDATE skills SET status='superseded' WHERE name=? AND status='active'", (name,))
        self.db.execute("UPDATE skills SET status='active', decided_at=? WHERE name=? AND version=?", (now_iso(), name, version))
        self.audit.record("user", "skill_rollback", "ok", details={"name": name, "version": version})
        self.bus.publish("skills_changed", {"name": name})
        return True

    def delete(self, name: str) -> bool:
        n = self.db.execute("DELETE FROM skills WHERE name=?", (name,)).rowcount
        self.bus.publish("skills_changed", {"name": name})
        return n > 0

    # ---- queries ------------------------------------------------------
    def _row(self, r: dict[str, Any]) -> dict[str, Any]:
        r = dict(r)
        r["definition"], r["validation"] = json.loads(r.pop("definition_json")), json.loads(r.pop("validation_json"))
        return r

    def get_version(self, name: str, version: int) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM skills WHERE name=? AND version=?", (name, version))
        return self._row(r) if r else None

    def active(self, name: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM skills WHERE name=? AND status='active'", (name,))
        return self._row(r) if r else None

    def list(self) -> list[dict[str, Any]]:
        return [self._row(r) for r in self.db.query("SELECT * FROM skills ORDER BY name, version DESC")]

    # ---- execution ----------------------------------------------------
    async def run(self, name: str, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        row = self.active(name)
        if not row:
            return failure("skill_not_active", f"No approved, active skill named '{name}'.")
        if ctx.depth > 0:
            return failure("nesting_blocked", "Skills cannot run other skills.")
        d = row["definition"]
        declared = d.get("parameters", {})
        missing = [p for p in declared if p not in params]
        if missing:
            return failure("missing_parameters", f"Missing parameter(s): {missing}.")
        for k, spec in declared.items():
            expected = {"string": str, "integer": int, "number": (int, float), "boolean": bool}[spec["type"]]
            if not isinstance(params[k], expected) or (spec["type"] == "integer" and isinstance(params[k], bool)):
                return failure("invalid_parameters", f"Parameter '{k}' must be a {spec['type']}.")
        results: list[dict[str, Any]] = []
        evidence: list[Evidence] = []
        all_verified = True
        for i, step in enumerate(d["steps"], 1):
            if ctx.cancel.is_set():
                return failure("cancelled", f"Cancelled before step {i}.", {"completed_steps": results})
            res = await self.registry.execute(step["tool"], _substitute(step.get("args", {}), params), ToolContext(ctx.task_id, ctx.cancel, ctx.svc, depth=1))
            results.append({"step": i, "tool": step["tool"], "ok": res.ok, "summary": res.summary, "verified": res.verified, "error_code": res.error_code})
            evidence.extend(res.evidence[:2])
            spec = self.registry.get(step["tool"])
            if spec and spec.state_changing and not res.verified:
                all_verified = False
            if not res.ok:
                return failure(res.error_code or "step_failed", f"Skill '{name}' stopped at step {i} ({step['tool']}): {res.summary}", {"steps": results}, evidence)
        return success(f"Skill '{name}' v{row['version']} finished all {len(results)} steps.", {"steps": results}, evidence, verified=all_verified)
