"""Brands, sentiment and hashtag research."""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from stark import brands, growth
from stark.core import db as dbm
from stark.core.db import utcnow
from stark.main import create_app
from stark.sentiment import analyze
from stark.tools.social import check_post


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        c.headers["authorization"] = f"Bearer {settings.api_token}"
        yield c
    dbm.ACTIVE_BRAND.update({"name": "", "blocked_terms": []})


def test_sentiment_labels():
    assert analyze("I love this, amazing work!")[0] == "positive"
    assert analyze("This is terrible, it crashes all the time 😡")[0] == "negative"
    assert analyze("not good at all")[0] == "negative"
    assert analyze("not bad")[0] == "positive"
    assert analyze("The update ships on Tuesday") == ("neutral", 0.0)
    assert -1 <= analyze("worst worst worst scam garbage")[1] <= 1


def test_brands_crud_activate_prompt_and_blocked_words(client):
    assert client.post("/api/brands", json={"name": ""}).status_code == 400
    a = client.post("/api/brands", json={"name": "Acme", "voice": "Friendly and short", "audience": "Makers",
                                         "hashtags": "launch, #maker", "blocked_terms": ["cheap"],
                                         "platforms": ["bluesky", "Bad Value!"], "color": "nope"}).json()
    assert a["hashtags"] == ["#launch", "#maker"] and a["platforms"] == ["bluesky"] and a["color"] == "#22d3ee"
    assert client.post("/api/brands", json={"name": "Acme"}).status_code == 400  # unique names
    b = client.post("/api/brands", json={"name": "Beta"}).json()

    client.post("/api/brands/active", json={"id": a["id"]})
    listed = client.get("/api/brands").json()
    assert listed["active"] == a["id"] and [x["active"] for x in listed["brands"]] == [True, False]
    k = client.app.state.kernel
    section = brands.prompt_section(k)
    assert "Active brand: Acme" in section and "Friendly and short" in section and "cheap" in section
    # the post checker enforces the active brand's words, new content is tagged with it
    assert any(i["code"] == "blocked_term" for i in check_post("bluesky", "So cheap!")["issues"])
    draft = client.post("/api/social/drafts", json={"platform": "bluesky", "text": "Hello makers"}).json()
    assert draft.get("brand", draft.get("item", {}).get("brand")) == "Acme"

    # renaming keeps content attached; deleting the active brand clears it
    client.put(f"/api/brands/{a['id']}", json={"name": "Acme Labs"})
    assert any(x["name"] == "Acme Labs" and x["items"] == 1 for x in client.get("/api/brands").json()["brands"])
    assert client.delete(f"/api/brands/{a['id']}").json()["ok"]
    assert client.get("/api/brands").json()["active"] == ""
    assert brands.prompt_section(k) == ""
    assert not any(i["code"] == "blocked_term" for i in check_post("bluesky", "So cheap!")["issues"])
    assert client.post("/api/brands/active", json={"id": "brd_missing"}).status_code == 404
    client.post("/api/brands/active", json={"id": b["id"]})
    client.post("/api/brands/active", json={"id": None})
    assert client.get("/api/brands").json()["active"] == ""


def test_hashtag_report_numbers_and_advice():
    now = utcnow()
    posts = [{"platform": "bluesky", "author": "a", "text": "Shipping today #launch #indiedev 🚀",
              "posted_at": (now - timedelta(hours=2)).isoformat(), "likes": 30, "reposts": 4, "replies": 2},
             {"platform": "mastodon", "author": "b", "text": "Terrible #launch, it crashes #bugs",
              "posted_at": (now - timedelta(days=3)).isoformat(), "likes": 1, "reposts": 0, "replies": 0},
             {"platform": "bluesky", "author": "c", "text": "old #launch #indiedev",
              "posted_at": (now - timedelta(days=20)).isoformat(), "likes": 0, "reposts": 0, "replies": 0}]
    r = growth.hashtag_report("launch", posts, now=now)
    assert r["found"] == 3 and r["last_24h"] == 1 and r["last_7d"] == 2
    assert r["related"][0] == {"tag": "#indiedev", "count": 2}
    assert r["top_posts"][0]["author"] == "a" and r["sentiment"]["negative"] == 1
    assert r["by_platform"] == {"bluesky": 2, "mastodon": 1} and r["advice"]
    assert "No recent posts" in growth.hashtag_report("x", [])["advice"]


def test_hashtag_endpoint_validates(client):
    assert client.get("/api/growth/hashtag", params={"tag": "two words"}).status_code == 400


def test_mentions_get_sentiment_and_mood(client):
    k = client.app.state.kernel
    lst = k.listening
    w = lst.add_watch({"kind": "keyword", "query": "stark", "platforms": ["bluesky"]}) \
        if hasattr(lst, "add_watch") else None
    watch = w or {"id": "wch_test", "kind": "keyword", "query": "stark"}
    new = lst._store(watch, [
        {"platform": "bluesky", "external_id": "1", "author": "x", "text": "I love it, amazing!", "posted_at": None},
        {"platform": "bluesky", "external_id": "2", "author": "y", "text": "Awful, it is broken and useless",
         "posted_at": None}])
    assert {m["sentiment"] for m in new} == {"positive", "negative"}
    got = client.get("/api/listening/mentions", params={"sentiment": "negative", "status": "all"}).json()
    assert [m["author"] for m in got["mentions"]] == ["y"]
    assert got["mood"]["negative"] == 1 and got["mood"]["positive"] == 1
    assert client.get("/api/listening/mentions", params={"sentiment": "angry"}).status_code == 400
