from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

from app.logging_setup import RedactingJsonFormatter
from app.permissions import PolicyViolation
from app.redaction import contains_sensitive, redact, redact_obj
from app.secrets_store import SecretStore
from app.settings_service import ConsentRequired
from app.tools.base import ToolContext, ToolSpec, success
from app.tools.registry import ToolRegistry
from app.types import Risk
from conftest import grant


def test_redaction_masks_keys_and_numbers():
    s = "key nvapi-ABCDEFGHIJKLMNOPQRSTUV and AIzaSyA1234567890abcdefghijkl, Bearer abcdefghijklmnop, password=hunter22 card 4111 1111 1111 1111"
    out = redact(s)
    for leaked in ("nvapi-ABCDEF", "AIzaSyA123", "abcdefghijklmnop", "hunter22", "4111 1111"):
        assert leaked not in out
    assert "REDACTED" in out
    assert redact_obj({"api_key": "x", "nested": [{"token": "y"}], "ok": "fine"}) == {"api_key": "[REDACTED]", "nested": [{"token": "[REDACTED]"}], "ok": "fine"}
    assert not contains_sensitive("My dog is called Max and I like tea")
    assert contains_sensitive("ssn 123-45-6789")
    assert not contains_sensitive("order number 1234 5678 9012 3456")  # fails Luhn -> not a card


def test_log_formatter_redacts_secrets():
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "using key %s", ("nvapi-ABCDEFGHIJKLMNOPQRSTUV",), None)
    assert "nvapi-" not in RedactingJsonFormatter().format(rec)


def test_secret_store_file_fallback_and_status(tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    s = SecretStore(tmp_path, use_keyring=False)
    assert s.get("nvidia_api_key") is None and s.status()["nvidia_api_key"]["configured"] is False
    s.set("nvidia_api_key", "nvapi-test-12345678")
    assert s.get("nvidia_api_key") == "nvapi-test-12345678"
    st = s.status()["nvidia_api_key"]
    assert st == {"configured": True, "source": "restricted-file"}  # status never contains the value
    if sys.platform != "win32":
        assert (os.stat(tmp_path / "secrets.json").st_mode & 0o077) == 0
    s.delete("nvidia_api_key")
    assert s.get("nvidia_api_key") is None
    with pytest.raises(KeyError):
        s.set("other", "value-value")


def test_env_var_overrides_store(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key-12345678")
    s = SecretStore(tmp_path, use_keyring=False)
    assert s.get("gemini_api_key") == "env-key-12345678" and s.source("gemini_api_key") == "environment"


async def test_workspace_boundary(env):
    grant(env.svc, env.ws, "read_workspace")
    pol = env.svc.policy
    (env.ws / "a.txt").write_text("hi")
    assert pol.resolve_path("a.txt") == (env.ws / "a.txt").resolve()
    for bad in ("../outside.txt", str(env.ws.parent / "x.txt"), "sub/../../escape.txt"):
        with pytest.raises(PolicyViolation) as e:
            pol.resolve_path(bad)
        assert e.value.code == "outside_workspace"
    with pytest.raises(PolicyViolation):
        pol.resolve_path("")


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
async def test_symlink_escape_is_blocked(env, tmp_path):
    grant(env.svc, env.ws, "read_workspace")
    outside = tmp_path / "secret_dir"
    outside.mkdir()
    (outside / "s.txt").write_text("secret")
    (env.ws / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PolicyViolation):
        env.svc.policy.resolve_path("link/s.txt")


async def test_no_workspace_means_no_paths(env):
    with pytest.raises(PolicyViolation) as e:
        env.svc.policy.resolve_path("a.txt")
    assert e.value.code == "no_workspace"


async def test_permission_changes_need_consent(env):
    with pytest.raises(ConsentRequired):
        env.svc.settings.update("permissions", {"write_workspace": True})
    assert env.svc.settings.get("permissions")["write_workspace"] is False
    env.svc.settings.update("permissions", {"write_workspace": True}, confirmed=True)
    env.svc.settings.update("permissions", {"write_workspace": False})  # narrowing never needs consent
    assert env.svc.settings.get("permissions")["write_workspace"] is False


async def test_workspace_root_and_relative_paths_rejected(env):
    with pytest.raises(Exception):
        env.svc.settings.update("workspaces", {"items": [{"name": "root", "path": os.path.abspath(os.sep)}]}, confirmed=True)
    with pytest.raises(Exception):
        env.svc.settings.update("workspaces", {"items": [{"name": "rel", "path": "relative/dir"}]}, confirmed=True)


async def test_denied_without_permission_and_audited(env):
    from app.tools.base import ToolContext
    import asyncio
    grant(env.svc, env.ws, "read_workspace")  # no write permission
    res = await env.svc.registry.execute("write_approved_file", {"path": "a.txt", "content": "x"}, ToolContext(None, asyncio.Event(), env.svc))
    assert not res.ok and res.error_code == "permission_not_granted"
    assert not (env.ws / "a.txt").exists()
    assert any(a["action"] == "tool:write_approved_file" and a["outcome"] == "permission_not_granted" for a in env.svc.audit.recent())


def test_registry_rejects_unsafe_registrations():
    async def h(a, c):
        return success("x")
    reg = ToolRegistry()
    with pytest.raises(ValueError):
        reg.register(ToolSpec("danger", "d", {"type": "object"}, h, risk=Risk.HIGH, approval="never", side_effect="write", verification="v"))
    with pytest.raises(ValueError):
        reg.register(ToolSpec("writer", "d", {"type": "object"}, h, side_effect="write"))  # state change without verification strategy
    with pytest.raises(ValueError):
        reg.register(ToolSpec("Bad-Name", "d", {"type": "object"}, h))


async def test_input_tools_gated_and_need_approval(env):
    import asyncio
    ctx = ToolContext(None, asyncio.Event(), env.svc)
    r = await env.svc.registry.execute("mouse_action", {"action": "click", "x": 5, "y": 5}, ctx)
    assert r.error_code == "permission_not_granted" and env.inp.actions == []
    env.svc.settings.update("permissions", {"input_control": True}, confirmed=True)
    from app.tools.base import ToolContext as TC
    decision = env.svc.policy.decide(env.svc.registry.get("mouse_action"), {"action": "click", "x": 5, "y": 5}, TC(None, asyncio.Event(), env.svc))
    assert decision.outcome == "approval"


def test_session_token_in_urls_is_redacted_from_logs():
    rec = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, '%s "WebSocket /api/voice/ws?token=%s" [accepted]', ("1.2.3.4", "e2e-token-0123456789abcdef"), None)
    out = RedactingJsonFormatter().format(rec)
    assert "e2e-token-0123456789abcdef" not in out and "REDACTED" in out
