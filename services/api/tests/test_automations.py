"""Automations: validation, conditions, templates, event runs, loop guard, rate limit, schedules, inbound hooks."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from stark import automations as au
from stark import hub
from stark.core.db import Mention
from stark.main import create_app
from stark.tools.social import Social

from .conftest import make_kernel


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c


def test_clean_rejects_bad_automations():
    ok = {"name": "x", "trigger": {"type": "event", "event": "post.failed"}, "actions": [{"type": "notify"}]}
    assert au.clean(ok)["actions"][0]["text"]
    for bad, msg in [({**ok, "name": ""}, "name"), ({**ok, "trigger": {"type": "event", "event": "nope"}}, "Event"),
                     ({**ok, "trigger": {"type": "schedule", "every": "day", "time": "25:00"}}, "09:30"),
                     ({**ok, "actions": []}, "at least one"),
                     ({**ok, "actions": [{"type": "webhook", "url": "http://x"}]}, "https"),
                     ({**ok, "actions": [{"type": "publish"}]}, "Unknown"),
                     ({**ok, "conditions": [{"field": "data.x", "op": "matches", "value": "("}]}, "pattern")]:
        with pytest.raises(au.AutomationError, match=msg):
            au.clean(bad)


def test_matches_and_render():
    p = {"event": "mention.found", "data": {"category": "complaint", "likes": 80, "text": "Slow app", "author": "@a"}}
    assert au.matches({"field": "data.category", "op": "contains", "value": "praise, complaint"}, p)
    assert au.matches({"field": "data.likes", "op": "greater_than", "value": "50"}, p)
    assert not au.matches({"field": "data.likes", "op": "less_than", "value": "50"}, p)
    assert au.matches({"field": "data.missing", "op": "is_empty", "value": ""}, p)
    assert au.matches({"field": "data.text", "op": "matches", "value": "(?i)slow"}, p)
    assert au.render("{{data.author}} said {{ data.text }} {{data.nope}}", p) == "@a said Slow app "


def test_every_recipe_is_valid():
    for r in au.RECIPES:
        au.clean(au.from_recipe(r["recipe"]))
    with pytest.raises(au.AutomationError):
        au.from_recipe("missing")


async def test_event_runs_actions_and_never_loops(settings):
    k, _ = make_kernel(settings)
    social = Social(settings)
    sent: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True})
    eng = au.Engine(k, social, settings, transport=httpx.MockTransport(handler))
    a = eng.save({"name": "copy", "trigger": {"type": "event", "event": "post.drafted"},
                  "conditions": [{"field": "data.platform", "op": "equals", "value": "bluesky"}],
                  "actions": [{"type": "create_draft", "platform": "mastodon", "text": "Also: {{data.text}}"},
                              {"type": "webhook", "url": "https://hook.example/x"}]})
    d = hub.create_draft(k, social, settings, {"platform": "bluesky", "text": "Hello world"})
    ev = {"type": "content.updated", "ts": "now", "data": d}
    assert await eng.on_event(ev) == 1
    runs = eng.history(a["id"])
    assert runs[0]["ok"] and runs[0]["steps"][0]["result"].startswith("draft ")
    assert sent[0]["automation"] == "copy" and sent[0]["data"]["text"] == "Hello world"
    made = [x for x in hub_items(k) if x["created_by"] == f"automation:{a['id']}"]
    assert made and made[0]["text"] == "Also: Hello world"
    # the draft the automation made does not trigger automations again
    assert await eng.on_event({"type": "content.updated", "ts": "now", "data": made[0]}) == 0
    # a mastodon draft does not match the condition
    m = hub.create_draft(k, social, settings, {"platform": "mastodon", "text": "Other"})
    assert await eng.on_event({"type": "content.updated", "ts": "now", "data": m}) == 0


def hub_items(k):
    from sqlalchemy import select

    from stark.core.db import ContentItem, to_dict

    with k.db.session() as s:
        return [to_dict(x) for x in s.scalars(select(ContentItem)).all()]


async def test_rate_limit_and_label_mention(settings, monkeypatch):
    k, _ = make_kernel(settings)
    eng = au.Engine(k, Social(settings), settings)
    with k.db.session() as s:
        m = Mention(platform="bluesky", watch_id="w1", external_id="x1", author="@a", text="This is broken",
                    url="https://bsky.app/x")
        s.add(m)
        s.flush()
        mid = m.id
    eng.save({"name": "lab", "trigger": {"type": "event", "event": "mention.found"},
                  "actions": [{"type": "label_mention", "label": "Urgent"}]})
    ev = {"type": "listening.hit", "ts": "now", "data": {"id": mid, "platform": "bluesky", "text": "This is broken",
                                                         "category": "complaint", "watch": "stark"}}
    assert await eng.on_event(ev) == 1
    with k.db.session() as s:
        assert s.get(Mention, mid).labels == ["Urgent"]
    monkeypatch.setattr(au, "RATE_LIMIT", 1)
    assert await eng.on_event(ev) == 0
    assert eng.list()[0]["runs"] == 1


def test_schedule_due_once_per_day(settings):
    k, _ = make_kernel(settings)
    eng = au.Engine(k, Social(settings), settings)
    tz = timezone(timedelta(hours=5))
    friday = datetime(2026, 10, 30, 16, 5, tzinfo=tz)
    a = {"trigger": {"type": "schedule", "every": "week", "weekday": 4, "time": "16:00"}, "last_run_at": None}
    assert eng.due(a, friday)
    assert not eng.due(a, friday.replace(hour=15))
    assert not eng.due(a, friday + timedelta(days=1))
    assert not eng.due({**a, "last_run_at": (friday - timedelta(minutes=1)).isoformat()}, friday)
    assert eng.due({**a, "last_run_at": (friday - timedelta(days=7)).isoformat()}, friday)


def test_api_recipes_test_run_and_inbound_hook(client):
    recipes = client.get("/api/automations/recipes").json()["recipes"]
    assert any(r["recipe"] == "inbound-draft" for r in recipes)
    a = client.post("/api/automations/from-recipe", json={"recipe": "inbound-draft"}).json()
    assert a["enabled"] is False and a["hook_path"].startswith(f"/api/hooks/{a['id']}/") and "hook_key" not in a
    plan = client.post(f"/api/automations/{a['id']}/test", json={"data": {"text": "Hi from Make"}}).json()
    assert plan["would_run"] and plan["steps"][0]["text"] == "Hi from Make"
    hook = a["hook_path"]
    # disabled automations ignore their hook
    assert TestClient(client.app).post(hook, json={"text": "x"}).status_code == 404
    body = {**{x: a[x] for x in ("name", "trigger", "conditions", "actions")}, "enabled": True}
    assert client.put(f"/api/automations/{a['id']}", json=body).json()["hook_path"] == hook  # key is kept
    anon = TestClient(client.app)
    assert anon.post(hook + "x", json={"text": "x"}).status_code == 404
    assert anon.post(f"/api/hooks/{a['id']}/", json={}).status_code in (404, 405)
    r = anon.post(hook, json={"text": "Hello from Make"}).json()
    assert r["ok"] and r["steps"][0]["result"].startswith("draft ")
    assert anon.post(hook, json={"other": 1}).json()["note"] == "conditions did not match"
    assert anon.post(hook, content=b"x" * 70_000).status_code == 413
    assert anon.get("/api/automations").status_code == 401
    assert client.get("/api/automations/runs").json()["runs"][0]["ok"]
    assert client.post("/api/automations", json={"name": "bad", "trigger": {"type": "x"},
                                                 "actions": [{"type": "notify"}]}).status_code == 400
    assert client.delete(f"/api/automations/{a['id']}").status_code == 200
    assert client.get("/api/automations").json()["automations"] == []
