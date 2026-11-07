"""Facebook Page and LinkedIn (own profile) publishing."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx
import pytest

from stark import channels
from stark.tools.social import AdapterError, Social

ITEM = {"id": "cnt_1", "text": "Launch (v2) is live #buildinpublic", "thread": ["Part two"], "media": []}


async def test_facebook_page_posts_text_and_thread_as_comments(settings):
    calls: list[tuple[str, dict]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        calls.append((req.url.path, form))
        if req.url.path.endswith("/feed"):
            return httpx.Response(200, json={"id": "99_1"})
        if req.url.path.endswith("/comments"):
            return httpx.Response(200, json={"id": "c_2"})
        return httpx.Response(404)

    settings.facebook_page_id, settings.facebook_page_token = "99", "ptok"
    social = Social(settings, httpx.MockTransport(handler))
    parts: list[int] = []
    ref = await social.adapter("facebook").publish(ITEM, lambda n, r: parts.append(n))
    assert ref == {"external_id": "99_1", "url": "https://www.facebook.com/99_1"}
    assert calls[0] == ("/v23.0/99/feed", {"access_token": "ptok", "message": ITEM["text"]})
    assert calls[1] == ("/v23.0/99_1/comments", {"access_token": "ptok", "message": "Part two"})
    assert parts == [0, 1]
    assert next(a for a in social.accounts() if a["platform"] == "facebook")["mode"] == "connected"


async def test_facebook_error_is_readable(settings):
    settings.facebook_page_id, settings.facebook_page_token = "99", "bad"
    t = httpx.MockTransport(lambda r: httpx.Response(400, json={"error": {"message": "Invalid OAuth access token."}}))
    with pytest.raises(AdapterError, match="Invalid OAuth access token"):
        await channels.FacebookPageAdapter(settings, t).publish(ITEM, lambda n, r: None)


async def test_facebook_metrics(settings):
    settings.facebook_page_id, settings.facebook_page_token = "99", "ptok"
    body = {"reactions": {"summary": {"total_count": 5}}, "comments": {"summary": {"total_count": 2}},
            "shares": {"count": 1}}
    a = channels.FacebookPageAdapter(settings, httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    assert await a.metrics(["99_1"]) == {"99_1": {"likes": 5, "replies": 2, "reposts": 1}}


def test_linkedin_commentary_escapes_markup_and_keeps_hashtags():
    out = channels.linkedin_commentary("Launch (v2) is live #buildinpublic a_b @me")
    assert out == "Launch \\(v2\\) is live {hashtag|\\#|buildinpublic} a\\_b \\@me"


async def test_linkedin_posts_single_post_with_thread_joined(settings):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/v2/userinfo":
            return httpx.Response(200, json={"sub": "abc", "name": "Me"})
        if req.url.path == "/rest/posts":
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:7"})
        return httpx.Response(404)

    settings.linkedin_access_token = "ltok"
    social = Social(settings, httpx.MockTransport(handler))
    ref = await social.adapter("linkedin").publish(ITEM, lambda n, r: None)
    assert ref["url"] == "https://www.linkedin.com/feed/update/urn:li:share:7/"
    post = seen[-1]
    body = json.loads(post.content)
    assert body["author"] == "urn:li:person:abc" and body["visibility"] == "PUBLIC"
    assert body["commentary"].endswith("{hashtag|\\#|buildinpublic}\n\nPart two")
    assert post.headers["LinkedIn-Version"] == settings.linkedin_api_version
    assert post.headers["X-Restli-Protocol-Version"] == "2.0.0"


async def test_linkedin_rejects_too_long_and_old_version(settings):
    settings.linkedin_access_token, settings.linkedin_author_urn = "ltok", "urn:li:person:abc"
    a = channels.LinkedInAdapter(settings, httpx.MockTransport(lambda r: httpx.Response(426)))
    with pytest.raises(AdapterError, match="3,000"):
        await a.publish({**ITEM, "text": "x" * 3001}, lambda n, r: None)
    with pytest.raises(AdapterError, match="LINKEDIN_API_VERSION"):
        await a.publish(ITEM, lambda n, r: None)


def test_unconnected_platforms_explain_why(settings):
    acc = {a["platform"]: a for a in Social(settings).accounts()}
    for p in ("x", "instagram", "tiktok", "youtube", "facebook", "linkedin"):
        assert acc[p]["mode"] == "simulation" and acc[p]["detail"]
    assert acc["facebook"]["can_connect"] and acc["linkedin"]["can_connect"]
    assert "public web address" in acc["instagram"]["detail"] and "every post" in acc["x"]["detail"]


async def test_images_upload_to_facebook_and_linkedin(settings, monkeypatch):
    import stark.tools.social as social_mod

    img = ({"file": "brand/launch.png", "mime": "image/png"}, b"\x89PNG data")
    monkeypatch.setattr(social_mod, "load_attachments", lambda s, item: [img])
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(f"{req.method} {req.url.host}{req.url.path}")
        if req.url.path.endswith("/photos"):
            assert b"launch.png" in req.content and b"\x89PNG data" in req.content
            return httpx.Response(200, json={"id": "ph1", "post_id": "99_5"})
        if req.url.path == "/rest/images":
            return httpx.Response(200, json={"value": {"uploadUrl": "https://www.linkedin.com/dms-uploads/x",
                                                       "image": "urn:li:image:9"}})
        if req.url.path == "/dms-uploads/x":
            assert req.content == b"\x89PNG data"
            return httpx.Response(201)
        if req.url.path == "/rest/posts":
            assert json.loads(req.content)["content"] == {"media": {"id": "urn:li:image:9"}}
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:8"})
        return httpx.Response(200, json={"id": "c"})

    t = httpx.MockTransport(handler)
    settings.facebook_page_id, settings.facebook_page_token = "99", "ptok"
    settings.linkedin_access_token, settings.linkedin_author_urn = "ltok", "urn:li:person:abc"
    one = {**ITEM, "thread": []}
    assert (await channels.FacebookPageAdapter(settings, t).publish(one, lambda n, r: None))["external_id"] == "99_5"
    assert (await channels.LinkedInAdapter(settings, t).publish(one, lambda n, r: None))["external_id"] == "urn:li:share:8"
    assert "PUT www.linkedin.com/dms-uploads/x" in paths


async def test_dashboard_connect_checks_then_saves(settings):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "graph.facebook.com":
            ok = parse_qs(req.url.query.decode())["access_token"] == ["good"]
            return httpx.Response(200, json={"name": "Nexonic"}) if ok else httpx.Response(400, json={})
        return httpx.Response(200, json={"name": "general"})

    social = Social(settings, httpx.MockTransport(handler))
    with pytest.raises(AdapterError, match="rejected"):
        await social.connect_generic("facebook", {"facebook_page_id": "99", "facebook_page_token": "bad"})
    assert social.adapter("facebook") is None
    who = await social.connect_generic("facebook", {"facebook_page_id": "99", "facebook_page_token": "good"})
    assert who == "Nexonic" and social.adapter("facebook") is not None
    with pytest.raises(AdapterError, match="format"):
        await social.connect_generic("discord", {"discord_post_webhook_url": "https://example.com/hook"})
    assert await social.connect_generic(
        "discord", {"discord_post_webhook_url": "https://discord.com/api/webhooks/1/x"}) == "#general"
    acc = {a["platform"]: a for a in social.accounts()}
    assert acc["facebook"]["connected_as"] == "Nexonic" and acc["facebook"]["source"] == "dashboard"
    assert acc["linkedin"]["can_connect"] and acc["linkedin"]["form"]["fields"][0]["secret"]
    assert not acc["x"]["can_connect"] and acc["x"]["form"] is None
    # saved values survive a restart and the secret is never in the accounts list
    again = {a["platform"]: a for a in Social(settings).accounts()}
    assert again["facebook"]["mode"] == "connected" and "good" not in json.dumps(again)
