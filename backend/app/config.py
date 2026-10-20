"""Runtime configuration (process-level). User-editable settings live in the DB."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "ZONIC M4"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NEMOTRON_MODEL = "nvidia/nemotron-3-super-120b-a12b"
# Verified against ai.google.dev Live API quickstart; configurable because preview IDs change.
DEFAULT_GEMINI_LIVE_MODEL = "gemini-3.1-flash-live-preview"

DEV_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173", "null")  # "null" = file:// renderer


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "zonic-m4"


@dataclass(frozen=True)
class RuntimeConfig:
    data_dir: Path
    api_token: str
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"
    allowed_origins: tuple[str, ...] = DEV_ORIGINS

    @property
    def db_path(self) -> Path:
        return self.data_dir / "zonic.db"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "logs" / "backend.log"

    @property
    def screenshot_dir(self) -> Path:
        return self.data_dir / "screenshots"


def load_config(env: dict[str, str] | None = None) -> RuntimeConfig:
    e = env if env is not None else os.environ
    data_dir = Path(e.get("ZONIC_DATA_DIR") or default_data_dir())
    token = e.get("ZONIC_API_TOKEN", "")
    origins = tuple(o.strip() for o in e.get("ZONIC_ALLOWED_ORIGINS", "").split(",") if o.strip()) or DEV_ORIGINS
    return RuntimeConfig(
        data_dir=data_dir,
        api_token=token,
        host=e.get("ZONIC_HOST", "127.0.0.1"),
        port=int(e.get("ZONIC_PORT", "8765")),
        log_level=e.get("ZONIC_LOG_LEVEL", "INFO").upper(),
        allowed_origins=origins,
    )
