"""Posting plan, item options, Bluesky threadgates and starter packs, follower history, fans, trends, outliers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from stark import insights
from stark.core.db import AccountStat, ContentItem, Mention, Watch
from stark.main import create_app
from stark.tools.social import BlueskyAdapter, Social

from .conftest import make_kernel


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c


def test_posting_plan_and_item_options(client):
    plan = client.get("/api/plan").json()
    assert [c["name"] for c in plan["categories"]] == ["Tips", "News", "Promo"] and len(plan["slots"]) == 5
    new = client.put("/api/plan", json={"categories": [{"name": "Tips", "share": 60}, {"name": "tips", "share": 10},
                                                       {"name": "Behind the scenes", "share": 40}],
                                        "slots": [{"weekday": 2, "time": "18:30"}, {"weekday": 0, "time": "09:00"},
                                                  {"weekday": 0, "time": "09:00"}]}).json()
    assert [c["name"] for c in new["categories"]] == ["Tips", "Behind the scenes"]
    assert new["slots"] == [{"weekday": 0, "time": "09:00"}, {"weekday": 2, "time": "18:30"}]
    assert client.put("/api/plan", json={"slots": [{"weekday": 9, "time": "25:00"}]}).status_code == 400

    d = client.post("/api/social/drafts", json={"platform": "bluesky", "text": "Tip: batch your posts #tips",
                                                "category": "Tips", "reply_control": "followers"}).json()
    assert d["category"] == "Tips" and d["reply_control"] == "followers"
    assert client.post("/api/social/drafts", json={"platform": "mastodon", "text": "x", "reply_control": "nobody"}).status_code == 400
    o = client.post(f"/api/social/items/{d['id']}/options", json={"reply_control": "everyone", "category": "News"}).json()
    assert o["reply_control"] is None and o["category"] == "News"
    assert client.post(f"/api/social/items/{d['id']}/options", json={"reply_control": "aliens"}).status_code == 400
    assert client.get("/api/growth").json()["streak"] == 0
    assert client.get("/api/growth/trends").json() == {"hashtags": [], "outliers": []}


def _bsky(settings, handler):
    settings.bluesky_handle, settings.bluesky_app_password = "me.bsky.social", "abcd-efgh-ijkl-mnop"
    s = Social(settings, transport=httpx.MockTransport(handler))
    return s


def _session(req):
    if req.url.path.endswith("createSession"):
        return httpx.Response(200, json={"accessJwt": "j", "did": "did:plc:me"})
    return None


async def test_bluesky_post_gets_a_threadgate_and_starter_pack_is_created(settings):
    seen: list[tuple[str, dict]] = []

    def handler(req):
        if (r := _session(req)) is not None:
            return r
        body = json.loads(req.content) if req.content else {}
        seen.append((req.url.path.rsplit(".", 1)[-1], body))
        if req.url.path.endswith("getRecord"):
            return httpx.Response(400)
        if req.url.path.endswith("getProfiles"):
            return httpx.Response(200, json={"profiles": [{"handle": "a.bsky.social", "did": "did:plc:a"}]})
        n = len(seen)
        return httpx.Response(200, json={"uri": f"at://did:plc:me/coll/rk{n}", "cid": f"c{n}"})
    social = _bsky(settings, handler)
    adapter = social.adapter("bluesky")
    assert isinstance(adapter, BlueskyAdapter)
    item = {"id": "cnt_1", "created_at": "2026-10-31T00:00:00+00:00", "text": "Hello", "thread": [], "media": [],
            "reply_control": "mentioned"}
    await adapter.publish(item, lambda n, ref: None)
    gate = [b for p, b in seen if p == "putRecord"][0]
    assert gate["collection"] == "app.bsky.feed.threadgate" and gate["record"]["allow"][0]["$type"].endswith("mentionRule")

    seen.clear()
    out = await insights.create_starter_pack(social, "Open-source AI", "People I learn from", ["@A.bsky.social", "ghost.bsky.social"])
    kinds = [b["collection"] for p, b in seen if p == "createRecord"]
    assert kinds == ["app.bsky.graph.list", "app.bsky.graph.listitem", "app.bsky.graph.starterpack"]
    assert out["added"] == 1 and out["not_found"] == ["ghost.bsky.social"]
    assert out["url"].startswith("https://bsky.app/starter-pack/me.bsky.social/")
    with pytest.raises(insights.InsightError):
        await insights.create_starter_pack(social, " ", "", ["a"])


async def test_snapshot_growth_report_fans_trends_and_outliers(settings):
    def handler(req):
        if (r := _session(req)) is not None:
            return r
        if req.url.path.endswith("getProfile"):
            return httpx.Response(200, json={"followersCount": 120, "followsCount": 40, "postsCount": 300})
        if req.url.path.endswith("listNotifications"):
            n = [{"reason": "like", "author": {"handle": "fan.bsky.social"}}] * 3 + \
                [{"reason": "reply", "author": {"handle": "fan.bsky.social"}}, {"reason": "follow", "author": {"handle": "new.bsky.social"}}]
            return httpx.Response(200, json={"notifications": n})
        return httpx.Response(404)
    social = _bsky(settings, handler)
    k, _ = make_kernel(settings)
    now = datetime.now(timezone.utc)
    with k.db.session() as s:
        s.add(AccountStat(platform="bluesky", day=(now - timedelta(days=10)).date().isoformat(), followers=100))
        for i in range(3):
            s.add(ContentItem(platform="bluesky", text=f"p{i}", status="published", created_by="user",
                              published_at=now - timedelta(days=i)))
    assert await insights.snapshot(k, social) == 1
    assert await insights.snapshot(k, social) == 1  # same day: updated, not duplicated
    rep = insights.growth_report(k)
    assert rep["summary"]["bluesky"]["followers"] == 120 and rep["summary"]["bluesky"]["change_total"] == 20
    assert len(rep["series"]["bluesky"]) == 2 and rep["streak"] == 3 and rep["active_days_30"] == 3
    fans = await insights.top_fans(social)
    assert fans["fans"][0] == {"platform": "bluesky", "account": "@fan.bsky.social", "score": 6, "kinds": {"like": 3, "reply": 1}}

    with k.db.session() as s:
        s.add(Watch(id="w1", kind="account", query="rival.bsky.social", platforms=["bluesky"]))
        s.add(Watch(id="w2", kind="keyword", query="ai", platforms=["bluesky"]))
        for i, likes in enumerate([2, 3, 2, 40]):
            s.add(Mention(watch_id="w1", platform="bluesky", external_id=f"r{i}", text=f"post {i}", likes=likes))
        for i in range(3):
            s.add(Mention(watch_id="w2", platform="bluesky", external_id=f"k{i}", text="new #OpenSource tool #ai",
                          posted_at=now - timedelta(days=1)))
        s.add(Mention(watch_id="w2", platform="bluesky", external_id="old", text="#ai", posted_at=now - timedelta(days=10)))
    (o,) = insights.outliers(k)
    assert o["score"] == 40 and o["times_average"] > 3
    tags = {t["tag"]: t for t in insights.rising_hashtags(k)}
    assert tags["opensource"]["count"] == 3 and tags["ai"]["before"] == 1
