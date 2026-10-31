"""Listening, phone notifications (Telegram buttons) and free AI images."""

from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from stark import growth
from stark.core.db import Approval, ContentItem, to_dict
from stark.tools.social import Social, fingerprint

from .conftest import make_kernel
from .test_social import _draft

BSKY_POST = {"uri": "at://did:plc:a/app.bsky.feed.post/3abc", "author": {"handle": "fan.bsky.social"},
             "record": {"text": "Does STARK OS work with Mastodon?", "createdAt": "2026-10-30T10:00:00Z"},
             "likeCount": 3, "repostCount": 1, "replyCount": 0}
MASTO_POST = {"uri": "https://m.example/statuses/1", "id": "1", "url": "https://m.example/@a/1",
              "account": {"acct": "angry@m.example"}, "content": "<p>Your app leaked my data, this is a scam</p>",
              "created_at": "2026-10-30T09:00:00Z", "favourites_count": 0, "reblogs_count": 0, "replies_count": 2}
RIVAL = {"post": {**BSKY_POST, "uri": "at://did:plc:r/app.bsky.feed.post/9", "author": {"handle": "rival.bsky.social"},
                  "record": {"text": "Our launch thread", "createdAt": "2026-10-29T10:00:00Z"}, "likeCount": 40}}


def web(seen: list[str]):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        if req.url.path.endswith("searchPosts"):
            return httpx.Response(200, json={"posts": [BSKY_POST]})
        if req.url.path.endswith("getAuthorFeed"):
            return httpx.Response(200, json={"feed": [RIVAL]})
        if "/timelines/tag/" in req.url.path:
            return httpx.Response(200, json=[MASTO_POST])
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_watch_validation():
    assert growth.clean_watch({"kind": "hashtag", "query": "#BuildInPublic"})["query"] == "BuildInPublic"
    assert growth.clean_watch({"kind": "account", "query": "@rival.bsky.social", "platforms": ["bluesky"]})["query"] == "rival.bsky.social"
    for bad in ({"kind": "hashtag", "query": "two words"}, {"kind": "keyword", "query": "x"}, {"kind": "nope", "query": "abc"},
                {"kind": "keyword", "query": "stark os", "platforms": ["x"]}):
        with pytest.raises(growth.GrowthError):
            growth.clean_watch(bad)


async def test_listening_finds_triages_dedupes_and_tracks_competitors(settings):
    k, _ = make_kernel(settings)
    seen: list[str] = []
    lst = growth.Listening(k, Social(settings), settings, transport=web(seen))
    kw = lst.add({"kind": "keyword", "query": "stark os"})
    lst.add({"kind": "account", "query": "rival.bsky.social", "platforms": ["bluesky"]})
    events = k.bus.subscribe()
    out = await lst.run_once()
    assert out["new"] == 3 and not out["errors"]
    new = lst.mentions("new")
    assert {m["category"] for m in new} == {"question", "escalate"}  # triaged with the inbox rules
    assert any("public.api.bsky.app" in u for u in seen) and any("/timelines/tag/starkos" in u for u in seen)
    assert json.loads(events.get_nowait())["type"] == "listening.hit"
    # nothing new on the next run (not due yet), and a forced run stores no duplicates
    assert (await lst.run_once())["watches"] == 0
    assert (await lst.run_once(force=True))["new"] == 0
    (rival,) = lst.competitors()
    assert rival["posts"] == 1 and rival["best"][0]["likes"] == 40 and rival["avg_score"] == 42
    assert lst.set_status(new[0]["id"], "done") and len(lst.mentions("new")) == 1
    assert lst.watches()[0]["new"] == 1
    assert lst.delete(kw["id"]) and lst.mentions("all", kw["id"]) == []


async def test_telegram_buttons_act_only_for_the_owner_chat_and_the_exact_text(settings):
    settings.telegram_bot_token, settings.telegram_chat_id = "123:abc", "42"
    k, _ = make_kernel(settings)
    social = Social(settings)
    n = growth.Notifier(k, social, settings)
    item = await _draft(k)
    with k.db.session() as s:
        row = to_dict(s.get(ContentItem, item["id"]))
    text, buttons = n.message_for({"type": "content.updated", "data": row})
    assert item["text"] in text and "simulation" in text
    assert n.message_for({"type": "content.updated", "data": row}) is None  # one message per draft
    publish = buttons[0][0]["callback_data"]
    assert publish == f"cn:{item['id']}:p:{fingerprint(row)[:10]}"
    stranger = {"data": publish, "message": {"chat": {"id": 7}}}
    assert await n.handle_callback(stranger) == "Not allowed."
    owner = {"data": publish, "message": {"chat": {"id": 42}}}
    # the post changes after the message was sent: the button refuses
    with k.db.session() as s:
        s.get(ContentItem, item["id"]).text = "Edited text #launch"
    assert "changed" in await n.handle_callback(owner)
    with k.db.session() as s:
        row = to_dict(s.get(ContentItem, item["id"]))
    owner["data"] = f"cn:{item['id']}:p:{fingerprint(row)[:10]}"
    assert await n.handle_callback(owner) == "Simulated 🧪"
    assert "published" in await n.handle_callback(owner)


async def test_telegram_approval_buttons_and_digest(settings):
    settings.telegram_bot_token, settings.telegram_chat_id = "123:abc", "42"
    k, _ = make_kernel(settings)
    t = k._create_task(agent_id="dum_e", instruction="t")
    ap = k.approvals.create(task_id=t["id"], agent_id="dum_e", tool_id="social.publish", action="Publish post",
                            target="bluesky", effects="Posts publicly", risks="public", permissions=[], tool_input={})
    text, buttons = growth.Notifier(k, Social(settings), settings).message_for({"type": "approval.created", "data": ap})
    assert "Posts publicly" in text and buttons[0][1]["callback_data"] == f"ap:{ap['id']}:r"
    n = growth.Notifier(k, Social(settings), settings)
    assert await n.handle_callback({"data": f"ap:{ap['id']}:a", "message": {"chat": {"id": "42"}}}) == "Approved ✅"
    with k.db.session() as s:
        assert s.get(Approval, ap["id"]).decided_by == "telegram"
    assert "Already decided" in await n.handle_callback({"data": f"ap:{ap['id']}:r", "message": {"chat": {"id": "42"}}})
    assert "daily digest" in n.digest_text()
    assert n.message_for({"type": "listening.hit", "data": {"category": "praise"}}) is None
    assert "Complaint" in n.message_for({"type": "listening.hit", "data": {"category": "complaint", "text": "x"}})[0]


async def test_generated_image_is_saved_in_the_workspace_and_attachable(settings):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 200
    calls: list[str] = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, content=png)
    out = await growth.generate_image(settings, "a calm robot arm painting a sunrise", transport=httpx.MockTransport(handler))
    assert out["file"].startswith("media/generated/") and out["mime"] == "image/png"
    assert (settings.workspace_roots[0] / out["file"]).read_bytes() == png
    assert "image.pollinations.ai" in calls[0] and "safe=true" in calls[0]
    k, _ = make_kernel(settings)
    item = await _draft(k, agent="u", media=[{"description": "robot", "alt_text": "A robot arm paints a sunrise", "file": out["file"]}])
    assert item["media"][0]["file"] == out["file"]
    bad = growth.generate_image(settings, "x", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>")))
    with pytest.raises(growth.GrowthError):
        await bad
    settings.image_generator = "off"
    with pytest.raises(growth.GrowthError, match="off"):
        await growth.generate_image(settings, "a robot")


def test_listening_and_notify_api(settings):
    from fastapi.testclient import TestClient

    from stark.main import create_app

    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        assert c.post("/api/listening/watches", json={"kind": "hashtag", "query": "two words"}).status_code == 400
        w = c.post("/api/listening/watches", json={"kind": "hashtag", "query": "launch", "platforms": ["mastodon"]}).json()
        assert c.get("/api/listening/watches").json()["watches"][0]["id"] == w["id"]
        assert c.patch(f"/api/listening/watches/{w['id']}", json={"enabled": False}).json()["enabled"] is False
        assert c.get("/api/listening/mentions").json() == {"mentions": [], "competitors": []}
        assert c.delete(f"/api/listening/watches/{w['id']}").json()["ok"]
        assert c.get("/api/notify/status").json()["telegram"] is False
        assert c.post("/api/notify/test").status_code == 409
        assert c.get("/api/media/file", params={"name": "../../etc/passwd"}).status_code == 404
        img = settings.workspace_roots[0] / growth.IMAGE_DIR
        img.mkdir(parents=True)
        (img / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 50)
        r = c.get("/api/media/file", params={"name": "a.png"})
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert "media.generate_image" in c.get("/api/system/status").json()["tools"]
