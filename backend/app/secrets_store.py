"""Credential storage. Priority: OS credential vault (keyring) -> restricted local file (documented fallback).
Environment variables (NVIDIA_API_KEY / GEMINI_API_KEY) are read-only overrides. Values are never returned by the API."""
from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

log = logging.getLogger(__name__)
SERVICE = "ZONIC M4"
KNOWN = {"nvidia_api_key": "NVIDIA_API_KEY", "gemini_api_key": "GEMINI_API_KEY"}


class SecretStore:
    def __init__(self, data_dir: Path, use_keyring: bool = True):
        self._file = data_dir / "secrets.json"
        self._keyring = None
        if use_keyring:
            try:
                import keyring
                from keyring.backends import fail
                if not isinstance(keyring.get_keyring(), fail.Keyring):
                    self._keyring = keyring
            except Exception as exc:  # pragma: no cover - platform dependent
                log.warning("keyring unavailable (%s); using restricted file fallback", type(exc).__name__)

    @property
    def backend(self) -> str:
        return "os-keyring" if self._keyring else "restricted-file"

    def _read_file(self) -> dict[str, str]:
        try:
            return json.loads(self._file.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    def _write_file(self, data: dict[str, str]) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(json.dumps(data), encoding="utf-8")
        try:
            os.chmod(self._file, stat.S_IRUSR | stat.S_IWUSR)  # best effort; ACLs govern on Windows
        except OSError:
            pass

    def get(self, name: str) -> str | None:
        env = os.environ.get(KNOWN.get(name, ""), "")
        if env:
            return env
        if self._keyring:
            try:
                return self._keyring.get_password(SERVICE, name)
            except Exception:  # pragma: no cover
                log.warning("keyring read failed")
        return self._read_file().get(name)

    def source(self, name: str) -> str | None:
        if os.environ.get(KNOWN.get(name, "")):
            return "environment"
        if self._keyring:
            try:
                if self._keyring.get_password(SERVICE, name):
                    return "os-keyring"
            except Exception:  # pragma: no cover
                pass
        return "restricted-file" if self._read_file().get(name) else None

    def set(self, name: str, value: str) -> None:
        if name not in KNOWN:
            raise KeyError(name)
        if self._keyring:
            try:
                self._keyring.set_password(SERVICE, name, value)
                return
            except Exception:  # pragma: no cover
                log.warning("keyring write failed; falling back to restricted file")
        data = self._read_file()
        data[name] = value
        self._write_file(data)

    def delete(self, name: str) -> None:
        if self._keyring:
            try:
                self._keyring.delete_password(SERVICE, name)
            except Exception:
                pass
        data = self._read_file()
        if data.pop(name, None) is not None:
            self._write_file(data)

    def status(self) -> dict[str, dict[str, object]]:
        return {n: {"configured": self.get(n) is not None, "source": self.source(n)} for n in KNOWN}
