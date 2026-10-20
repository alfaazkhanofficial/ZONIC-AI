from __future__ import annotations

import pytest

from app.memory import MemoryDisabled, SensitiveContentError
from conftest import make_services


async def test_crud_and_provenance(env):
    m = env.svc.memory
    a = m.create("I prefer dark mode and concise answers", "preference", "user_ui", user_approved=True)
    assert a["provenance"]["trust"] == "user_approved" and a["provenance"]["source"] == "user_ui"
    m.update(a["id"], content="I prefer light mode", importance=0.9)
    assert m.get(a["id"])["content"] == "I prefer light mode"
    assert m.delete(a["id"]) and m.get(a["id"]) is None


async def test_keyword_and_semantic_search_approved_only(env):
    m = env.svc.memory
    m.create("The school ERP backend uses FastAPI and PostgreSQL", "project", "user_ui", user_approved=True)
    m.create("Favourite editor is VS Code", "preference", "user_ui", user_approved=True)
    m.create("Candidate: user likes pineapple pizza", "preference", "agent:t1", user_approved=False)
    hits = m.search("postgres database for school")
    assert hits and "PostgreSQL" in hits[0]["content"]
    assert not m.search("pineapple pizza")                      # unreviewed candidates are never recalled
    assert m.search("pineapple pizza", include_unapproved=True)  # but the review UI can see them
    assert "semantic" in m.search("postgresql")[0]["match"] or "keyword" in m.search("postgresql")[0]["match"]
    assert m.search("zzzzqqq nothing") == []


async def test_like_fallback_when_fts_unavailable(tmp_path):
    svc, *_ = make_services(tmp_path, force_no_fts=True)
    assert svc.db.fts5 is False
    svc.memory.create("Deploy script lives in tools/deploy.ps1", "procedural", "user_ui", user_approved=True)
    assert svc.memory.search("deploy script")[0]["content"].startswith("Deploy")
    assert svc.memory.status()["keyword_index"] == "like-fallback"
    await svc.shutdown()


async def test_sensitive_content_refused(env):
    for bad in ("my key is nvapi-ABCDEFGHIJKLMNOPQRSTUV", "password: hunter2hunter2", "card 4111 1111 1111 1111"):
        with pytest.raises(SensitiveContentError):
            env.svc.memory.create(bad, "knowledge", "user_ui", user_approved=True)
    assert env.svc.memory.status()["count"] == 0


async def test_category_toggle_and_master_switch(env):
    env.svc.settings.update("memory", {"workflows": False})
    with pytest.raises(MemoryDisabled):
        env.svc.memory.create("always run tests first", "procedural", "user_ui")
    env.svc.settings.update("memory", {"enabled": False})
    with pytest.raises(MemoryDisabled):
        env.svc.memory.create("anything", "knowledge", "user_ui")


async def test_persistence_across_restart(tmp_path):
    svc, *_ = make_services(tmp_path)
    svc.memory.create("Project codename is Falcon", "project", "user_ui", user_approved=True)
    await svc.shutdown()
    svc2, *_ = make_services(tmp_path)  # same data dir = app restart
    assert svc2.memory.search("falcon codename")[0]["content"] == "Project codename is Falcon"
    assert svc2.memory.clear() == 1 and svc2.memory.status()["count"] == 0
    await svc2.shutdown()
