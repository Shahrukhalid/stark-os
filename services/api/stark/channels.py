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
        return httpx.AsyncClient(timeout=30, transport=self.transport, **kw)

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


def build(settings, transport=None) -> dict[str, Any]:
    return {"threads": ThreadsAdapter(settings, transport), "telegram": TelegramChannelAdapter(settings, transport),
            "discord": DiscordAdapter(settings, transport), "slack": SlackAdapter(settings, transport),
            "facebook": FacebookPageAdapter(settings, transport), "linkedin": LinkedInAdapter(settings, transport)}
