from __future__ import annotations

from enum import Enum


class PermissionGroup(str, Enum):
    READ_WORKSPACE = "read_workspace"
    WRITE_WORKSPACE = "write_workspace"
    LAUNCH_APPS = "launch_apps"
    BROWSER = "browser"
    SCREENSHOT = "screenshot"
    INPUT_CONTROL = "input_control"
    ELEVATED = "elevated"


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskState(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
_S = TaskState
TRANSITIONS: dict[TaskState, set[TaskState]] = {
    _S.QUEUED: {_S.PLANNING, _S.CANCELLED, _S.FAILED},
    _S.PLANNING: {_S.RUNNING, _S.VERIFYING, _S.COMPLETED, _S.FAILED, _S.CANCELLED, _S.WAITING_FOR_APPROVAL},
    _S.RUNNING: {_S.RUNNING, _S.WAITING_FOR_APPROVAL, _S.VERIFYING, _S.COMPLETED, _S.FAILED, _S.CANCELLED},
    _S.WAITING_FOR_APPROVAL: {_S.RUNNING, _S.FAILED, _S.CANCELLED},
    _S.VERIFYING: {_S.COMPLETED, _S.FAILED, _S.CANCELLED},
    _S.COMPLETED: set(),
    _S.FAILED: set(),
    _S.CANCELLED: set(),
}
