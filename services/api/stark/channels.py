"""More places to publish: Threads and Facebook Pages (Meta's free APIs), LinkedIn (your own profile), a Telegram
channel, a Discord channel and a Slack channel.

Each adapter follows the Bluesky/Mastodon contract: ``connected()``, ``publish(item, on_part)`` returning
``{"external_id", "url"}``, and ``metrics()``. Publishing still only happens through ``publish_item`` after the
owner approved the exact text.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable

import httpx

OnPart = Callable[[int, dict[str, Any]], None]


def _parts(item: dict[str, Any]) -> list[str]:
    return [item["text"], *(item.get("thread") or [])]


class _Base:
    platform = ""

    def __init__(self, settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    def _client(self, **kw) -> httpx.AsyncClient:
        return httpx.AsyncClient(**{"timeout": 30, **kw}, transport=self.transport)

    async def metrics(self, external_ids: list[str]) -> dict[str, dict[str, int]]:
        return {}  # these channels have no public engagement counts for posts

    async def inbox(self, limit: int) -> list[dict[str, Any]]:
        return []


class ThreadsAdapter(_Base):
    """Threads Graph API (free; needs a Threads user access token with threads_content_publish)."""

    platform = "threads"
    base = "https://graph.threads.net/v1.0"

    def connected(self) -> bool:
        return bool(self.settings.threads_access_token and self.settings.threads_user_id)

    async def publish(self, item: dict[str, Any], on_part: OnPart) -> dict[str, Any]:
        from .tools.social import AdapterError

        if item.get("media"):
            raise AdapterError("Threads needs images at a public web address; post this one as text only, or "
                               "publish the image from the Threads app")
        uid, token = self.settings.threads_user_id, self.settings.threads_access_token
        first: dict[str, Any] | None = None
        parent: str | None = None
        async with self._client() as client:
            for n, part in enumerate(_parts(item)):
                params = {"media_type": "TEXT", "text": part, "access_token": token}
                if parent:
                    params["reply_to_id"] = parent
                r = await client.post(f"{self.base}/{uid}/threads", params=params)
                if r.status_code != 200:
                    raise AdapterError(f"Threads refused the post ({r.status_code}): {r.text[:200]}")
                r = await client.post(f"{self.base}/{uid}/threads_publish",
                                      params={"creation_id": r.json()["id"], "access_token": token})
                if r.status_code != 200:
                    raise AdapterError(f"Threads could not publish ({r.status_code}): {r.text[:200]}")
                media_id = r.json()["id"]
                link = await client.get(f"{self.base}/{media_id}", params={"fields": "permalink", "access_token": token})
                ref = {"external_id": media_id, "url": link.json().get("permalink") if link.status_code == 200 else None}
                on_part(n, ref)
                first = first or ref
                parent = media_id
        assert first is not None
        return first

    async def metrics(self, external_ids: list[str]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        async with self._client() as client:
            for mid in external_ids[:40]:
                r = await client.get(f"{self.base}/{mid}/insights", params={
                    "metric": "likes,replies,reposts,quotes", "access_token": self.settings.threads_access_token})
                if r.status_code == 200:
                    vals = {m["name"]: (m.get("values") or [{}])[0].get("value", 0) for m in r.json().get("data", [])}
                    out[mid] = {"likes": vals.get("likes", 0), "reposts": vals.get("reposts", 0),
                                "replies": vals.get("replies", 0), "quotes": vals.get("quotes", 0)}
        return out


class TelegramChannelAdapter(_Base):
    """Posts to a Telegram channel where your bot is an admin (TELEGRAM_BOT_TOKEN + TELEGRAM_CHANNEL_ID)."""

    platform = "telegram"

    def connected(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.settings.telegram_channel_id)

    async def publish(self, item: dict[str, Any], on_part: OnPart) -> dict[str, Any]:
        from .tools.social import AdapterError, load_attachments

        api = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}"
        chat = self.settings.telegram_channel_id
        attachments = load_attachments(self.settings, item)
        first: dict[str, Any] | None = None
        async with self._client() as client:
            for n, part in enumerate(_parts(item)):
                if n == 0 and attachments and len(part) <= 1024:
                    meta, data = attachments[0]
                    r = await client.post(f"{api}/sendPhoto", data={"chat_id": chat, "caption": part},
                                          files={"photo": (meta["file"].rsplit("/", 1)[-1], data, meta["mime"])})
                else:
                    r = await client.post(f"{api}/sendMessage", json={"chat_id": chat, "text": part})
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                if r.status_code != 200 or not body.get("ok"):
                    raise AdapterError(f"Telegram refused the post: {body.get('description', r.status_code)}")
                mid = body["result"]["message_id"]
                url = f"https://t.me/{chat.lstrip('@')}/{mid}" if str(chat).startswith("@") else None
                ref = {"external_id": f"{chat}:{mid}", "url": url}
                on_part(n, ref)
                first = first or ref
        assert first is not None
        return first


class _WebhookChannel(_Base):
    """Discord / Slack channel through an incoming webhook URL."""

    host = ""
    setting = ""
    limit = 2000

    @property
    def url(self) -> str:
        return getattr(self.settings, self.setting) or ""

    def connected(self) -> bool:
        return self.url.startswith(self.host)

    def _body(self, part: str) -> dict[str, Any]:
        raise NotImplementedError

    async def publish(self, item: dict[str, Any], on_part: OnPart) -> dict[str, Any]:
        from .tools.social import AdapterError, load_attachments

        attachments = load_attachments(self.settings, item)
        first: dict[str, Any] | None = None
        async with self._client() as client:
            for n, part in enumerate(_parts(item)):
                if self.platform == "discord":
                    if n == 0 and attachments:
                        meta, data = attachments[0]
                        r = await client.post(self.url, params={"wait": "true"},
                                              data={"payload_json": json.dumps(self._body(part))},
                                              files={"files[0]": (meta["file"].rsplit("/", 1)[-1], data, meta["mime"])})
                    else:
                        r = await client.post(self.url, params={"wait": "true"}, json=self._body(part))
                else:
                    r = await client.post(self.url, json=self._body(part))
                if r.status_code >= 300:
                    raise AdapterError(f"{self.platform.title()} refused the post ({r.status_code}): {r.text[:150]}")
                try:
                    mid = str(r.json().get("id"))
                except ValueError:
                    mid = hashlib.sha256(f"{item['id']}:{n}".encode()).hexdigest()[:16]
                ref = {"external_id": mid, "url": None}
                on_part(n, ref)
                first = first or ref
        assert first is not None
        return first


class DiscordAdapter(_WebhookChannel):
    platform = "discord"
    host = "https://discord.com/api/webhooks/"
    setting = "discord_post_webhook_url"

    def _body(self, part: str) -> dict[str, Any]:
        return {"content": part[:2000], "allowed_mentions": {"parse": []}}  # never ping @everyone


class SlackAdapter(_WebhookChannel):
    platform = "slack"
    host = "https://hooks.slack.com/"
    setting = "slack_webhook_url"

    def _body(self, part: str) -> dict[str, Any]:
        return {"text": part[:3000]}


GRAPH = "https://graph.facebook.com/v23.0"


class FacebookPageAdapter(_Base):
    """A Facebook Page you manage, through your own Meta app (Standard Access needs no App Review for Pages
    you manage). Needs a Page access token with pages_manage_posts and the Page ID."""

    platform = "facebook"

    def connected(self) -> bool:
        return bool(self.settings.facebook_page_token and self.settings.facebook_page_id)

    def _p(self, **kw) -> dict[str, Any]:
        return {"access_token": self.settings.facebook_page_token, **kw}

    async def publish(self, item: dict[str, Any], on_part: OnPart) -> dict[str, Any]:
        from .tools.social import AdapterError, load_attachments

        page = self.settings.facebook_page_id
        attachments = load_attachments(self.settings, item)
        parts = _parts(item)
        async with self._client() as client:
            if attachments:
                meta, data = attachments[0]
                r = await client.post(f"{GRAPH}/{page}/photos", data=self._p(caption=parts[0]),
                                      files={"source": (meta["file"].rsplit("/", 1)[-1], data, meta["mime"])})
            else:
                r = await client.post(f"{GRAPH}/{page}/feed", data=self._p(message=parts[0]))
            if r.status_code != 200:
                raise AdapterError(f"Facebook refused the post ({r.status_code}): {_meta_error(r)}")
            body = r.json()
            post_id = body.get("post_id") or body["id"]
            first = {"external_id": post_id, "url": f"https://www.facebook.com/{post_id}"}
            on_part(0, first)
            for n, part in enumerate(parts[1:], start=1):  # the rest of a thread becomes comments
                r = await client.post(f"{GRAPH}/{post_id}/comments", data=self._p(message=part))
                if r.status_code != 200:
                    raise AdapterError(f"Facebook refused comment {n + 1} ({r.status_code}): {_meta_error(r)}")
                on_part(n, {"external_id": r.json()["id"], "url": None})
        return first

    async def metrics(self, external_ids: list[str]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        fields = "reactions.summary(true).limit(0),comments.summary(true).limit(0),shares"
        async with self._client() as client:
            for pid in external_ids[:40]:
                r = await client.get(f"{GRAPH}/{pid}", params=self._p(fields=fields))
                if r.status_code == 200:
                    b = r.json()
                    out[pid] = {"likes": (b.get("reactions") or {}).get("summary", {}).get("total_count", 0),
                                "replies": (b.get("comments") or {}).get("summary", {}).get("total_count", 0),
                                "reposts": (b.get("shares") or {}).get("count", 0)}
        return out


def _meta_error(r: httpx.Response) -> str:
    try:
        return r.json()["error"]["message"][:200]
    except (ValueError, KeyError, TypeError):
        return r.text[:200]


LINKEDIN = "https://api.linkedin.com"
_LI_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")
_HASHTAG = re.compile(r"(?<![\w#])#(\w+)")


def linkedin_commentary(text: str) -> str:
    """LinkedIn treats \\ | { } @ [ ] ( ) < > # * _ ~ as markup: escape them so the post is not cut off,
    and keep #words as real hashtags."""
    out, pos = [], 0
    for m in _HASHTAG.finditer(text):
        out.append(_LI_RESERVED.sub(r"\\\1", text[pos:m.start()]))
        out.append("{hashtag|\\#|" + _LI_RESERVED.sub(r"\\\1", m.group(1)) + "}")
        pos = m.end()
    out.append(_LI_RESERVED.sub(r"\\\1", text[pos:]))
    return "".join(out)


class LinkedInAdapter(_Base):
    """Your own LinkedIn profile through the self-serve "Share on LinkedIn" product (w_member_social, no
    partner review). Tokens last 60 days. Company Pages need LinkedIn's reviewed Community Management API."""

    platform = "linkedin"

    def connected(self) -> bool:
        return bool(self.settings.linkedin_access_token)

    def _h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.linkedin_access_token}",
                "LinkedIn-Version": self.settings.linkedin_api_version, "X-Restli-Protocol-Version": "2.0.0"}

    async def author(self, client: httpx.AsyncClient) -> str:
        from .tools.social import AdapterError

        if self.settings.linkedin_author_urn:
            return self.settings.linkedin_author_urn
        r = await client.get(f"{LINKEDIN}/v2/userinfo", headers=self._h())
        if r.status_code != 200 or not r.json().get("sub"):
            raise AdapterError("LinkedIn did not say who you are: add the openid and profile scopes to the token, "
                               "or set LINKEDIN_AUTHOR_URN (urn:li:person:…)")
        self.settings.linkedin_author_urn = f"urn:li:person:{r.json()['sub']}"
        return self.settings.linkedin_author_urn

    async def publish(self, item: dict[str, Any], on_part: OnPart) -> dict[str, Any]:
        from .tools.social import AdapterError, load_attachments

        text = "\n\n".join(_parts(item))
        if len(text) > 3000:
            raise AdapterError("LinkedIn posts are single posts of up to 3,000 characters; shorten this thread")
        attachments = load_attachments(self.settings, item)
        async with self._client() as client:
            author = await self.author(client)
            body: dict[str, Any] = {
                "author": author, "commentary": linkedin_commentary(text), "visibility": "PUBLIC",
                "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                                 "thirdPartyDistributionChannels": []},
                "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
            if attachments:
                meta, data = attachments[0]
                r = await client.post(f"{LINKEDIN}/rest/images", params={"action": "initializeUpload"},
                                      headers=self._h(), json={"initializeUploadRequest": {"owner": author}})
                if r.status_code != 200:
                    raise AdapterError(f"LinkedIn refused the image ({r.status_code}): {r.text[:200]}")
                up = r.json()["value"]
                put = await client.put(up["uploadUrl"], content=data, headers={
                    "Authorization": f"Bearer {self.settings.linkedin_access_token}", "Content-Type": meta["mime"]})
                if put.status_code >= 300:
                    raise AdapterError(f"LinkedIn image upload failed ({put.status_code})")
                body["content"] = {"media": {"id": up["image"]}}
            r = await client.post(f"{LINKEDIN}/rest/posts", headers=self._h(), json=body)
            if r.status_code == 426:
                raise AdapterError("LinkedIn no longer accepts API version "
                                   f"{self.settings.linkedin_api_version}; set LINKEDIN_API_VERSION to a recent YYYYMM")
            if r.status_code != 201:
                raise AdapterError(f"LinkedIn refused the post ({r.status_code}): {r.text[:200]}")
        urn = r.headers.get("x-restli-id", "")
        ref = {"external_id": urn, "url": f"https://www.linkedin.com/feed/update/{urn}/" if urn else None}
        on_part(0, ref)
        return ref



# ---------------------------------------------------------------- media platforms (images and video)
IG = "https://graph.instagram.com/v23.0"


async def _file_chunks(path: str, start: int = 0, length: int | None = None, size: int = 1 << 20):
    """Stream part of a file without loading it into memory."""
    left = length
    with open(path, "rb") as fh:
        fh.seek(start)
        while left is None or left > 0:
            chunk = fh.read(size if left is None else min(size, left))
            if not chunk:
                return
            if left is not None:
                left -= len(chunk)
            yield chunk


def _title(text: str, limit: int = 100) -> str:
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "Untitled")
    return first[:limit]


class InstagramAdapter(_Base):
    """Instagram professional (Business/Creator) account through the Instagram API with Instagram Login
    (your own Meta app; Standard Access needs no review for your own account). Videos become Reels and are
    uploaded straight from this computer. Instagram fetches images from a public address, so images go
    through your connected Facebook Page as an unpublished photo first."""

    platform = "instagram"
    poll_s = 3.0

    def connected(self) -> bool:
        return bool(self.settings.instagram_access_token and self.settings.instagram_user_id)

    def _p(self, **kw) -> dict[str, Any]:
        return {"access_token": self.settings.instagram_access_token, **kw}

    async def metrics(self, external_ids: list[str]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        async with self._client() as client:
            for mid in external_ids[:40]:
                r = await client.get(f"{IG}/{mid}",
                                     params=self._p(fields="like_count,comments_count"))
                if r.status_code == 200:
                    b = r.json()
                    out[mid] = {"likes": int(b.get("like_count") or 0), "replies": int(b.get("comments_count") or 0),
                                "reposts": 0}
        return out

    async def _image_url(self, client: httpx.AsyncClient, meta: dict[str, Any], data: bytes) -> str:
        from .tools.social import AdapterError

        s = self.settings
        if not (s.facebook_page_token and s.facebook_page_id):
            raise AdapterError("Instagram downloads images from a public address. Connect your Facebook Page too "
                               "(STARK hosts the image there as an unpublished photo), or post a video as a Reel.")
        r = await client.post(f"{GRAPH}/{s.facebook_page_id}/photos",
                              data={"access_token": s.facebook_page_token, "published": "false", "temporary": "true"},
                              files={"source": (meta["file"].rsplit("/", 1)[-1], data, meta["mime"])})
        if r.status_code != 200:
            raise AdapterError(f"Could not stage the image on your Facebook Page: {_meta_error(r)}")
        r = await client.get(f"{GRAPH}/{r.json()['id']}",
                             params={"fields": "images", "access_token": s.facebook_page_token})
        images = r.json().get("images") if r.status_code == 200 else None
        if not images:
            raise AdapterError("Facebook did not return an address for the staged image")
        return max(images, key=lambda i: i.get("width", 0))["source"]

    async def publish(self, item: dict[str, Any], on_part: OnPart) -> dict[str, Any]:
        import asyncio

        from .tools.social import AdapterError, load_attachments, load_video

        uid = self.settings.instagram_user_id
        caption = "\n\n".join(_parts(item))
        video = load_video(self.settings, item)
        images = load_attachments(self.settings, item)
        if not video and not images:
            raise AdapterError("Instagram posts need an image or a video")
        async with self._client(timeout=httpx.Timeout(300, connect=30)) as client:
            if video:
                r = await client.post(f"{IG}/{uid}/media", params=self._p(
                    media_type="REELS", upload_type="resumable", caption=caption))
                if r.status_code != 200:
                    raise AdapterError(f"Instagram refused the Reel ({r.status_code}): {_meta_error(r)}")
                container, uri = r.json()["id"], r.json().get("uri") or f"https://rupload.facebook.com/ig-api-upload/v23.0/{r.json()['id']}"
                up = await client.post(uri, content=_file_chunks(video["path"]), headers={
                    "Authorization": f"OAuth {self.settings.instagram_access_token}", "offset": "0",
                    "file_size": str(video["bytes"])})
                if up.status_code != 200:
                    raise AdapterError(f"Instagram video upload failed ({up.status_code}): {up.text[:200]}")
            else:
                meta, data = images[0]
                url = await self._image_url(client, meta, data)
                r = await client.post(f"{IG}/{uid}/media", params=self._p(image_url=url, caption=caption))
                if r.status_code != 200:
                    raise AdapterError(f"Instagram refused the image ({r.status_code}): {_meta_error(r)}")
                container = r.json()["id"]
            for _ in range(200):  # Instagram processes the media before it can be published
                st = await client.get(f"{IG}/{container}", params=self._p(fields="status_code"))
                code = st.json().get("status_code") if st.status_code == 200 else None
                if code in (None, "FINISHED", "PUBLISHED"):
                    break
                if code in ("ERROR", "EXPIRED"):
                    raise AdapterError(f"Instagram could not process the media ({code})")
                await asyncio.sleep(self.poll_s)
            r = await client.post(f"{IG}/{uid}/media_publish", params=self._p(creation_id=container))
            if r.status_code != 200:
                raise AdapterError(f"Instagram could not publish ({r.status_code}): {_meta_error(r)}")
            mid = r.json()["id"]
            link = await client.get(f"{IG}/{mid}", params=self._p(fields="permalink"))
        ref = {"external_id": mid, "url": link.json().get("permalink") if link.status_code == 200 else None}
        on_part(0, ref)
        return ref


class PinterestAdapter(_Base):
    """Pins on one of your boards (Pinterest API v5, your own app). With Trial access Pins are visible
    only to you; Pinterest grants Standard access on request."""

    platform = "pinterest"
    base = "https://api.pinterest.com/v5"

    def connected(self) -> bool:
        return bool(self.settings.pinterest_access_token and self.settings.pinterest_board_id)

    async def metrics(self, external_ids: list[str]) -> dict[str, dict[str, int]]:
        """Saves, comments and impressions over the last 90 days (Pinterest's longest window)."""
        from datetime import date, timedelta

        end = date.today()
        params = {"start_date": (end - timedelta(days=89)).isoformat(), "end_date": end.isoformat(),
                  "metric_types": "IMPRESSION,SAVE,PIN_CLICK,TOTAL_COMMENTS,TOTAL_REACTIONS", "app_types": "ALL"}
        out: dict[str, dict[str, int]] = {}
        async with self._client() as client:
            for pid in external_ids[:40]:
                r = await client.get(f"{self.base}/pins/{pid}/analytics", params=params,
                                     headers={"Authorization": f"Bearer {self.settings.pinterest_access_token}"})
                if r.status_code == 200:
                    t = ((r.json().get("all") or {}).get("lifetime_metrics")
                         or (r.json().get("all") or {}).get("summary_metrics") or {})
                    out[pid] = {"likes": int(t.get("TOTAL_REACTIONS") or 0), "reposts": int(t.get("SAVE") or 0),
                                "replies": int(t.get("TOTAL_COMMENTS") or 0), "views": int(t.get("IMPRESSION") or 0),
                                "clicks": int(t.get("PIN_CLICK") or 0)}
        return out

    async def publish(self, item: dict[str, Any], on_part: OnPart) -> dict[str, Any]:
        import base64

        from .tools.social import AdapterError, find_urls, load_attachments

        images = load_attachments(self.settings, item)
        if not images:
            raise AdapterError("A Pin needs an image (Pinterest video Pins are not supported yet)")
        meta, data = images[0]
        text = item["text"]
        spans = find_urls(text)
        body: dict[str, Any] = {
            "board_id": self.settings.pinterest_board_id, "title": _title(text), "description": text[:500],
            "media_source": {"source_type": "image_base64", "content_type": meta["mime"],
                             "data": base64.b64encode(data).decode()}}
        if meta.get("alt_text"):
            body["alt_text"] = meta["alt_text"][:500]
        if spans:
            body["link"] = text[spans[0][0]:spans[0][1]]
        async with self._client() as client:
            r = await client.post(f"{self.base}/pins", json=body,
                                  headers={"Authorization": f"Bearer {self.settings.pinterest_access_token}"})
        if r.status_code not in (200, 201):
            raise AdapterError(f"Pinterest refused the Pin ({r.status_code}): {r.text[:200]}")
        pid = r.json()["id"]
        ref = {"external_id": pid, "url": f"https://www.pinterest.com/pin/{pid}/"}
        on_part(0, ref)
        return ref


class _OAuthAdapter(_Base):
    """Platforms with short-lived access tokens: a refresh token (from Connect → sign in) buys new ones."""

    token_url = ""
    fields: tuple[str, str, str] = ("", "", "")  # client id, client secret, refresh token setting names
    persist: Callable[[str, str], None] | None = None  # saves a rotated refresh token

    def __init__(self, settings, transport=None) -> None:
        super().__init__(settings, transport)
        self._access: tuple[str, float] | None = None

    def connected(self) -> bool:
        cid, secret, refresh = (getattr(self.settings, f, "") for f in self.fields)
        return bool(refresh and ((cid and secret) or self.settings.connect_url))

    def _refresh_body(self) -> dict[str, str]:
        cid, secret, refresh = (getattr(self.settings, f) for f in self.fields)
        return {"client_id": cid, "client_secret": secret, "refresh_token": refresh, "grant_type": "refresh_token"}

    async def access_token(self, client: httpx.AsyncClient) -> str:
        import time

        from .tools.social import AdapterError

        if self._access and self._access[1] > time.time() + 60:
            return self._access[0]
        if getattr(self.settings, self.fields[1], ""):
            r = await client.post(self.token_url, data=self._refresh_body())
        else:  # signed in with Nexonic's app: STARK Connect holds the app secret
            r = await client.post(f"{self.settings.connect_url.rstrip('/')}/refresh/{self.platform}",
                                  json={"refresh_token": getattr(self.settings, self.fields[2])})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or not body.get("access_token"):
            raise AdapterError(f"{self.platform.title()} sign-in expired or was revoked; connect it again "
                               f"({body.get('error_description') or body.get('error') or r.status_code})")
        self._access = (body["access_token"], time.time() + float(body.get("expires_in") or 3600))
        new_refresh = body.get("refresh_token")
        if new_refresh and new_refresh != getattr(self.settings, self.fields[2]):
            setattr(self.settings, self.fields[2], new_refresh)
            if self.persist:
                self.persist(self.fields[2], new_refresh)
        return body["access_token"]


class TikTokAdapter(_OAuthAdapter):
    """TikTok Content Posting API (Direct Post, video uploaded from this computer). Until TikTok audits
    your app every post is private (SELF_ONLY); set TIKTOK_PRIVACY after the audit."""

    platform = "tiktok"
    token_url = "https://open.tiktokapis.com/v2/oauth/token/"
    fields = ("tiktok_client_key", "tiktok_client_secret", "tiktok_refresh_token")
    base = "https://open.tiktokapis.com/v2"

    def _refresh_body(self) -> dict[str, str]:
        b = super()._refresh_body()
        b["client_key"] = b.pop("client_id")
        return b

    @staticmethod
    def chunks(total: int) -> tuple[int, int]:
        """(chunk_size, count) within TikTok's rules: one chunk up to 64 MB, else 10 MB chunks with the
        remainder added to the last one."""
        if total <= 64 * 1024 * 1024:
            return total, 1
        size = 10 * 1024 * 1024
        return size, total // size

    async def publish(self, item: dict[str, Any], on_part: OnPart) -> dict[str, Any]:
        from .tools.social import AdapterError, load_video

        video = load_video(self.settings, item)
        if not video:
            raise AdapterError("TikTok posts need a video (MP4 or MOV)")
        total = video["bytes"]
        size, count = self.chunks(total)
        async with self._client(timeout=httpx.Timeout(600, connect=30)) as client:
            token = await self.access_token(client)
            r = await client.post(f"{self.base}/post/publish/video/init/", headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}, json={
                "post_info": {"title": item["text"][:2200], "privacy_level": self.settings.tiktok_privacy,
                              "disable_comment": False, "disable_duet": False, "disable_stitch": False},
                "source_info": {"source": "FILE_UPLOAD", "video_size": total, "chunk_size": size,
                                "total_chunk_count": count}})
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            err = body.get("error") or {}
            if r.status_code != 200 or err.get("code", "ok") != "ok":
                raise AdapterError(f"TikTok refused the post: {err.get('message') or r.status_code}")
            publish_id, upload_url = body["data"]["publish_id"], body["data"]["upload_url"]
            for n in range(count):
                start = n * size
                length = total - start if n == count - 1 else size
                up = await client.put(upload_url, content=_file_chunks(video["path"], start, length), headers={
                    "Content-Type": video["mime"], "Content-Length": str(length),
                    "Content-Range": f"bytes {start}-{start + length - 1}/{total}"})
                if up.status_code not in (200, 201, 206):
                    raise AdapterError(f"TikTok video upload failed at part {n + 1} ({up.status_code})")
        ref = {"external_id": publish_id, "url": None}
        on_part(0, ref)
        return ref


class YouTubeAdapter(_OAuthAdapter):
    """YouTube upload from this computer (resumable). Vertical clips under three minutes appear as Shorts.
    Uploads from Google-unaudited apps stay private; set YOUTUBE_PRIVACY after the audit."""

    platform = "youtube"
    token_url = "https://oauth2.googleapis.com/token"
    fields = ("youtube_client_id", "youtube_client_secret", "youtube_refresh_token")

    async def metrics(self, external_ids: list[str]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        async with self._client() as client:
            token = await self.access_token(client)
            for start in range(0, min(len(external_ids), 200), 50):  # 50 ids per request
                r = await client.get("https://www.googleapis.com/youtube/v3/videos",
                                     params={"part": "statistics", "id": ",".join(external_ids[start:start + 50])},
                                     headers={"Authorization": f"Bearer {token}"})
                for v in (r.json().get("items") or []) if r.status_code == 200 else []:
                    st = v.get("statistics") or {}
                    out[v["id"]] = {"likes": int(st.get("likeCount") or 0), "replies": int(st.get("commentCount") or 0),
                                    "reposts": 0, "views": int(st.get("viewCount") or 0)}
        return out

    async def publish(self, item: dict[str, Any], on_part: OnPart) -> dict[str, Any]:
        from .tools.social import HASHTAG_RE, AdapterError, load_video

        video = load_video(self.settings, item)
        if not video:
            raise AdapterError("YouTube needs a video (MP4 or MOV)")
        text = "\n\n".join(_parts(item))
        clean = text.replace("<", "").replace(">", "")
        meta = {"snippet": {"title": _title(clean), "description": clean[:5000], "categoryId": "22",
                            "tags": [t.lstrip("#") for t in HASHTAG_RE.findall(text)][:15]},
                "status": {"privacyStatus": self.settings.youtube_privacy, "selfDeclaredMadeForKids": False}}
        async with self._client(timeout=httpx.Timeout(900, connect=30)) as client:
            token = await self.access_token(client)
            r = await client.post("https://www.googleapis.com/upload/youtube/v3/videos",
                                  params={"uploadType": "resumable", "part": "snippet,status"}, json=meta, headers={
                                      "Authorization": f"Bearer {token}", "X-Upload-Content-Type": video["mime"],
                                      "X-Upload-Content-Length": str(video["bytes"])})
            if r.status_code != 200 or not r.headers.get("location"):
                raise AdapterError(f"YouTube refused the upload ({r.status_code}): {r.text[:200]}")
            up = await client.put(r.headers["location"], content=_file_chunks(video["path"]), headers={
                "Authorization": f"Bearer {token}", "Content-Type": video["mime"],
                "Content-Length": str(video["bytes"])})
            if up.status_code not in (200, 201):
                raise AdapterError(f"YouTube video upload failed ({up.status_code}): {up.text[:200]}")
        vid = up.json()["id"]
        ref = {"external_id": vid, "url": f"https://www.youtube.com/watch?v={vid}"}
        on_part(0, ref)
        return ref


def build(settings, transport=None) -> dict[str, Any]:
    return {"threads": ThreadsAdapter(settings, transport), "telegram": TelegramChannelAdapter(settings, transport),
            "discord": DiscordAdapter(settings, transport), "slack": SlackAdapter(settings, transport),
            "facebook": FacebookPageAdapter(settings, transport), "linkedin": LinkedInAdapter(settings, transport),
            "instagram": InstagramAdapter(settings, transport), "pinterest": PinterestAdapter(settings, transport),
            "tiktok": TikTokAdapter(settings, transport), "youtube": YouTubeAdapter(settings, transport)}
