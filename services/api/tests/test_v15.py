"""1.5: brand isolation for listening, library, automations and memory; automation retries and auto-pause."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from stark import automations as au
from stark import hub
from stark.core import db as dbm
from stark.main import create_app
from stark.tools.social import Social

from .conftest import make_kernel


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c
    dbm.ACTIVE_BRAND.update({"name": "", "blocked_terms": []})


def use(client, bid):
    client.post("/api/brands/active", json={"id": bid})


def test_listening_library_automations_and_memory_stay_in_their_brand(client):
    shared = client.post("/api/library", json={"kind": "signature", "name": "Shared", "body": "Thanks!"}).json()
    a = client.post("/api/brands", json={"name": "Acme"}).json()
    b = client.post("/api/brands", json={"name": "Beta"}).json()
    use(client, a["id"])
    client.post("/api/library", json={"kind": "hashtags", "name": "Acme tags", "body": "acme"})
    client.post("/api/listening/watches", json={"kind": "keyword", "query": "acme", "platforms": ["bluesky"]})
    client.post("/api/automations", json={"name": "Acme alert", "trigger": {"type": "event", "event": "mention.found"},
                                          "actions": [{"type": "notify", "text": "{{data.text}}"}]})
    k = client.app.state.kernel
    k.memory.save(actor=None, namespace="user:preferences", layer="preference", content="Acme voice is playful",
                  consent=True)
    use(client, b["id"])
    names = lambda path, key, f="name": [x[f] for x in client.get(path).json()[key]]  # noqa: E731
    assert names("/api/library", "snippets") == ["Shared"]  # shared items stay visible, Acme's do not
    assert names("/api/listening/watches", "watches", "query") == []
    assert names("/api/automations", "automations") == []
    assert k.memory.search(actor=None, query="Acme voice") == []
    assert k.memory.preferences_for(k.registry.get("jarvis")) == []
    use(client, a["id"])
    assert names("/api/library", "snippets") == ["Acme tags", "Shared"]
    assert names("/api/listening/watches", "watches", "query") == ["acme"]
    assert names("/api/automations", "automations") == ["Acme alert"]
    assert k.memory.search(actor=None, query="Acme voice")
    assert len(client.get("/api/library?brand=all").json()["snippets"]) == 2 and shared["brand"] == ""


@pytest.mark.asyncio
async def test_brand_automation_ignores_other_brands_events(settings):
    k, _ = make_kernel(settings)
    eng = au.Engine(k, Social(settings), settings)
    dbm.ACTIVE_BRAND.update({"name": "Acme"})
    try:
        a = eng.save({"name": "label", "trigger": {"type": "event", "event": "mention.found"},
                      "actions": [{"type": "add_utm"}]})
    finally:
        dbm.ACTIVE_BRAND.update({"name": ""})
    assert a["brand"] == "Acme"
    ev = lambda brand: {"type": "listening.hit", "ts": "t", "data": {"text": "x", "brand": brand}}  # noqa: E731
    assert await eng.on_event(ev("Beta")) == 0
    assert await eng.on_event(ev("Acme")) == 1
    assert await eng.on_event(ev("")) == 1  # shared watches still reach every automation


@pytest.mark.asyncio
async def test_retry_then_auto_pause_and_manual_retry(settings):
    k, _ = make_kernel(settings)
    calls: list[int] = []
    status = {"code": 503}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status["code"])
    events: list[tuple[str, dict]] = []
    publish = k.bus.publish
    k.bus.publish = lambda t, d: (events.append((t, d)), publish(t, d))
    eng = au.Engine(k, Social(settings), settings, transport=httpx.MockTransport(handler))
    eng.retry_delay = 0
    a = eng.save({"name": "log", "trigger": {"type": "event", "event": "post.published"},
                  "actions": [{"type": "webhook", "url": "https://hook.example/x"}]})
    payload = {"event": "post.published", "data": {"text": "hi"}}

    r = await eng.run(a, payload)
    assert not r["ok"] and r["steps"][0]["retried"] and len(calls) == 2  # one automatic retry
    status["code"] = 200
    calls.clear()
    failed_run = eng.history(a["id"])[0]
    retried = await eng.retry(failed_run["id"])  # replay the same event
    assert retried["ok"] and len(calls) == 1
    with pytest.raises(au.AutomationError):
        await eng.retry(eng.history(a["id"])[0]["id"])  # a successful run cannot be retried

    status["code"] = 400  # refused: no automatic retry, counts as a failure
    for _ in range(au.PAUSE_AFTER):
        await eng.run(eng.get(a["id"]), payload)
    row = eng.get(a["id"])
    assert row["enabled"] is False and "3 failed runs" in row["paused_reason"]
    assert [d["id"] for t, d in events if t == "automation.paused"] == [a["id"]]
    assert eng.health()["paused"][0]["id"] == a["id"]
    assert hub.webhook_payload({"type": "automation.paused", "ts": "t", "data": events[-1][1]})["event"] == \
        "automation.paused"
    # switching it back on clears the pause
    again = eng.save({**{x: row[x] for x in ("name", "trigger", "conditions", "actions")}, "enabled": True}, a["id"])
    assert again["enabled"] and again["paused_reason"] == "" and again["consecutive_failures"] == 0
