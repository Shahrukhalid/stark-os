"""Social logins are renewed before they expire; LinkedIn warns before its 60 days are up."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx

from stark import health, token_refresh
from stark.tools.social import Social


class _Kernel:
    class obs:  # noqa: N801 - minimal stand-in
        audits: list = []

        @classmethod
        def audit(cls, *a, **k):
            cls.audits.append((a, k))

    class db:  # noqa: N801
        saved: dict = {}

        @classmethod
        def set_setting(cls, key, value):
            cls.saved[key] = value


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def test_instagram_and_threads_tokens_are_renewed_and_saved(settings):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.url.host, req.url.path, dict(req.url.params)))
        return httpx.Response(200, json={"access_token": f"new-{req.url.host}", "expires_in": 5184000})

    social = Social(settings, httpx.MockTransport(handler))
    social.store.save("instagram", {"instagram_user_id": "1", "instagram_access_token": "old-ig"}, "@me")
    social.store.save("threads", {"threads_user_id": "2", "threads_access_token": "old-th"}, "@me")
    social.store.update("instagram", "token_at", _ago(8))
    social.store.update("threads", "token_at", _ago(1))  # renewed recently: left alone

    out = await token_refresh.renew_due(_Kernel, social)
    assert out == {"instagram": "renewed"}
    assert seen == [("graph.instagram.com", "/refresh_access_token",
                     {"grant_type": "ig_refresh_token", "access_token": "old-ig"})]
    assert settings.instagram_access_token == "new-graph.instagram.com"
    reloaded = Social(settings).store.data["instagram"]
    assert reloaded["instagram_access_token"] == "new-graph.instagram.com"
    assert token_refresh.token_age(social.store, "instagram") < timedelta(minutes=1)


async def test_failed_renewal_keeps_the_old_token_and_reports(settings):
    t = httpx.MockTransport(lambda r: httpx.Response(400, json={"error": {"message": "Session has expired"}}))
    social = Social(settings, t)
    social.store.save("threads", {"threads_user_id": "2", "threads_access_token": "old-th"}, "@me")
    social.store.update("threads", "token_at", _ago(30))
    out = await token_refresh.renew_due(_Kernel, social)
    assert out["threads"].startswith("failed") and "Session has expired" in out["threads"]
    assert settings.threads_access_token == "old-th"


async def test_pinterest_renews_through_connect_only_with_a_refresh_token(settings):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, json={"access_token": "pin-new", "refresh_token": "ref-new"})

    social = Social(settings, httpx.MockTransport(handler))
    social.store.save("pinterest", {"pinterest_board_id": "b", "pinterest_access_token": "pin-old"}, "Board")
    social.store.update("pinterest", "token_at", _ago(25))
    assert not token_refresh.due(social.store, "pinterest")  # no refresh token, no Connect address
    settings.connect_url = "https://connect.test"
    social.store.update("pinterest", "pinterest_refresh_token", "ref-old")
    assert await token_refresh.renew_due(_Kernel, social) == {"pinterest": "renewed"}
    assert calls == ["https://connect.test/refresh/pinterest"]
    assert social.store.data["pinterest"]["pinterest_refresh_token"] == "ref-new"
    assert settings.pinterest_access_token == "pin-new"


async def test_env_tokens_are_never_rewritten(settings):
    settings.instagram_user_id, settings.instagram_access_token = "1", "env-token"
    social = Social(settings, httpx.MockTransport(lambda r: httpx.Response(500)))
    assert not token_refresh.due(social.store, "instagram")


async def test_linkedin_warns_ten_days_before_expiry(settings, monkeypatch):
    t = httpx.MockTransport(lambda r: httpx.Response(200, json={"name": "Shahrukh"}))
    social = Social(settings, t)
    social.store.save("linkedin", {"linkedin_access_token": "li"}, "Shahrukh")
    social.store.update("linkedin", "token_at", _ago(55))
    assert token_refresh.linkedin_days_left(social.store) == 4

    class K(_Kernel):
        class db(_Kernel.db):  # noqa: N801
            @staticmethod
            def get_setting(key):
                return None

        class bus:  # noqa: N801
            @staticmethod
            def publish(*a, **k):
                pass

    monkeypatch.setattr(health, "_recent_failures", lambda kernel, platform, days=3: (0, ""))  # no database here
    result = await health.check_all(K, social)
    li = next(e for e in result["accounts"] if e["platform"] == "linkedin")
    assert li["status"] == health.WARN and "4 day" in li["message"]


async def test_instagram_youtube_and_pinterest_report_real_engagement(settings):
    from stark import channels

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "graph.instagram.com":
            return httpx.Response(200, json={"like_count": 7, "comments_count": 3})
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "yt", "expires_in": 3600})
        if req.url.path == "/youtube/v3/videos":
            assert req.url.params["id"] == "v1,v2"
            return httpx.Response(200, json={"items": [
                {"id": "v1", "statistics": {"likeCount": "10", "commentCount": "2", "viewCount": "500"}}]})
        if req.url.path.endswith("/analytics"):
            return httpx.Response(200, json={"all": {"lifetime_metrics": {
                "IMPRESSION": 900, "SAVE": 12, "PIN_CLICK": 4, "TOTAL_COMMENTS": 1, "TOTAL_REACTIONS": 6}}})
        return httpx.Response(404)

    t = httpx.MockTransport(handler)
    settings.instagram_user_id, settings.instagram_access_token = "1", "ig"
    settings.youtube_client_id, settings.youtube_client_secret, settings.youtube_refresh_token = "c", "s", "r"
    settings.pinterest_access_token, settings.pinterest_board_id = "pin", "b"
    built = channels.build(settings, t)
    assert await built["instagram"].metrics(["m1"]) == {"m1": {"likes": 7, "replies": 3, "reposts": 0}}
    assert await built["youtube"].metrics(["v1", "v2"]) == {
        "v1": {"likes": 10, "replies": 2, "reposts": 0, "views": 500}}
    assert await built["pinterest"].metrics(["p1"]) == {
        "p1": {"likes": 6, "reposts": 12, "replies": 1, "views": 900, "clicks": 4}}


async def test_tiktok_engagement_maps_publish_ids_to_public_videos(settings):
    from stark import channels

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/oauth/token/":
            return httpx.Response(200, json={"access_token": "tt", "expires_in": 86400})
        if req.url.path == "/v2/post/publish/status/fetch/":
            pid = json.loads(req.content)["publish_id"]
            ids = [7300000000000000001] if pid == "pub-public" else []  # private posts have no video ID
            return httpx.Response(200, json={"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": ids}})
        if req.url.path == "/v2/video/query/":
            assert json.loads(req.content) == {"filters": {"video_ids": ["7300000000000000001"]}}
            assert "view_count" in req.url.params["fields"]
            return httpx.Response(200, json={"data": {"videos": [{"id": "7300000000000000001", "like_count": 9,
                                                                   "comment_count": 2, "share_count": 1,
                                                                   "view_count": 300}]}})
        return httpx.Response(404)

    settings.tiktok_client_key, settings.tiktok_client_secret, settings.tiktok_refresh_token = "k", "s", "r"
    tiktok = channels.build(settings, httpx.MockTransport(handler))["tiktok"]
    assert await tiktok.metrics(["pub-public", "pub-private"]) == {
        "pub-public": {"likes": 9, "replies": 2, "reposts": 1, "views": 300}}


async def test_linkedin_engagement_and_quiet_without_permission(settings):
    from stark import channels

    calls = []

    def ok(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.raw_path.decode())
        return httpx.Response(200, json={"likesSummary": {"totalLikes": 5},
                                         "commentsSummary": {"aggregatedTotalComments": 3}})

    settings.linkedin_access_token = "li"
    li = channels.build(settings, httpx.MockTransport(ok))["linkedin"]
    assert await li.metrics(["urn:li:share:1"]) == {"urn:li:share:1": {"likes": 5, "replies": 3, "reposts": 0}}
    assert calls == ["/rest/socialActions/urn%3Ali%3Ashare%3A1"]

    denied = []
    li = channels.build(settings, httpx.MockTransport(lambda r: denied.append(1) or httpx.Response(403)))["linkedin"]
    assert await li.metrics(["urn:li:share:1", "urn:li:share:2"]) == {}
    assert len(denied) == 1  # stops after the first refusal


def test_tiktok_analytics_adds_video_list_to_sign_in():
    from urllib.parse import parse_qs, urlparse

    from stark import oauth

    plain = parse_qs(urlparse(oauth.start("tiktok", "k", "s", 8000)).query)["scope"][0]
    extra = parse_qs(urlparse(oauth.start("tiktok", "k", "s", 8000, "video.list")).query)["scope"][0]
    assert plain == "user.info.basic,video.publish,video.upload"
    assert extra == plain + ",video.list"
