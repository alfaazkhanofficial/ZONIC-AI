"""Service container wiring everything together (also the seam tests use to inject fakes)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .agent import AgentRuntime
from .approvals import ApprovalManager
from .audit import AuditLog
from .chat import ChatStore
from .config import RuntimeConfig
from .db import Database
from .events import EventBus
from .memory import Embedder, MemoryService
from .permissions import PermissionPolicy
from .providers.base import ModelProvider
from .providers.nemotron import NemotronProvider
from .secrets_store import SecretStore
from .settings_service import SettingsService
from .skills import SkillService
from .tasks import TaskManager
from .tools.builtin import build_builtin_tools
from .tools.registry import ToolRegistry
from .tools.windows import Adapters, bind_adapters, build_windows_tools, prune_screenshots
from .voice import VoiceManager

log = logging.getLogger(__name__)


@dataclass
class Services:
    config: RuntimeConfig
    db: Database
    bus: EventBus
    audit: AuditLog
    settings: SettingsService
    secrets: SecretStore
    policy: PermissionPolicy
    approvals: ApprovalManager
    memory: MemoryService
    chat: ChatStore
    tasks: TaskManager
    registry: ToolRegistry
    skills: SkillService
    provider: ModelProvider
    adapters: Adapters
    voice: VoiceManager
    agent: AgentRuntime

    async def shutdown(self) -> None:
        await self.voice.stop_all()
        await self.tasks.shutdown()
        self.db.close()


def build_services(config: RuntimeConfig, *, provider: ModelProvider | None = None, adapters: Adapters | None = None, secrets: SecretStore | None = None,
                   embedder: Embedder | None = None, live_connector: Any = None, force_no_fts: bool = False) -> Services:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(config.db_path, force_no_fts=force_no_fts)
    bus = EventBus()
    audit = AuditLog(db, bus)
    settings = SettingsService(db)
    secrets = secrets or SecretStore(config.data_dir)
    policy = PermissionPolicy(settings)
    approvals = ApprovalManager(db, bus, audit)
    memory = MemoryService(db, settings, embedder)
    chat = ChatStore(db, settings)
    tasks = TaskManager(db, bus, audit, settings)
    registry = ToolRegistry()
    adapters = adapters or Adapters()
    bind_adapters(adapters)
    for spec in [*build_builtin_tools(), *build_windows_tools()]:
        registry.register(spec)
    skills = SkillService(db, registry, approvals, audit, bus)
    provider = provider or NemotronProvider(settings, secrets)
    svc = Services(config=config, db=db, bus=bus, audit=audit, settings=settings, secrets=secrets, policy=policy, approvals=approvals, memory=memory, chat=chat,
                   tasks=tasks, registry=registry, skills=skills, provider=provider, adapters=adapters, voice=None, agent=None)  # type: ignore[arg-type]
    svc.voice = VoiceManager(svc, connector=live_connector)
    svc.agent = AgentRuntime(svc)
    registry.svc = svc
    registry.sync_records()
    try:
        prune_screenshots(config.screenshot_dir, settings.get("privacy")["screenshot_retention_hours"])
    except Exception:
        log.warning("screenshot pruning failed", exc_info=True)
    return svc
