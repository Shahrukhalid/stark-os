"""Sign-in (OAuth 2.0 with PKCE) for platforms whose access tokens expire quickly: YouTube and TikTok.

The owner uses their own developer app (client ID and secret). STARK opens the platform's sign-in page,
the platform redirects back to this computer (http://127.0.0.1:<port>/api/oauth/<platform>/callback),
and only the long-lived refresh token is stored, in the local account store.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx

PROVIDERS: dict[str, dict[str, Any]] = {
    "youtube": {"auth": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
                "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly",
                "id_param": "client_id", "pkce": "b64",
                "fields": ("youtube_client_id", "youtube_client_secret", "youtube_refresh_token"),
                "extra": {"access_type": "offline", "prompt": "consent"}},
    "tiktok": {"auth": "https://www.tiktok.com/v2/auth/authorize/", "token": "https://open.tiktokapis.com/v2/oauth/token/",
               "scope": "user.info.basic,video.publish,video.upload", "id_param": "client_key", "pkce": "hex",
               "fields": ("tiktok_client_key", "tiktok_client_secret", "tiktok_refresh_token"), "extra": {}},
}
PENDING: dict[str, dict[str, Any]] = {}
TTL_S = 900


class OAuthError(RuntimeError):
    pass


def redirect_uri(port: int, platform: str) -> str:
    return f"http://127.0.0.1:{port}/api/oauth/{platform}/callback"


def start(platform: str, client_id: str, client_secret: str, port: int) -> str:
    p = PROVIDERS[platform]
    if not client_id.strip() or not client_secret.strip():
        raise OAuthError("Enter the client ID and secret of your developer app first.")
    now = time.time()
    for k in [k for k, v in PENDING.items() if v["created"] < now - TTL_S]:
        PENDING.pop(k, None)
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = digest.hex() if p["pkce"] == "hex" else base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    redirect = redirect_uri(port, platform)
    PENDING[state] = {"platform": platform, "client_id": client_id.strip(), "client_secret": client_secret.strip(),
                      "verifier": verifier, "redirect": redirect, "created": now}
    q = {p["id_param"]: client_id.strip(), "redirect_uri": redirect, "response_type": "code", "scope": p["scope"],
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256", **p["extra"]}
    return f"{p['auth']}?{urlencode(q)}"


async def finish(platform: str, state: str, code: str, transport=None) -> dict[str, str]:
    """Exchange the code for tokens; returns the setting values to store."""
    pending = PENDING.pop(state, None)
    if not pending or pending["platform"] != platform or pending["created"] < time.time() - TTL_S:
        raise OAuthError("This sign-in link expired or was already used. Start again from Your accounts.")
    p = PROVIDERS[platform]
    body = {p["id_param"]: pending["client_id"], "client_secret": pending["client_secret"], "code": code,
            "grant_type": "authorization_code", "redirect_uri": pending["redirect"], "code_verifier": pending["verifier"]}
    async with httpx.AsyncClient(timeout=30, transport=transport) as c:
        r = await c.post(p["token"], data=body)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or not data.get("refresh_token"):
        raise OAuthError("The platform did not return a refresh token "
                         f"({data.get('error_description') or data.get('error') or r.status_code}).")
    cid, secret, refresh = p["fields"]
    return {cid: pending["client_id"], secret: pending["client_secret"], refresh: data["refresh_token"]}
