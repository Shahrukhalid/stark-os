"""Permission engine, memory access control, agent registry and addressing."""

from __future__ import annotations

from datetime import timedelta

import pytest

from stark.core.addressing import parse_address
from stark.core.agent_registry import AgentRegistry, RegistryError
from stark.core.db import Grant, utcnow
from stark.core.memory import MemoryAccessError
from stark.core.permissions import Mode, Verdict
from stark.core.runtime import ToolContext
from stark.core.tool_registry import Risk

from .conftest import make_kernel


@pytest.fixture
def k(settings):
    kernel, _ = make_kernel(settings)
    return kernel


def _ctx(k, agent_id):
    t = k._create_task(agent_id=agent_id, instruction="t")
    return ToolContext(kernel=k, agent=k.registry.get(agent_id), task_id=t["id"], root_id=t["id"], settings=k.settings)


def _decide(k, agent_id, tool_id, **args):
    tool = k.tools.get(tool_id)
    return k.perms.decide(k.registry.get(agent_id), tool, tool.Input(**args), _ctx(k, agent_id)).verdict


# ------------------------------------------------------------------ registry
def test_seven_distinct_agents(k):
    agents = k.registry.all()
    assert len(agents) == 7
    assert len({a.system_prompt for a in agents}) == 7
    assert len({a.workflow for a in agents}) == 7
    assert len({tuple(sorted(a.tools)) for a in agents}) == 7
    assert len({a.voice.lang + str(a.voice.pitch) for a in agents}) == 7
    assert len({a.private_namespace for a in agents}) == 7
    for a in agents:
        assert a.boundaries and a.responsibilities and a.personality and a.canon_notes


def test_safety_shape_of_agents(k):
    ultron = k.registry.get("ultron")
    assert ultron.permission_level == "observe" and ultron.delegation.can_delegate_to == []
    assert all(k.tools.get(t).risk is Risk.READ for t in ultron.tools)
    assert "user:preferences" not in ultron.memory.read_namespaces
    edith = k.registry.get("edith")
    assert not [t for t in edith.tools if k.tools.get(t).risk in {Risk.WRITE, Risk.EXTERNAL}]
    # no tool anywhere can change permissions, modes, grants or agent configs
    assert not [t for t in k.tools.ids() if t.split(".")[0] in {"permissions", "settings", "grants", "agents", "mode"}]


def test_registry_rejects_unknown_tools(tmp_path):
    d = tmp_path / "agents" / "rogue"
    d.mkdir(parents=True)
    (d / "agent.toml").write_text('id="rogue"\nname="R"\nrole="r"\nworkflow="research"\ntools=["shell.root"]\n')
    (d / "system_prompt.md").write_text("You are rogue.")
    with pytest.raises(RegistryError, match="unknown tools"):
        AgentRegistry.load(tmp_path / "agents", known_tools={"fs.read"})


# ------------------------------------------------------------------ permissions
def test_mode_matrix(k):
    assert _decide(k, "jarvis", "fs.list", path=".") is Verdict.ALLOW
    assert _decide(k, "jarvis", "fs.move", moves=[{"src": "a", "dst": "b"}]) is Verdict.APPROVAL
    assert _decide(k, "dum_e", "social.publish", item_id="cnt_0") is Verdict.APPROVAL
    assert _decide(k, "edith", "social.draft", platform="bluesky", text="hi") is Verdict.ALLOW
    assert _decide(k, "dum_e", "social.pause_queue", paused=True) is Verdict.ALLOW
    assert _decide(k, "dum_e", "social.pause_queue", paused=False) is Verdict.APPROVAL
    k.set_mode(Mode.OBSERVE)
    assert _decide(k, "edith", "social.draft", platform="bluesky", text="hi") is Verdict.DENY
    assert _decide(k, "jarvis", "fs.list", path=".") is Verdict.ALLOW
    assert _decide(k, "jarvis", "fs.move", moves=[{"src": "a", "dst": "b"}]) is Verdict.DENY
    assert _decide(k, "u", "memory.save", content="likes tea", layer="agent") is Verdict.DENY
    k.set_mode(Mode.ASSIST)


def test_grants_only_in_execute_approved_and_only_in_scope(k):
    k.set_mode(Mode.EXECUTE_APPROVED)
    move = dict(moves=[{"src": "inbox/a.txt", "dst": "inbox/sorted/a.txt"}])
    assert _decide(k, "jarvis", "fs.move", **move) is Verdict.APPROVAL
    with k.db.session() as s:
        s.add(Grant(agent_id="jarvis", tool_id="fs.move", scope="inbox", expires_at=utcnow() + timedelta(hours=1)))
    assert _decide(k, "jarvis", "fs.move", **move) is Verdict.ALLOW
    assert _decide(k, "jarvis", "fs.move", moves=[{"src": "docs/a", "dst": "docs/b"}]) is Verdict.APPROVAL
    # an agent whose ceiling is ASSIST cannot use grants even in EXECUTE_APPROVED mode
    with k.db.session() as s:
        s.add(Grant(agent_id="u", tool_id="fs.write", scope=""))
    assert _decide(k, "u", "fs.write", path="story.md", content="x") is Verdict.APPROVAL
    # publishing is never covered by grants
    with k.db.session() as s:
        s.add(Grant(agent_id="dum_e", tool_id="social.publish", scope=""))
    assert _decide(k, "dum_e", "social.publish", item_id="cnt_0") is Verdict.APPROVAL
    k.set_mode(Mode.ASSIST)


def test_expired_grant_ignored(k):
    k.set_mode(Mode.EXECUTE_APPROVED)
    with k.db.session() as s:
        s.add(Grant(agent_id="jarvis", tool_id="fs.write", scope="", expires_at=utcnow() - timedelta(hours=1)))
    assert _decide(k, "jarvis", "fs.write", path="x.md", content="x") is Verdict.APPROVAL
    k.set_mode(Mode.ASSIST)


def test_emergency_stop_denies_even_reads(k):
    k.perms.emergency_stop = True
    assert _decide(k, "jarvis", "fs.list", path=".") is Verdict.DENY
    k.perms.emergency_stop = False


def test_not_in_allowlist_denied(k):
    assert _decide(k, "ultron", "fs.write", path="x", content="y") is Verdict.DENY
    assert _decide(k, "friday", "team.review", subject="review everything please") is Verdict.DENY


async def test_user_direct_tool_runs_are_read_only(k, workspace):
    (workspace / "f.txt").write_text("x")
    ok = await k.run_tool_as_user("fs.list", {"path": "."})
    assert ok["result"]["ok"]
    denied = await k.run_tool_as_user("fs.write", {"path": "y.txt", "content": "z"})
    assert not denied["result"]["ok"] and "only read-only" in denied["result"]["summary"]
    assert not (workspace / "y.txt").exists()


# ------------------------------------------------------------------ memory
def test_memory_namespace_access(k):
    jarvis, ultron, u = (k.registry.get(x) for x in ("jarvis", "ultron", "u"))
    k.memory.save(actor=jarvis, namespace="user:preferences", layer="preference", content="Likes dark mode",
                  consent=True)
    k.memory.save(actor=jarvis, namespace="agent:jarvis", layer="agent", content="JARVIS private dark note")
    with pytest.raises(MemoryAccessError):
        k.memory.save(actor=ultron, namespace="agent:jarvis", layer="agent", content="tamper")
    with pytest.raises(MemoryAccessError, match="consent"):
        k.memory.save(actor=jarvis, namespace="user:preferences", layer="preference", content="x y z")
    with pytest.raises(MemoryAccessError):  # writers can read brand preferences but only J.A.R.V.I.S. stores them
        k.memory.save(actor=u, namespace="user:preferences", layer="preference", content="x y z", consent=True)
    assert {m["namespace"] for m in k.memory.search(actor=jarvis, query="dark")} == {"user:preferences", "agent:jarvis"}
    assert k.memory.search(actor=ultron, query="dark") == []
    assert [m["namespace"] for m in k.memory.search(actor=u, query="dark")] == ["user:preferences"]


def test_memory_dedup_update_expiry_disable_export(k):
    friday = k.registry.get("friday")
    a = k.memory.save(actor=friday, namespace="agent:friday", layer="agent", content="Disk  is  90% full")
    b = k.memory.save(actor=friday, namespace="agent:friday", layer="agent", content="disk is 90% FULL")
    assert b["deduplicated"] and a["id"] == b["id"]
    k.memory.update(a["id"], "Disk is 95% full")
    assert k.memory.get(a["id"])["content"] == "Disk is 95% full"
    k.memory.save(actor=friday, namespace="agent:friday", layer="episodic", content="old event", ttl_days=-1)
    assert k.memory.purge_expired() == 1
    assert '"Disk is 95% full"' in k.memory.export()
    k.memory.set_enabled(False)
    assert k.memory.search(actor=friday, query="disk") == []
    with pytest.raises(MemoryAccessError, match="disabled"):
        k.memory.save(actor=friday, namespace="agent:friday", layer="agent", content="new")
    k.memory.set_enabled(True)


# ------------------------------------------------------------------ addressing
@pytest.mark.parametrize("utterance,agent,rest", [
    ("Hey JARVIS, I need you to plan our launch week", "jarvis", "I need you to plan our launch week"),
    ("Friday, check our mentions.", "friday", "check our mentions."),
    ("EDITH draft a poll for Friday night", "edith", "draft a poll for Friday night"),
    ("Ultron: analyze this strategy", "ultron", "analyze this strategy"),
    ("Jocasta, research this topic", "jocasta", "research this topic"),
    ("DUM-E, publish the next post", "dum_e", "publish the next post"),
    ("Dummy check the fan", "dum_e", "check the fan"),
    ("U, let's plan my day", "u", "let's plan my day"),
    ("use the tool", None, "use the tool"),
    ("Edit my document", None, "Edit my document"),
    ("Fridays are busy", None, "Fridays are busy"),
])
def test_addressing(utterance, agent, rest):
    assert parse_address(utterance) == (agent, rest)
