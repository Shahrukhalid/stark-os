"""Dashboard-driven social features: connecting accounts, one-click publish, approved auto-publishing."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from stark.core.db import ContentItem, Database
from stark.main import create_app
from stark.tools import social

from .conftest import ScriptedProvider, text


def bsky_mock(seen):
    def handler(req: httpx.Request):
        p = req.url.path
        if p.endswith("createSession"):
            body = json.loads(req.content)
            seen["login"] = body
            if body["password"] != "abcd-efgh-ijkl-mnop":
                return httpx.Response(401, json={"error": "AuthenticationRequired"})
            return httpx.Response(200, json={"accessJwt": "jwt", "did": "did:plc:x", "handle": body["identifier"]})
        if p.endswith("getRecord"):
            return httpx.Response(400, json={"error": "RecordNotFound"})
        if p.endswith("createRecord"):
            seen.setdefault("posts", []).append(json.loads(req.content)["record"]["text"])
            n = len(seen["posts"])
            return httpx.Response(200, json={"uri": f"at://did:plc:x/app.bsky.feed.post/r{n}", "cid": f"c{n}"})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture
def client(settings):
    settings.scheduler_interval_s = 3600  # tests drive the scheduler by hand
    app = create_app(settings, {"openrouter": ScriptedProvider(lambda a, r: [text("ok")])})
    with TestClient(app) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c


def _wire(client, seen):
    k = client.app.state.kernel
    sc = k.tools.get("social.publish").social
    t = bsky_mock(seen)
    sc.transport = t
    for a in sc.adapters.values():
        a.transport = t
    return k, sc


def _draft(k, platform="bluesky", body="Launch day! https://example.com #launch"):
    with k.db.session() as s:
        row = ContentItem(platform=platform, text=body, created_by="edith",
                          check=social.check_post(platform, body))
        s.add(row)
        s.flush()
        return row.id


def test_connect_bluesky_from_dashboard_stores_locally_and_never_returns_secret(client, settings):
    seen = {}
    k, sc = _wire(client, seen)
    bad = client.post("/api/social/accounts/bluesky", json={"handle": "me.bsky.social", "app_password": "MyMainPassw0rd"})
    assert bad.status_code == 400 and "app password" in bad.json()["detail"]
    assert "login" not in seen  # a main-password-shaped value never even reaches Bluesky
    wrong = client.post("/api/social/accounts/bluesky", json={"handle": "me.bsky.social", "app_password": "zzzz-zzzz-zzzz-zzzz"})
    assert wrong.status_code == 400 and "zzzz" not in wrong.text
    ok = client.post("/api/social/accounts/bluesky", json={"handle": "@me.bsky.social", "app_password": "abcd-efgh-ijkl-mnop"})
    assert ok.status_code == 200 and ok.json()["connected_as"] == "me.bsky.social"
    acct = {a["platform"]: a for a in client.get("/api/social/accounts").json()["accounts"]}["bluesky"]
    assert acct["mode"] == "connected" and acct["source"] == "dashboard"
    assert "abcd-efgh" not in client.get("/api/social/accounts").text
    path = settings.data_dir / "social_accounts.json"
    assert path.is_file() and oct(os.stat(path).st_mode & 0o777) == "0o600"
    # survives a restart
    again = social.AccountStore(settings)
    assert again.connected_as("bluesky") == "me.bsky.social"
    assert client.delete("/api/social/accounts/bluesky").status_code == 200
    acct = {a["platform"]: a for a in client.get("/api/social/accounts").json()["accounts"]}["bluesky"]
    assert acct["mode"] == "simulation"


def test_connect_mastodon_requires_https_and_public_server(client):
    r = client.post("/api/social/accounts/mastodon", json={"base_url": "http://mastodon.example", "access_token": "x" * 20})
    assert r.status_code == 400
    r = client.post("/api/social/accounts/mastodon", json={"base_url": "https://127.0.0.1", "access_token": "x" * 20})
    assert r.status_code == 400 and "refused" in r.json()["detail"]


def test_publish_now_needs_the_exact_text_you_saw(client):
    k, _ = _wire(client, {})
    item_id = _draft(k)
    items = client.get("/api/social/queue").json()["items"]
    fp = items[0]["fingerprint"]
    assert client.post(f"/api/social/items/{item_id}/publish", json={"fingerprint": "0" * 64}).status_code == 409
    r = client.post(f"/api/social/items/{item_id}/publish", json={"fingerprint": fp}).json()
    assert r["ok"] and r["simulated"]  # not connected: simulation, clearly labelled


def test_approved_auto_publish_goes_out_on_time_and_edits_cancel_approval(client, settings):
    seen = {}
    k, sc = _wire(client, seen)
    client.post("/api/social/accounts/bluesky", json={"handle": "me.bsky.social", "app_password": "abcd-efgh-ijkl-mnop"})
    a, b = _draft(k, body="Auto post A #launch"), _draft(k, body="Auto post B #launch")
    fps = {i["id"]: i["fingerprint"] for i in client.get("/api/social/queue").json()["items"]}
    soon = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    for item_id in (a, b):
        r = client.post(f"/api/social/items/{item_id}/schedule", json={"fingerprint": fps[item_id], "when": soon, "auto": True})
        assert r.status_code == 200
    # someone edits B after approval: its approval no longer applies
    from stark.core.runtime import ToolContext

    edit = k.tools.get("social.edit")
    t = k._create_task(agent_id="edith", instruction="t")
    ctx = ToolContext(kernel=k, agent=k.registry.get("edith"), task_id=t["id"], root_id=t["id"], settings=settings)
    client.portal.call(edit.run, edit.Input(item_id=b, text="Edited B #launch"), ctx)
    rows = {i["id"]: i for i in client.get("/api/social/queue").json()["items"]}
    assert rows[a]["auto_publish"] and not rows[b]["auto_publish"]
    time.sleep(1.2)
    out = client.portal.call(social.run_scheduler_once, k, sc, settings)
    assert [o["id"] for o in out if o["outcome"] == "published"] == [a]
    assert seen["posts"] == ["Auto post A #launch"]
    rows = {i["id"]: i for i in client.get("/api/social/queue").json()["items"]}
    assert rows[a]["status"] == "published" and rows[b]["status"] == "scheduled" and not rows[b]["auto_publish"]


def test_scheduler_skips_when_paused_or_late(client, settings):
    k, sc = _wire(client, {})
    item_id = _draft(k)
    fp = client.get("/api/social/queue").json()["items"][0]["fingerprint"]
    soon = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    client.post(f"/api/social/items/{item_id}/schedule", json={"fingerprint": fp, "when": soon, "auto": True})
    client.post("/api/social/queue/pause?paused=true")
    time.sleep(1.2)
    assert client.portal.call(social.run_scheduler_once, k, sc, settings) == []
    client.post("/api/social/queue/pause?paused=false")
    with k.db.session() as s:  # pretend STARK OS was off for a day
        s.get(ContentItem, item_id).scheduled_for = datetime.now(timezone.utc) - timedelta(hours=30)
    out = client.portal.call(social.run_scheduler_once, k, sc, settings)
    assert out == [{"id": item_id, "outcome": "missed"}]
    assert client.get("/api/social/queue").json()["items"][0]["status"] == "scheduled"


def test_upgrade_adds_new_columns_to_an_existing_database(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE content_items (id VARCHAR(40) PRIMARY KEY, platform VARCHAR(24), text TEXT)")
    con.execute("INSERT INTO content_items (id, platform, text) VALUES ('cnt_1', 'x', 'hi')")
    con.commit()
    con.close()
    db = Database(f"sqlite:///{path}")
    db.create_all()
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(content_items)")}
    assert {"auto_publish", "approved_fp", "approved_at", "paused", "autopilot"} <= cols
    tables = {r[0] for r in sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"campaigns", "research_items"} <= tables  # 0.5.0 Autopilot tables are created on upgrade
    with db.session() as s:
        old = s.get(ContentItem, "cnt_1")
        assert old.auto_publish in (False, 0) and old.autopilot is None
    assert social.summarize(to_dict_row(db))["autopilot"] is None


def to_dict_row(db):
    from stark.core.db import to_dict

    with db.session() as s:
        return to_dict(s.get(ContentItem, "cnt_1"))


def test_publish_refuses_when_the_page_expected_a_simulation_but_the_account_is_live(client):
    k, _ = _wire(client, {})
    item_id = _draft(k)
    fp = client.get("/api/social/queue").json()["items"][0]["fingerprint"]
    # The page thinks the account is connected, but it is not: refuse rather than mislabel.
    r = client.post(f"/api/social/items/{item_id}/publish", json={"fingerprint": fp, "live": True})
    assert r.status_code == 409 and "connection changed" in r.json()["detail"]
    r = client.post(f"/api/social/items/{item_id}/publish", json={"fingerprint": fp, "live": False}).json()
    assert r["ok"] and r["simulated"]


def test_calendar_feed_requires_token_and_lists_only_scheduled_posts(client):
    k = client.app.state.kernel
    sched, draft = _draft(k, body="Scheduled, with comma"), _draft(k, body="Just a draft")
    with k.db.session() as s:
        row = s.get(ContentItem, sched)
        row.status = "scheduled"
        row.scheduled_for = datetime.now(timezone.utc) + timedelta(days=2)

    assert TestClient(client.app).get("/api/social/calendar.ics").status_code == 401
    res = client.get("/api/social/calendar.ics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/calendar")
    assert f"UID:{sched}@stark-os" in res.text and draft not in res.text
    assert "SUMMARY:Bluesky: Scheduled\\, with comma" in res.text
    assert res.text.endswith("END:VCALENDAR\r\n")
