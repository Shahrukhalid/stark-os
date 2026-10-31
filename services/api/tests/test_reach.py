"""Threads / Telegram / Discord / Slack publishing, UTM tagging, inbox rules, own feeds, Bluesky DMs, uploads."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from stark import channels, reach
from stark.main import create_app
from stark.tools.social import AdapterError, Social

from .conftest import make_kernel

ITEM = {"id": "cnt_1", "text": "Hello channel", "thread": ["Part two"], "media": []}


async def test_threads_telegram_discord_slack_publish(settings):
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.method} {req.url.host}{req.url.path}")
        if req.url.host == "graph.threads.net":
            if req.url.path.endswith("/threads"):
                return httpx.Response(200, json={"id": "c1"})
            if req.url.path.endswith("/threads_publish"):
                return httpx.Response(200, json={"id": f"m{len(calls)}"})
            return httpx.Response(200, json={"permalink": "https://www.threads.net/@me/post/x"})
        if req.url.host == "api.telegram.org":
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
        if req.url.host == "discord.com":
            assert json.loads(req.content)["allowed_mentions"] == {"parse": []}
            return httpx.Response(200, json={"id": "d1"})
        return httpx.Response(200, text="ok")
    settings.threads_access_token, settings.threads_user_id = "tok", "42"
    settings.telegram_bot_token, settings.telegram_channel_id = "1:a", "@starkos"
    settings.discord_post_webhook_url = "https://discord.com/api/webhooks/1/x"
    settings.slack_webhook_url = "https://hooks.slack.com/services/T/B/X"
    a = channels.build(settings, httpx.MockTransport(handler))
    parts: list[tuple[str, int]] = []
    ref = await a["threads"].publish(ITEM, lambda n, r: parts.append(("threads", n)))
    assert ref["url"] == "https://www.threads.net/@me/post/x" and parts == [("threads", 0), ("threads", 1)]
    assert (await a["telegram"].publish(ITEM, lambda n, r: None))["url"] == "https://t.me/starkos/7"
    assert (await a["discord"].publish(ITEM, lambda n, r: None))["external_id"] == "d1"
    assert (await a["slack"].publish(ITEM, lambda n, r: None))["url"] is None
    with pytest.raises(AdapterError, match="public web address"):
        await a["threads"].publish({**ITEM, "media": [{"file": "x.png"}]}, lambda n, r: None)
    accounts = {x["platform"]: x for x in Social(settings).accounts()}
    assert all(accounts[p]["mode"] == "connected" for p in ("threads", "telegram", "discord", "slack"))
    assert accounts["slack"]["can_connect"] is False  # set in .env, no dashboard form


def test_utm_tags_only_own_links():
    t = reach.add_utm("Read https://blog.example.com/post?x=1, and https://bsky.app/profile/me plus https://a.example/?utm_source=x", "bluesky", "Launch Week")
    assert "https://blog.example.com/post?x=1&utm_source=bluesky&utm_medium=social&utm_campaign=launch-week," in t
    assert "https://bsky.app/profile/me plus" in t and t.count("utm_source") == 2


def test_rules_feeds_dms_and_uploads_api(client, settings):
    r = client.put("/api/inbox/rules", json={"rules": [{"contains": "Refund, money back", "label": "Billing", "priority": "high"},
                                                      {"contains": "", "label": "x"}]}).json()
    assert r["rules"] == [{"contains": "refund, money back", "label": "Billing", "priority": "high"}]
    assert reach.apply_rules(r["rules"], "I want my MONEY BACK") == ["Billing"]
    assert client.put("/api/feeds", json={"feeds": [{"kind": "blog", "url": "http://insecure.example/feed"}]}).status_code == 400
    f = client.put("/api/feeds", json={"feeds": [{"kind": "youtube", "url": "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv"}]}).json()
    assert f["feeds"][0]["url"].endswith("channel_id=UCabcdefghijklmnopqrstuv") and f["feeds"][0]["template"].startswith("New video")
    assert client.get("/api/inbox/dms").status_code == 409  # Bluesky not connected
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    up = client.post("/api/media/upload?name=Quote card", content=png, headers={"content-type": "image/png"}).json()
    assert up["file"].startswith("media/generated/") and "quote-card" in up["name"]
    assert client.post("/api/media/upload", content=b"<svg/>").status_code == 400
    d = client.post("/api/social/drafts", json={"platform": "mastodon", "text": "Out now https://shop.example/new", "campaign": "Spring"}).json()
    tagged = client.post(f"/api/social/items/{d['id']}/utm").json()
    assert "utm_campaign=spring" in tagged["text"]


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c


async def test_own_feeds_prime_first_then_draft_new_items(settings):
    k, _ = make_kernel(settings)
    social = Social(settings)
    reach.save_feeds(k, [{"kind": "podcast", "url": "https://pod.example/rss", "platforms": ["bluesky", "mastodon"]}])
    items = [{"title": "Ep 1", "url": "https://pod.example/1"}]

    async def fetch(url):
        return list(items)
    assert (await reach.check_feeds(k, social, settings, fetch))["drafts"] == []  # first look: remember only
    items.insert(0, {"title": "Ep 2: Free AI tools", "url": "https://pod.example/2"})
    out = await reach.check_feeds(k, social, settings, fetch)
    assert len(out["drafts"]) == 2
    assert (await reach.check_feeds(k, social, settings, fetch))["drafts"] == []


async def test_bluesky_dms_list_read_and_send(settings):
    settings.bluesky_handle, settings.bluesky_app_password = "me.bsky.social", "abcd-efgh-ijkl-mnop"
    sent = []

    def handler(req):
        if req.url.path.endswith("createSession"):
            return httpx.Response(200, json={"accessJwt": "j", "did": "did:me"})
        assert req.headers["atproto-proxy"] == "did:web:api.bsky.chat#bsky_chat"
        if req.url.path.endswith("listConvos"):
            return httpx.Response(200, json={"convos": [{"id": "c1", "unreadCount": 2, "members": [{"did": "did:me"}, {"did": "did:a", "handle": "ann.bsky.social"}],
                                                         "lastMessage": {"text": "Hi!", "sender": {"did": "did:a"}, "sentAt": "2026-10-31T10:00:00Z"}}]})
        if req.url.path.endswith("getMessages"):
            return httpx.Response(200, json={"messages": [{"id": "2", "text": "Hi!", "sender": {"did": "did:a"}}, {"id": "1", "text": "Hello", "sender": {"did": "did:me"}}]})
        sent.append(json.loads(req.content))
        return httpx.Response(200, json={"id": "3", "sentAt": "now"})
    social = Social(settings, transport=httpx.MockTransport(handler))
    (c,) = await reach.bluesky_dms(social)
    assert c["with"] == "@ann.bsky.social" and c["unread"] == 2 and not c["last_from_me"]
    msgs = await reach.bluesky_dm_messages(social, "c1")
    assert [m["text"] for m in msgs] == ["Hello", "Hi!"] and msgs[0]["from_me"]
    await reach.bluesky_dm_send(social, "c1", "Thanks!")
    assert sent == [{"convoId": "c1", "message": {"text": "Thanks!"}}]
