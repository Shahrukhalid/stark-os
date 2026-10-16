"""Runs a core workflow against PostgreSQL when TEST_DATABASE_URL is set (skipped otherwise)."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text as sql

from stark.core.db import Database

from .conftest import last_tool_results, make_kernel, n_tool_rounds, text, tool

PG = os.environ.get("TEST_DATABASE_URL")
pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not PG, reason="TEST_DATABASE_URL not set")]


async def test_delegation_and_memory_on_postgres(settings):
    db = Database(PG)
    with db.engine.begin() as conn:  # clean slate
        conn.execute(sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    settings.database_url = PG

    def brain(agent, req):
        if agent == "jarvis" and n_tool_rounds(req) == 0:
            return [tool("agent.delegate", {"agent_id": "edith", "instruction": "Audit the workspace."})]
        if agent == "jarvis":
            return [text("EDITH says: " + last_tool_results(req)[0]["content"][:200])]
        return [text("No issues found.")]

    k, _ = make_kernel(settings, brain)
    done = await k.wait(k.submit_chat("jarvis", "security check")["id"], 10)
    assert done["status"] == "completed" and "No issues found" in done["result"]
    assert k.memory.list(layer="episodic")
    assert k.messages.for_root(done["id"])


async def test_social_queue_on_postgres(settings):
    from datetime import datetime, timedelta, timezone

    from stark.core.runtime import ToolContext
    from stark.tools import social

    db = Database(PG)
    with db.engine.begin() as conn:
        conn.execute(sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    settings.database_url = PG
    k, _ = make_kernel(settings)

    def ctx(agent):
        t = k._create_task(agent_id=agent, instruction="t")
        return ToolContext(kernel=k, agent=k.registry.get(agent), task_id=t["id"], root_id=t["id"], settings=settings)

    draft = k.tools.get("social.draft")
    res = await draft.run(draft.Input(platform="bluesky", text="Hello from Postgres #test",
                                      media=[{"description": "logo", "alt_text": "STARK logo"}]), ctx("edith"))
    sch = k.tools.get("social.schedule")
    when = datetime.now(timezone(timedelta(hours=-7))) + timedelta(hours=3)
    s = await sch.run(sch.Input(item_id=res.data["id"], when=when), ctx("dum_e"))
    assert abs((datetime.fromisoformat(s.data["scheduled_for"]) - when).total_seconds()) < 1
    pub = k.tools.get("social.publish")
    out = await pub.run(pub.Input(item_id=res.data["id"]), ctx("dum_e"))
    assert out.ok and out.simulated
    q = social.list_queue(k, "published")
    assert q[0]["media"][0]["alt_text"] == "STARK logo" and q[0]["check"]["verdict"] == "pass"
