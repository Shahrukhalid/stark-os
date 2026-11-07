"""'Log in with …' through Nexonic's official apps (STARK Connect)."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from stark import channels, oauth
from stark.tools.social import Social

CONNECT = "https://connect.test"


def test_official_start_url():
    with pytest.raises(oauth.OAuthError, match="not set up"):
        oauth.official_start("", "facebook", 8000)
    url = urlparse(oauth.official_start(CONNECT, "tiktok", 51234))
    q = parse_qs(url.query)
    assert url.path == "/start/tiktok" and q["return"] == ["http://127.0.0.1:51234/api/oauth/tiktok/callback"]
    assert len(q["challenge"][0]) == 64 and oauth.is_official(q["state"][0])
    assert "challenge" not in parse_qs(urlparse(oauth.official_start(CONNECT, "facebook", 8000)).query)


async def test_official_finish_posts_code_and_verifier():
    state = parse_qs(urlparse(oauth.official_start(CONNECT, "youtube", 8000)).query)["state"][0]

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert req.url.path == "/token/youtube" and body["code"] == "c" and body["code_verifier"]
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "r"})

    assert (await oauth.official_finish(CONNECT, "youtube", state, "c", httpx.MockTransport(handler)))["refresh_token"] == "r"
    with pytest.raises(oauth.OAuthError):
        await oauth.official_finish(CONNECT, "youtube", state, "c", httpx.MockTransport(handler))


async def test_facebook_login_lets_user_pick_a_page(settings):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": [{"id": "1", "name": "Shop", "access_token": "p1"},
                                                      {"id": "2", "name": "Blog", "access_token": "p2"}]})
        return httpx.Response(200, json={"name": "Blog"})

    social = Social(settings, httpx.MockTransport(handler))
    res = await social.finish_login("facebook", {"access_token": "user"})
    assert [o["name"] for o in res["choose"]] == ["Shop", "Blog"]
    token = oauth.remember_pick("facebook", res["choose"])
    assert await social.pick("facebook", oauth.take_pick("facebook", token, "2")) == "Blog"
    assert settings.facebook_page_token == "p2" and social.adapter("facebook") is not None
    with pytest.raises(oauth.OAuthError):
        oauth.take_pick("facebook", token, "2")


async def test_tiktok_login_refreshes_through_connect_server(settings):
    settings.connect_url = CONNECT
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.url.host}{req.url.path}")
        if req.url.host == "connect.test":
            assert json.loads(req.content) == {"refresh_token": "r1"}
            return httpx.Response(200, json={"access_token": "a1", "expires_in": 86400})
        return httpx.Response(200, json={"data": {"user": {"display_name": "Nexonic"}}})

    social = Social(settings, httpx.MockTransport(handler))
    res = await social.finish_login("tiktok", {"access_token": "x", "refresh_token": "r1"})
    assert res == {"who": "Nexonic"} and calls[0] == "connect.test/refresh/tiktok"
    assert social.adapter("tiktok") is not None and not settings.tiktok_client_secret
    acc = {a["platform"]: a for a in social.accounts()}
    assert acc["facebook"]["login"] and acc["tiktok"]["login"] and not acc["bluesky"]["login"]


def test_login_hidden_without_connect_server(settings):
    settings.connect_url = ""
    assert not any(a["login"] for a in Social(settings).accounts())
    assert channels.TikTokAdapter(settings).connected() is False
