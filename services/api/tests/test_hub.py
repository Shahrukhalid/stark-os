"""Drafts from outside tools, CSV import, evergreen recycling, Library, webhooks and the MCP server."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from stark import hub, mcp_server
from stark.core.db import ContentItem
from stark.main import create_app
from stark.tools.social import Social

from .conftest import make_kernel


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c


def test_drafts_import_and_library_api(client):
    d = client.post("/api/social/drafts", json={"platform": "bluesky", "text": "Hello from an outside tool #launch"}).json()
    assert d["status"] == "draft" and d["check"]["verdict"] in ("pass", "warn") and d["created_by"] == "user"
    assert client.post("/api/social/drafts", json={"platform": "myspace", "text": "x"}).status_code == 400

    future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d %H:%M")
    csv = ("platform,text,scheduled_for,campaign,thread\n"
           f"bluesky,Monday tip: batch your posts #tips,{future},tips,\n"
           "mastodon,A thread about our launch,,launch,Part two || Part three\n"
           "bluesky,Old one,2020-01-01 09:00,,\n"
           "friendster,Nope,,,\n")
    out = client.post("/api/social/import", json={"csv": csv}).json()
    assert out["created"] == 3 and out["scheduled"] == 1
    assert any("line 4" in e and "past" in e for e in out["errors"]) and any("line 5" in e for e in out["errors"])
    q = {i["text"]: i for i in client.get("/api/social/queue").json()["items"]}
    assert q["Monday tip: batch your posts #tips"]["status"] == "scheduled"
    assert q["Monday tip: batch your posts #tips"]["auto_publish"] is False  # importing never approves publishing
    assert q["A thread about our launch"]["thread"] == ["Part two", "Part three"]
    assert client.post("/api/social/import", json={"csv": "foo,bar\n1,2\n"}).status_code == 400

    s = client.post("/api/library", json={"kind": "hashtags", "name": "Launch", "body": "launch, #ShipIt launch"}).json()
    assert s["body"] == "#launch #ShipIt"
    assert client.post("/api/library", json={"kind": "spell", "name": "x", "body": "y"}).status_code == 400
    assert [x["name"] for x in client.get("/api/library").json()["snippets"]] == ["Launch"]
    assert client.delete(f"/api/library/{s['id']}").json()["ok"]
    assert client.get("/api/media").json() == {"images": []}
    assert client.get("/api/webhooks").json()["count"] == 0
    assert client.post("/api/webhooks/test").status_code == 409


async def test_evergreen_posts_come_back_as_drafts_once_per_period(settings):
    k, _ = make_kernel(settings)
    social = Social(settings)
    with k.db.session() as s:
        s.add(ContentItem(id="cnt_old", platform="bluesky", text="Our evergreen guide #guide", status="published",
                          created_by="user", simulated=False, published_at=datetime.now(timezone.utc) - timedelta(days=31)))
    with pytest.raises(hub.HubError):
        hub.set_evergreen(k, "cnt_old", 3)
    assert hub.set_evergreen(k, "cnt_old", 30)["evergreen_days"] == 30
    (copy_id,) = hub.recycle_due(k, social, settings)
    assert hub.recycle_due(k, social, settings) == []  # the setting moved to the copy
    with k.db.session() as s:
        copy = s.get(ContentItem, copy_id)
        assert copy.status == "draft" and copy.recycled_from == "cnt_old" and copy.evergreen_days == 30
        assert copy.text == "Our evergreen guide #guide" and copy.created_by == "recycler"
        assert s.get(ContentItem, "cnt_old").evergreen_days is None


async def test_webhooks_send_signed_events_once_per_state(settings):
    settings.webhook_urls, settings.webhook_secret = ["https://hooks.example/abc"], "s3cret"
    k, _ = make_kernel(settings)
    got: list[httpx.Request] = []
    w = hub.Webhooks(k, settings, transport=httpx.MockTransport(lambda r: got.append(r) or httpx.Response(200)))
    ev = {"type": "content.updated", "ts": "t", "data": {"id": "cnt_1", "status": "published", "platform": "bluesky",
                                                        "text": "hi", "external_url": "https://bsky.app/x"}}
    p = w.payload_for(ev)
    assert p["event"] == "post.published" and p["data"]["external_url"] == "https://bsky.app/x"
    assert w.payload_for(ev) is None and w.payload_for({"type": "task.thought", "data": {}}) is None
    assert await w.send(p) == 1
    body = got[0].content
    assert got[0].headers["x-stark-signature"] == hub.sign("s3cret", body) and json.loads(body)["event"] == "post.published"
    assert hub.webhook_payload({"type": "listening.hit", "data": {"author": "@a", "text": "t"}})["event"] == "mention.found"


def test_mcp_server_speaks_the_protocol_and_cannot_publish(client, settings):
    def handler(req: httpx.Request) -> httpx.Response:
        r = client.request(req.method, req.url.path, params=dict(req.url.params), content=req.content,
                           headers={"content-type": "application/json"})
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": "application/json"})
    c = mcp_server.Client("http://stark", settings.api_token, transport=httpx.MockTransport(handler))
    init = mcp_server.handle(c, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["serverInfo"]["name"] == "stark-os"
    assert mcp_server.handle(c, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {t["name"] for t in mcp_server.handle(c, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert "create_draft" in names and not any("publish" in n for n in names)

    def call(name, **args):
        r = mcp_server.handle(c, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": args}})
        return json.loads(r["result"]["content"][0]["text"]) if not r["result"].get("isError") else r["result"]["content"][0]["text"]

    d = call("create_draft", platform="mastodon", text="Written by an editor plugin #hello")
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert call("schedule_draft", item_id=d["id"], when=when)["auto_publish"] is False
    assert call("list_queue", status="scheduled")[0]["id"] == d["id"]
    assert "no such post" in call("schedule_draft", item_id="nope", when=when)
    assert call("stark_status")["mode"] == "assist"
    assert mcp_server.handle(c, {"jsonrpc": "2.0", "id": 9, "method": "nope"})["error"]["code"] == -32601
