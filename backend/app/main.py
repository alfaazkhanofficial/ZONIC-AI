"""Entry point: python -m app.main  (Electron main process launches this and owns its lifecycle)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import psutil
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import install_error_handlers, mount
from .config import RuntimeConfig, load_config
from .logging_setup import setup_logging
from .services import Services, build_services

log = logging.getLogger("zonic")


def parent_alive(pid: int | None) -> bool:
    return pid is None or psutil.pid_exists(pid)


async def _parent_watchdog(app: FastAPI, pid: int, interval: float = 2.0) -> None:
    while parent_alive(pid):
        await asyncio.sleep(interval)
    log.warning("parent process %s is gone; shutting down to avoid an orphaned backend", pid)
    server = getattr(app.state, "server", None)
    if server is not None:
        server.should_exit = True


def create_app(config: RuntimeConfig | None = None, services: Services | None = None, *, parent_pid: int | None = None) -> FastAPI:
    config = config or load_config()
    svc = services or build_services(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        watchdog = asyncio.create_task(_parent_watchdog(app, parent_pid)) if parent_pid else None
        log.info("ZONIC backend %s ready on %s:%s", __version__, config.host, config.port)
        yield
        if watchdog:
            watchdog.cancel()
        await svc.shutdown()
        log.info("ZONIC backend stopped cleanly")

    app = FastAPI(title="ZONIC M4 backend", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.svc = svc
    app.add_middleware(CORSMiddleware, allow_origins=list(config.allowed_origins), allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def request_id(request: Request, call_next: Any) -> Any:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    install_error_handlers(app)
    mount(app)
    return app


def run() -> None:
    ap = argparse.ArgumentParser(description="ZONIC M4 backend")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()
    cfg = load_config()
    if not cfg.api_token or len(cfg.api_token) < 16:
        print("ZONIC_API_TOKEN (>=16 chars) must be set. The desktop app generates one per launch; scripts/dev.ps1 does too.", file=sys.stderr)
        sys.exit(2)
    cfg = RuntimeConfig(**{**cfg.__dict__, **({"host": args.host} if args.host else {}), **({"port": args.port} if args.port else {})})
    if cfg.host not in ("127.0.0.1", "localhost", "::1"):
        print("Refusing to bind to a non-loopback address.", file=sys.stderr)
        sys.exit(2)
    setup_logging(cfg.log_level, cfg.log_path)
    parent = int(os.environ["ZONIC_PARENT_PID"]) if os.environ.get("ZONIC_PARENT_PID", "").isdigit() else None
    app = create_app(cfg, parent_pid=parent)
    server = uvicorn.Server(uvicorn.Config(app, host=cfg.host, port=cfg.port, log_config=None, access_log=False, timeout_graceful_shutdown=3))
    app.state.server = server
    server.run()


if __name__ == "__main__":
    run()
