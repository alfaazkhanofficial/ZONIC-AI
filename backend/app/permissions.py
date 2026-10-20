"""Permission policy. The backend is authoritative: UI toggles only edit settings, this enforces them."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .redaction import redact
from .settings_service import SettingsService
from .tools.base import ToolContext, ToolSpec
from .types import PermissionGroup, Risk

GROUP_LABELS = {
    PermissionGroup.READ_WORKSPACE: "Read files in approved workspaces",
    PermissionGroup.WRITE_WORKSPACE: "Create/edit files in approved workspaces",
    PermissionGroup.LAUNCH_APPS: "Launch allowlisted applications",
    PermissionGroup.BROWSER: "Open links in your default browser",
    PermissionGroup.SCREENSHOT: "Observe the screen (screenshots, active window)",
    PermissionGroup.INPUT_CONTROL: "Control mouse and keyboard",
    PermissionGroup.ELEVATED: "Elevated / destructive actions",
}


class PolicyViolation(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class Decision:
    outcome: Literal["allow", "deny", "approval"]
    code: str = ""
    reason: str = ""
    summary: str = ""
    risk: Risk = Risk.LOW


def _norm(p: Path | str) -> str:
    return os.path.normcase(str(p))


class PermissionPolicy:
    def __init__(self, settings: SettingsService):
        self.settings = settings

    def granted(self, group: PermissionGroup) -> bool:
        return bool(self.settings.get("permissions").get(group.value, False))

    def granted_groups(self) -> list[str]:
        perms = self.settings.get("permissions")
        return [k for k, v in perms.items() if v]

    def workspaces(self) -> list[Path]:
        out = []
        for w in self.settings.get("workspaces")["items"]:
            p = Path(w["path"])
            if p.is_dir():
                out.append(p.resolve())
        return out

    def default_workspace(self) -> Path | None:
        items = self.settings.get("workspaces")["items"]
        wid = self.settings.get("personalization")["default_workspace_id"]
        for w in items:
            if w["id"] == wid and Path(w["path"]).is_dir():
                return Path(w["path"]).resolve()
        spaces = self.workspaces()
        return spaces[0] if spaces else None

    def resolve_path(self, raw: str) -> Path:
        """Resolve a user/model-supplied path and require it to live inside an approved workspace."""
        spaces = self.workspaces()
        if not spaces:
            raise PolicyViolation("no_workspace", "No approved workspace. Add one in Permissions first.")
        if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
            raise PolicyViolation("invalid_path", "Path is empty or invalid.")
        candidate = Path(raw)
        if not candidate.is_absolute():
            base = self.default_workspace() or spaces[0]
            candidate = base / candidate
        resolved = candidate.resolve()  # follows symlinks, collapses ".."
        rn = _norm(resolved)
        for ws in spaces:
            wn = _norm(ws)
            if rn == wn or rn.startswith(wn.rstrip(os.sep) + os.sep):
                return resolved
        raise PolicyViolation("outside_workspace", "That path is outside the approved workspaces.")

    def decide(self, spec: ToolSpec, args: dict[str, Any], ctx: ToolContext) -> Decision:
        if spec.permission is not None and not self.granted(spec.permission):
            label = GROUP_LABELS[spec.permission]
            return Decision("deny", "permission_not_granted", f"Permission not granted: “{label}”. Enable it in Permissions.")
        for key in spec.path_args:
            if key in args and args[key] is not None:
                try:
                    self.resolve_path(str(args[key]))
                except PolicyViolation as v:
                    return Decision("deny", v.code, v.message)
        summary = spec.describe(args) if spec.describe else f"{spec.name} {redact(json.dumps(args, default=str))[:160]}"
        if spec.approval == "always":
            return Decision("approval", summary=summary, risk=spec.risk)
        if spec.approval == "dynamic" and spec.needs_approval:
            reason = spec.needs_approval(args, ctx)
            if reason:
                return Decision("approval", summary=reason, risk=spec.risk)
        return Decision("allow", summary=summary, risk=spec.risk)
