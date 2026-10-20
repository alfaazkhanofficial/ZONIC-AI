"""User-editable, non-secret settings persisted in SQLite, validated by pydantic models."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .config import DEFAULT_GEMINI_LIVE_MODEL, DEFAULT_NEMOTRON_MODEL, DEFAULT_NVIDIA_BASE_URL
from .db import Database, new_id, now_iso


class OnboardingCfg(BaseModel):
    step: int = Field(1, ge=1, le=10)
    completed: bool = False
    completed_at: str | None = None
    skipped: list[str] = []


class InteractionCfg(BaseModel):
    mode: Literal["voice_and_text", "text_first", "voice_first"] = "voice_and_text"
    reduced_motion: Literal["system", "on", "off"] = "system"
    startup_launch: bool = False
    animation_intensity: float = Field(1.0, ge=0.0, le=1.0)


class NemotronCfg(BaseModel):
    base_url: str = DEFAULT_NVIDIA_BASE_URL
    model: str = DEFAULT_NEMOTRON_MODEL
    timeout_s: float = Field(60, ge=5, le=300)
    streaming: bool = True
    temperature: float | None = Field(None, ge=0, le=2)

    @field_validator("base_url")
    @classmethod
    def _https(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not (v.startswith("https://") or v.startswith("http://localhost") or v.startswith("http://127.0.0.1")):
            raise ValueError("base_url must be https:// (http only for localhost)")
        return v


class GeminiCfg(BaseModel):
    model: str = DEFAULT_GEMINI_LIVE_MODEL
    voice_name: str = ""
    input_device_id: str = ""
    output_device_id: str = ""


class MemoryCfg(BaseModel):
    enabled: bool = True
    preferences: bool = True
    projects: bool = True
    workflows: bool = True
    conversation_history: bool = True
    semantic_index: bool = True


class PermissionsCfg(BaseModel):
    read_workspace: bool = False
    write_workspace: bool = False
    launch_apps: bool = False
    browser: bool = False
    screenshot: bool = False
    input_control: bool = False
    elevated: bool = False


class LimitsCfg(BaseModel):
    max_steps: int = Field(12, ge=1, le=40)
    task_timeout_s: int = Field(300, ge=30, le=1800)
    max_concurrent_tasks: int = Field(2, ge=1, le=4)


class PersonalizationCfg(BaseModel):
    address_as: str = Field("", max_length=60)
    response_style: Literal["concise", "balanced", "detailed"] = "concise"
    language: str = Field("en", max_length=20)
    voice_behavior: str = Field("", max_length=200)
    default_workspace_id: str = ""


class PrivacyCfg(BaseModel):
    screenshot_retention_hours: int = Field(24, ge=1, le=720)


class Workspace(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ws_"))
    name: str = Field(max_length=80)
    path: str

    @field_validator("path")
    @classmethod
    def _dir(cls, v: str) -> str:
        p = Path(v)
        if not p.is_absolute():
            raise ValueError("workspace path must be absolute")
        if not p.is_dir():
            raise ValueError("workspace path must be an existing directory")
        if p.parent == p:
            raise ValueError("a drive/filesystem root cannot be a workspace")
        return str(p.resolve())


class WorkspacesCfg(BaseModel):
    items: list[Workspace] = []


class AppEntry(BaseModel):
    exe: str
    args: list[str] = []  # fixed by the user in settings; the model can never supply arguments
    process_names: list[str] = []
    label: str = ""


class AppAllowlistCfg(BaseModel):
    items: dict[str, AppEntry] = {}

    @field_validator("items")
    @classmethod
    def _valid(cls, v: dict[str, AppEntry]) -> dict[str, AppEntry]:
        for key, entry in v.items():
            if not key.replace("_", "").replace("-", "").isalnum():
                raise ValueError(f"invalid app key {key!r}")
            if os.path.isabs(entry.exe) and not Path(entry.exe).is_file():
                raise ValueError(f"{entry.exe} does not exist")
            if not os.path.isabs(entry.exe) and ("/" in entry.exe or "\\" in entry.exe):
                raise ValueError("exe must be an absolute path or a bare system executable name")
        return v


class DiscoveryCfg(BaseModel):
    result: dict[str, Any] | None = None
    ran_at: str | None = None


def default_app_allowlist() -> dict[str, dict[str, Any]]:
    if sys.platform != "win32":
        return {}
    return {
        "notepad": {"exe": "notepad.exe", "process_names": ["notepad.exe"], "label": "Notepad"},
        "calculator": {"exe": "calc.exe", "process_names": ["calculatorapp.exe", "calc.exe", "calculator.exe"], "label": "Calculator"},
        "paint": {"exe": "mspaint.exe", "process_names": ["mspaint.exe"], "label": "Paint"},
    }


GROUPS: dict[str, type[BaseModel]] = {
    "onboarding": OnboardingCfg,
    "interaction": InteractionCfg,
    "nemotron": NemotronCfg,
    "gemini": GeminiCfg,
    "memory": MemoryCfg,
    "permissions": PermissionsCfg,
    "limits": LimitsCfg,
    "personalization": PersonalizationCfg,
    "privacy": PrivacyCfg,
    "workspaces": WorkspacesCfg,
    "app_allowlist": AppAllowlistCfg,
    "discovery": DiscoveryCfg,
}
# Changes to these groups can widen what the agent may touch and need explicit confirmation.
CONSENT_GROUPS = {"permissions", "workspaces", "app_allowlist"}


class ConsentRequired(Exception):
    pass


class SettingsService:
    def __init__(self, db: Database):
        self.db = db
        if self.db.get_setting("app_allowlist") is None:
            self.db.set_setting("app_allowlist", {"items": default_app_allowlist()})

    def get(self, group: str) -> dict[str, Any]:
        model = GROUPS[group]
        raw = self.db.get_setting(group, {})
        return model.model_validate(raw).model_dump()

    def model(self, group: str) -> Any:
        return GROUPS[group].model_validate(self.db.get_setting(group, {}))

    def all(self) -> dict[str, dict[str, Any]]:
        return {g: self.get(g) for g in GROUPS}

    def update(self, group: str, patch: dict[str, Any], *, confirmed: bool = False) -> dict[str, Any]:
        if group not in GROUPS:
            raise KeyError(group)
        current = self.get(group)
        merged = {**current, **patch}
        new = GROUPS[group].model_validate(merged).model_dump()  # raises ValidationError on bad input
        if group in CONSENT_GROUPS and new != current and not self._only_narrowing(group, current, new) and not confirmed:
            raise ConsentRequired(f"Changing '{group}' expands what ZONIC can access and needs explicit confirmation.")
        self.db.set_setting(group, new)
        return new

    @staticmethod
    def _only_narrowing(group: str, old: dict[str, Any], new: dict[str, Any]) -> bool:
        if group == "permissions":
            return not any(new[k] and not old.get(k) for k in new)
        if group == "workspaces":
            return {w["path"] for w in new["items"]} <= {w["path"] for w in old["items"]}
        if group == "app_allowlist":
            return set(new["items"]) <= set(old["items"]) and all(new["items"][k] == old["items"][k] for k in new["items"])
        return False

    def mark_onboarding_complete(self) -> dict[str, Any]:
        return self.update("onboarding", {"completed": True, "completed_at": now_iso(), "step": 10})
