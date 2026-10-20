"""Tool contract: typed schema, permission, risk, timeout, verification strategy, structured result."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel

from ..types import PermissionGroup, Risk


class Evidence(BaseModel):
    type: str
    value: str
    passed: bool = True


class ToolResult(BaseModel):
    ok: bool
    summary: str
    data: dict[str, Any] | None = None
    evidence: list[Evidence] = []
    error_code: str | None = None
    needs_approval: bool = False
    verified: bool = False  # True only when an independent observation confirmed the outcome


def success(summary: str, data: dict[str, Any] | None = None, evidence: list[Evidence] | None = None, verified: bool = True) -> ToolResult:
    return ToolResult(ok=True, summary=summary, data=data, evidence=evidence or [], verified=verified and bool(evidence))


def failure(code: str, summary: str, data: dict[str, Any] | None = None, evidence: list[Evidence] | None = None) -> ToolResult:
    return ToolResult(ok=False, summary=summary, data=data, evidence=evidence or [], error_code=code)


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class ToolContext:
    task_id: str | None
    cancel: asyncio.Event
    svc: Any  # app.services.Services
    depth: int = 0  # skill nesting depth


Handler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    version: str = "1.0.0"
    permission: PermissionGroup | None = None
    risk: Risk = Risk.LOW
    side_effect: Literal["none", "read", "write", "external"] = "none"
    timeout_s: float = 30.0
    verification: str = ""
    approval: Literal["never", "always", "dynamic"] = "never"
    path_args: tuple[str, ...] = ()
    needs_approval: Callable[[dict[str, Any], ToolContext], str | None] | None = None
    describe: Callable[[dict[str, Any]], str] | None = None
    availability: Callable[[], tuple[bool, str | None]] | None = None
    model_visible: bool = True
    platforms: tuple[str, ...] | None = None  # sys.platform prefixes
    skill_allowed: bool = True

    @property
    def state_changing(self) -> bool:
        return self.side_effect in ("write", "external")
