"""Instagram, Pinterest, TikTok and YouTube publishing, video attachments and the sign-in flow."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from stark import channels, oauth
from stark.tools import social as social_mod
from stark.tools.social import AdapterError, Social

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64


def _video(settings, size: int = 3000) -> dict:
    d = settings.workspace_roots[0] / "media" / "video"
    d.mkdir(parents=True, exist_ok=True)
    (d / "clip.mp4").write_bytes(b"\0\0\0\x18ftypmp42" + b"v" * (size - 12))
    return social_mod.describe_media(settings, [{"file": "media/video/clip.mp4", "alt_text": "clip"}])[0]


def _image(settings) -> dict:
    (settings.workspace_roots[0] / "pin.png").write_bytes(PNG)
    return social_mod.describe_media(settings, [{"file": "pin.png", "alt_text": "a pin"}])[0]


def test_video_media_and_checks(settings):
    v = _video(settings)
    assert v["type"] == "video" and v["mime"] == "video/mp4" and v["bytes"] == 3000 and "path" not in v
    item = {"text": "New clip", "thread": [], "media": [v]}
    assert social_mod.load_video(settings, item)["sha256"] == v["sha256"]
    codes = lambda p, media: {c["code"] for c in social_mod.check_post(p, "Hello", media=media)["issues"]}  # noqa: E731
    assert "video_unsupported" in codes("bluesky", [v])
    assert "needs_video" in codes("tiktok", [_image(settings)])
    assert not {"video_unsupported", "needs_video", "alt_text"} & codes("tiktok", [v])
    (settings.workspace_roots[0] / "fake.mp4").write_bytes(b"not a video at all")
    with pytest.raises(social_mod.MediaFileError):
        social_mod.describe_media(settings, [{"file": "fake.mp4"}])


async def test_instagram_reel_uploads_from_disk(settings):
    v = _video(settings)
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(f"{req.method} {req.url.host}{req.url.path}")
        q = parse_qs(req.url.query.decode())
        if req.url.path.endswith("/media") and req.method == "POST":
            assert q["media_type"] == ["REELS"] and q["upload_type"] == ["resumable"]
            return httpx.Response(200, json={"id": "c1", "uri": "https://rupload.facebook.com/ig-api-upload/v23.0/c1"})
        if req.url.host == "rupload.facebook.com":
            assert req.headers["file_size"] == "3000" and req.headers["authorization"] == "OAuth itok"
            assert req.content.startswith(b"\0\0\0\x18ftyp")
            return httpx.Response(200, json={"success": True})
        if req.url.path.endswith("/c1"):
            return httpx.Response(200, json={"status_code": "FINISHED"})
        if req.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "m9"})
        return httpx.Response(200, json={"permalink": "https://www.instagram.com/reel/x/"})

    settings.instagram_user_id, settings.instagram_access_token = "17", "itok"
    a = channels.InstagramAdapter(settings, httpx.MockTransport(handler))
    ref = await a.publish({"text": "Reel #launch", "thread": [], "media": [v]}, lambda n, r: None)
    assert ref == {"external_id": "m9", "url": "https://www.instagram.com/reel/x/"}
    assert "POST rupload.facebook.com/ig-api-upload/v23.0/c1" in seen


async def test_instagram_image_needs_facebook_page_then_stages_it(settings):
    img = _image(settings)
    settings.instagram_user_id, settings.instagram_access_token = "17", "itok"
    item = {"text": "Photo", "thread": [], "media": [img]}
    with pytest.raises(AdapterError, match="Facebook Page"):
        await channels.InstagramAdapter(settings, httpx.MockTransport(lambda r: httpx.Response(500))).publish(
            item, lambda n, r: None)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/photos"):
            assert b"published" in req.content and b"false" in req.content
            return httpx.Response(200, json={"id": "ph"})
        if req.url.path.endswith("/ph"):
            return httpx.Response(200, json={"images": [{"width": 100, "source": "https://cdn.fb/small.png"},
                                                        {"width": 1080, "source": "https://cdn.fb/big.png"}]})
        if req.url.path.endswith("/media") and req.method == "POST":
            assert parse_qs(req.url.query.decode())["image_url"] == ["https://cdn.fb/big.png"]
            return httpx.Response(200, json={"id": "c2"})
        if req.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "m2"})
        return httpx.Response(200, json={"status_code": "FINISHED", "permalink": "https://www.instagram.com/p/y/"})

    settings.facebook_page_id, settings.facebook_page_token = "99", "ptok"
    ref = await channels.InstagramAdapter(settings, httpx.MockTransport(handler)).publish(item, lambda n, r: None)
    assert ref["external_id"] == "m2"


async def test_pinterest_pin(settings):
    img = _image(settings)

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["board_id"] == "b1" and body["title"] == "Spring lookbook"
        assert body["link"] == "https://shop.example/spring" and body["media_source"]["source_type"] == "image_base64"
        assert body["alt_text"] == "a pin"
        return httpx.Response(201, json={"id": "p7"})

    settings.pinterest_board_id, settings.pinterest_access_token = "b1", "pina"
    a = channels.PinterestAdapter(settings, httpx.MockTransport(handler))
    ref = await a.publish({"text": "Spring lookbook\nhttps://shop.example/spring", "thread": [], "media": [img]},
                          lambda n, r: None)
    assert ref["url"] == "https://www.pinterest.com/pin/p7/"
    with pytest.raises(AdapterError, match="needs an image"):
        await a.publish({"text": "x", "thread": [], "media": []}, lambda n, r: None)


def test_tiktok_chunk_rules():
    mb = 1024 * 1024
    assert channels.TikTokAdapter.chunks(3 * mb) == (3 * mb, 1)
    assert channels.TikTokAdapter.chunks(64 * mb) == (64 * mb, 1)
    size, count = channels.TikTokAdapter.chunks(105 * mb)
    assert size == 10 * mb and count == 10 and 105 * mb - (count - 1) * size < 128 * mb


async def test_tiktok_refreshes_token_uploads_and_keeps_rotated_token(settings):
    v = _video(settings)
    puts: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v2/oauth/token/":
            form = parse_qs(req.content.decode())
            assert form["client_key"] == ["ck"] and form["refresh_token"] == ["r1"]
            return httpx.Response(200, json={"access_token": "a1", "expires_in": 86400, "refresh_token": "r2"})
        if req.url.path == "/v2/post/publish/video/init/":
            body = json.loads(req.content)
            assert req.headers["authorization"] == "Bearer a1"
            assert body["post_info"]["privacy_level"] == "SELF_ONLY"
            assert body["source_info"] == {"source": "FILE_UPLOAD", "video_size": 3000, "chunk_size": 3000,
                                           "total_chunk_count": 1}
            return httpx.Response(200, json={"data": {"publish_id": "pub1", "upload_url": "https://up.tiktok/u"},
                                             "error": {"code": "ok"}})
        puts.append(req.headers["content-range"])
        return httpx.Response(201)

    settings.tiktok_client_key, settings.tiktok_client_secret, settings.tiktok_refresh_token = "ck", "cs", "r1"
    social = Social(settings, httpx.MockTransport(handler))
    social.store.save("tiktok", {"tiktok_client_key": "ck", "tiktok_client_secret": "cs",
                                 "tiktok_refresh_token": "r1"}, "me")
    ref = await social.adapter("tiktok").publish({"text": "Clip", "thread": [], "media": [v]}, lambda n, r: None)
    assert ref["external_id"] == "pub1" and puts == ["bytes 0-2999/3000"]
    assert settings.tiktok_refresh_token == "r2" and social.store.data["tiktok"]["tiktok_refresh_token"] == "r2"


async def test_youtube_resumable_upload_private_by_default(settings):
    v = _video(settings)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ya29", "expires_in": 3599})
        if req.method == "POST":
            meta = json.loads(req.content)
            assert meta["status"]["privacyStatus"] == "private" and meta["snippet"]["title"] == "My Short"
            assert meta["snippet"]["tags"] == ["shorts"] and req.headers["x-upload-content-length"] == "3000"
            return httpx.Response(200, headers={"location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=u"})
        assert req.method == "PUT" and len(req.content) == 3000
        return httpx.Response(200, json={"id": "vid1"})

    settings.youtube_client_id, settings.youtube_client_secret, settings.youtube_refresh_token = "id", "sec", "rt"
    a = channels.YouTubeAdapter(settings, httpx.MockTransport(handler))
    ref = await a.publish({"text": "My Short\nBehind the scenes #shorts", "thread": [], "media": [v]}, lambda n, r: None)
    assert ref["url"] == "https://www.youtube.com/watch?v=vid1"


async def test_oauth_start_and_finish():
    url = oauth.start("tiktok", "ck", "cs", 51234)
    q = parse_qs(urlparse(url).query)
    assert q["client_key"] == ["ck"] and q["redirect_uri"] == ["http://127.0.0.1:51234/api/oauth/tiktok/callback"]
    assert len(q["code_challenge"][0]) == 64  # TikTok wants the hex SHA-256
    state = q["state"][0]

    def handler(req: httpx.Request) -> httpx.Response:
        form = parse_qs(req.content.decode())
        assert form["code"] == ["abc"] and "code_verifier" in form
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "r", "expires_in": 86400})

    vals = await oauth.finish("tiktok", state, "abc", httpx.MockTransport(handler))
    assert vals == {"tiktok_client_key": "ck", "tiktok_client_secret": "cs", "tiktok_refresh_token": "r"}
    with pytest.raises(oauth.OAuthError, match="expired or was already used"):
        await oauth.finish("tiktok", state, "abc", httpx.MockTransport(handler))
    g = parse_qs(urlparse(oauth.start("youtube", "id", "sec", 8000)).query)
    assert g["access_type"] == ["offline"] and len(g["code_challenge"][0]) == 43
