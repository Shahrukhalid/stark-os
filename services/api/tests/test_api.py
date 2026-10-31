"""HTTP API integration tests (FastAPI app with lifespan, scripted model)."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from stark.main import create_app

from .conftest import ScriptedProvider, last_tool_results, n_tool_rounds, text, tool


def brain(agent, req):
    msg = req.messages[-1]["content"]
    if isinstance(msg, str) and "organise" in msg and n_tool_rounds(req) == 0:
        return [tool("fs.write", {"path": "plan.md", "content": "# plan"})]
    if n_tool_rounds(req):
        return [text("after tool: " + last_tool_results(req)[0]["content"][:100])]
    return [text(f"{agent} here")]


@pytest.fixture
def client(settings):
    providers = {"openrouter": ScriptedProvider(brain)}
    app = create_app(settings, providers)
    with TestClient(app) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c


def _poll(client, task_id, until=("completed", "failed", "cancelled"), timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        t = client.get(f"/api/tasks/{task_id}").json()["task"]
        if t["status"] in until:
            return t
        time.sleep(0.05)
    raise AssertionError(f"task stuck in {t['status']}")


def test_auth_required(settings, client):
    anon = TestClient(client.app)
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/agents").status_code == 401
    assert anon.get("/api/agents", headers={"authorization": "Bearer wrong"}).status_code == 401


def test_refuses_to_start_without_token(settings):
    settings.api_token = ""
    with pytest.raises(RuntimeError, match="STARK_API_TOKEN"):
        create_app(settings, {})


def test_agents_and_status(client):
    agents = client.get("/api/agents").json()
    assert len(agents) == 7
    jarvis = next(a for a in agents if a["id"] == "jarvis")
    assert jarvis["model_in_use"]["provider"] == "openrouter"
    assert jarvis["live"]["status"] == "idle" and jarvis["tool_details"]
    status = client.get("/api/system/status").json()
    assert status["mode"] == "assist" and status["emergency_stop"] is False
    assert status["tools"]["web.search"] == "requires_credentials"
    assert status["tools"]["social.inbox"] == "simulated"
    accounts = client.get("/api/social/accounts").json()["accounts"]
    assert {a["platform"]: a["mode"] for a in accounts}["bluesky"] == "simulation"
    assert client.get("/api/social/queue").json() == {"items": [], "paused": False}
    assert client.get("/api/social/queue?status=bogus").status_code == 400


def test_chat_addressing_and_conversation(client):
    t = client.post("/api/chat", json={"message": "Friday, run diagnostics"}).json()
    assert t["agent_id"] == "friday" and t["instruction"] == "run diagnostics"
    done = _poll(client, t["id"])
    assert done["result"] == "friday here"
    turns = client.get(f"/api/conversations/{t['conversation_id']}/turns").json()
    assert [x["role"] for x in turns] == ["user", "assistant"]
    # follow-up in the same conversation stays with the selected agent
    t2 = client.post("/api/chat", json={"message": "and memory?", "agent_id": "friday",
                                        "conversation_id": t["conversation_id"]}).json()
    assert _poll(client, t2["id"])["result"] == "friday here"


def test_approval_flow_over_http(client, workspace):
    t = client.post("/api/chat", json={"message": "please organise", "agent_id": "jarvis"}).json()
    _poll(client, t["id"], until=("waiting_approval",))
    pending = client.get("/api/approvals?status=pending").json()
    assert len(pending) == 1 and pending[0]["tool_id"] == "fs.write"
    for key in ("action", "agent_id", "target", "expected_effects", "risks", "permissions"):
        assert pending[0][key]
    r = client.post(f"/api/approvals/{pending[0]['id']}/decision", json={"decision": "approve"})
    assert r.status_code == 200
    done = _poll(client, t["id"])
    assert "Wrote" in done["result"] and (workspace / "plan.md").exists()
    assert client.post(f"/api/approvals/{pending[0]['id']}/decision", json={"decision": "approve"}).status_code == 409
    detail = client.get(f"/api/tasks/{t['id']}").json()
    assert any(a["action"] == "tool:fs.write" for a in detail["audit"])
    assert any(m["type"] == "APPROVAL_REQUIRED" for m in detail["messages"])


def test_estop_over_http(client):
    t = client.post("/api/chat", json={"message": "please organise", "agent_id": "jarvis"}).json()
    _poll(client, t["id"], until=("waiting_approval",))
    out = client.post("/api/estop").json()
    assert out["engaged"] and out["cancelled_approvals"] == 1
    assert _poll(client, t["id"])["status"] == "cancelled"
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 409
    assert client.get("/api/system/status").json()["emergency_stop"] is True
    client.post("/api/estop/reset")
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 200


def test_memory_endpoints(client):
    m = client.post("/api/memory", json={"content": "Prefers metric units"}).json()
    assert m["namespace"] == "user:preferences" and m["consent"] is True
    assert client.patch(f"/api/memory/{m['id']}", json={"content": "Prefers SI units"}).json()["content"] == "Prefers SI units"
    listing = client.get("/api/memory?namespace=user:preferences").json()
    assert listing["enabled"] and len(listing["memories"]) == 1
    export = client.get("/api/memory/export")
    assert "Prefers SI units" in export.text and "attachment" in export.headers["content-disposition"]
    assert client.post("/api/memory/settings", json={"enabled": False}).json() == {"enabled": False}
    assert client.get("/api/memory").json()["enabled"] is False
    client.post("/api/memory/settings", json={"enabled": True})
    assert client.delete(f"/api/memory/{m['id']}").json() == {"deleted": True}


def test_tools_endpoint_and_user_run(client):
    tools = client.get("/api/tools").json()
    by_id = {t["id"]: t for t in tools}
    assert "jarvis" in by_id["team.review"]["agents"] and by_id["team.review"]["agents"] == ["jarvis"]
    res = client.post("/api/tools/system.metrics/run", json={"top_n": 3, "sample_seconds": 0.2}).json()
    assert res["result"]["ok"] and res["result"]["data"]["memory"]["total_gb"] > 0
    denied = client.post("/api/tools/fs.write/run", json={"path": "x", "content": "y"}).json()
    assert not denied["result"]["ok"]


def test_mode_grants_usage_audit(client):
    assert client.post("/api/settings/mode", json={"mode": "observe"}).json() == {"mode": "observe"}
    assert client.post("/api/settings/mode", json={"mode": "godmode"}).status_code == 422
    client.post("/api/settings/mode", json={"mode": "assist"})
    bad = client.post("/api/grants", json={"agent_id": "dum_e", "tool_id": "social.publish"})
    assert bad.status_code == 400  # publishing can never get a standing grant
    g = client.post("/api/grants", json={"agent_id": "jarvis", "tool_id": "fs.move", "scope": "inbox"}).json()
    assert client.delete(f"/api/grants/{g['id']}").json() == {"deleted": True}
    t = client.post("/api/chat", json={"message": "hello", "agent_id": "u"}).json()
    _poll(client, t["id"])
    usage = client.get("/api/usage").json()
    assert any(a["key"] == "u" and a["calls"] == 1 for a in usage["by_agent"])
    audit = client.get("/api/audit").json()
    assert any(a["action"] == "mode.set" for a in audit)


def test_cancel_endpoint(client):
    t = client.post("/api/chat", json={"message": "please organise", "agent_id": "jarvis"}).json()
    _poll(client, t["id"], until=("waiting_approval",))
    assert client.post(f"/api/tasks/{t['id']}/cancel").json() == {"cancelled": True}
    assert _poll(client, t["id"])["status"] == "cancelled"
    assert client.post(f"/api/tasks/{t['id']}/cancel").status_code == 409


def test_models_endpoints_with_openrouter_pool(settings):
    from stark.providers.openrouter import OpenRouterProvider

    from .test_providers import _transport

    settings.openrouter_api_key = "sk-or-test"
    pool = OpenRouterProvider("sk-or-test", transport=_transport({}))
    with TestClient(create_app(settings, {"openrouter": pool})) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        status = c.get("/api/system/status").json()
        assert status["providers"]["openrouter"]["configured"] and status["quota"]["remaining"] == 41
        info = c.get("/api/models").json()
        assert "cohere/north-mini-code:free" in info["pool"] and info["tiers"]["fast"]
        assert all(m["id"].endswith(":free") or m["id"] in {"openrouter/free", "google/lyria-3-pro-preview"}
                   for m in info["catalog"])
        res = c.post("/api/models/ping", json={"models": ["cohere/north-mini-code:free"]}).json()
        assert res["results"][0]["ok"] and res["results"][0]["tool_calling"]
        assert "sk-or-test" not in json.dumps([status, info, res])


def test_tool_run_rejects_bad_input_cleanly(client):
    r = client.post("/api/tools/fs.read/run", json={"path": "a\u0000b"})
    assert r.status_code == 200 and r.json()["result"]["ok"] is False
    assert r.json()["task"]["status"] == "failed"  # never left stuck in "queued"
    r = client.post("/api/tools/fs.read/run", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400
    r = client.post("/api/tools/fs.read/run", json=["not", "an", "object"])
    assert r.status_code == 400


def test_data_folder_is_private(settings, client):
    import os
    import stat

    if os.name != "nt":
        assert stat.S_IMODE(settings.data_dir.stat().st_mode) == 0o700


def test_social_analytics_reports_queue_and_never_invents_engagement(client):
    from datetime import datetime, timezone

    from stark.core.db import ContentItem

    assert client.get("/api/social/analytics").json()["posts"] == []
    k = client.app.state.kernel
    with k.db.session() as s:
        s.add(ContentItem(platform="bluesky", text="hello", status="published", created_by="user", simulated=True,
                          published_at=datetime.now(timezone.utc)))
        s.add(ContentItem(platform="mastodon", text="draft", status="draft", created_by="edith"))
    data = client.get("/api/social/analytics?refresh=true").json()
    assert data["counts"] == {"bluesky": {"published": 1}, "mastodon": {"draft": 1}}
    (post,) = data["posts"]
    assert post["simulated"] and post["engagement"] is None and post["score"] is None
    assert data["measured"] == 0 and data["totals"]["likes"] == 0
