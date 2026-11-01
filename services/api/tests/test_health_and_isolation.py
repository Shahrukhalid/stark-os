"""Account health checks and per-brand isolation."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from stark import automations, brands, health, hub
from stark.core import db as dbm
from stark.core.db import ContentItem
from stark.main import create_app
from stark.tools.social import Social, check_post

from .conftest import make_kernel


def platform_api(telegram_admin: bool = True, mastodon_ok: bool = True):
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        assert req.method == "GET", "health checks must never post"
        if "verify_credentials" in url:
            return httpx.Response(200 if mastodon_ok else 401, json={"acct": "me"})
        if url.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 42, "username": "starkbot"}})
        if "getChatMember" in url:
            return httpx.Response(200, json={"ok": True, "result": {"status": "administrator" if telegram_admin else "left"}})
        if "discord.com/api/webhooks" in url:
            return httpx.Response(404, json={"message": "Unknown Webhook"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def connect(settings):
    settings.mastodon_base_url = "https://social.example"
    settings.mastodon_access_token = "tok"
    settings.telegram_bot_token = "123:abc"
    settings.telegram_channel_id = "@news"
    settings.discord_post_webhook_url = "https://discord.com/api/webhooks/1/x"
    settings.slack_webhook_url = "https://hooks.slack.com/services/T/B/C"


@pytest.mark.asyncio
async def test_health_checks_without_posting_and_alerts_once(settings):
    connect(settings)
    k, _ = make_kernel(settings)
    events: list[tuple[str, dict]] = []
    publish = k.bus.publish
    k.bus.publish = lambda t, d: (events.append((t, d)), publish(t, d))
    social = Social(settings, platform_api())

    r = await health.check_all(k, social)
    by = {e["platform"]: e for e in r["accounts"]}
    assert set(by) == {"mastodon", "telegram", "discord", "slack"}  # only connected accounts
    assert by["mastodon"]["status"] == "ok" and "@me" in by["mastodon"]["message"]
    assert by["telegram"]["status"] == "ok"
    assert by["discord"]["status"] == "error"
    assert by["slack"]["status"] == "warning"
    assert r["overall"] == "error" and r["needs_attention"] == ["discord"]
    assert [d["platform"] for t, d in events if t == "account.unhealthy"] == ["discord"]
    assert health.cached(k)["needs_attention"] == ["discord"]

    # still broken: no second alert; the bot losing admin rights is a new alert
    events.clear()
    await health.check_all(k, Social(settings, platform_api(telegram_admin=False)))
    assert [d["platform"] for t, d in events if t == "account.unhealthy"] == ["telegram"]


@pytest.mark.asyncio
async def test_recent_failures_downgrade_and_slack_failure_is_an_error(settings):
    connect(settings)
    settings.discord_post_webhook_url = ""
    settings.telegram_bot_token = ""
    k, _ = make_kernel(settings)
    with k.db.session() as s:
        for p in ("mastodon", "slack"):
            s.add(ContentItem(platform=p, text="x", status="failed", created_by="user", error="invalid_token"))
    r = await health.check_all(k, Social(settings, platform_api()))
    by = {e["platform"]: e for e in r["accounts"]}
    assert by["mastodon"]["status"] == "warning" and "invalid_token" in by["mastodon"]["message"]
    assert by["slack"]["status"] == "error" and by["slack"]["failed_recently"] == 1


def test_unhealthy_event_reaches_webhooks_and_automations():
    p = hub.webhook_payload({"type": "account.unhealthy", "ts": "t", "data": {"platform": "threads", "message": "m"}})
    assert p == {"event": "account.unhealthy", "at": "t", "data": {"platform": "threads", "message": "m"}}
    assert "account.unhealthy" in automations.EVENTS
    assert automations.from_recipe("account-health")["trigger"]["event"] == "account.unhealthy"


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c
    dbm.ACTIVE_BRAND.update({"name": "", "blocked_terms": []})


def test_health_endpoints(client):
    assert client.get("/api/social/health").json()["accounts"] == []
    r = client.post("/api/social/health/check").json()  # nothing connected in tests
    assert r["overall"] == "ok" and r["accounts"] == []


def test_active_brand_scopes_queue_analytics_and_campaigns(client):
    a = client.post("/api/brands", json={"name": "Acme", "blocked_terms": ["cheap"]}).json()
    b = client.post("/api/brands", json={"name": "Beta"}).json()
    client.post("/api/brands/active", json={"id": a["id"]})
    client.post("/api/social/drafts", json={"platform": "bluesky", "text": "Acme post"})
    client.post("/api/brands/active", json={"id": b["id"]})
    client.post("/api/social/drafts", json={"platform": "bluesky", "text": "Beta post"})

    q = client.get("/api/social/queue").json()
    assert q["brand"] == "Beta" and [i["text"] for i in q["items"]] == ["Beta post"]
    assert [i["text"] for i in client.get("/api/social/queue?brand=Acme").json()["items"]] == ["Acme post"]
    assert len(client.get("/api/social/queue?brand=all").json()["items"]) == 2

    camp = {"name": "Beta news", "platforms": ["bluesky"], "topics": ["news"], "keywords": ["news"], "sources": [{"type": "rss", "value": "https://feeds.example.com/f.xml"}]}
    assert client.post("/api/autopilot/campaigns", json=camp).status_code == 200
    assert [c["name"] for c in client.get("/api/autopilot/campaigns").json()["campaigns"]] == ["Beta news"]
    client.post("/api/brands/active", json={"id": a["id"]})
    assert client.get("/api/autopilot/campaigns").json()["campaigns"] == []
    assert len(client.get("/api/autopilot/campaigns?brand=all").json()["campaigns"]) == 1
    assert client.get("/api/social/analytics?brand=Acme").status_code == 200

    # a campaign writing for another brand is checked against that brand's words, not the active one
    assert not any(i["code"] == "blocked_term" for i in
                   check_post("bluesky", "So cheap!", active_brand=False)["issues"])
    assert any(i["code"] == "blocked_term" for i in check_post("bluesky", "So cheap!")["issues"])
    k = client.app.state.kernel
    assert brands.by_name(k, "Acme")["blocked_terms"] == ["cheap"] and brands.by_name(k, "Nope") is None
    assert "Never use: cheap" in brands.brief(brands.by_name(k, "Acme")) and brands.brief(None) == ""
