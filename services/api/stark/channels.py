"""More places to publish: Threads (Meta's free API), a Telegram channel, a Discord channel and a Slack channel.

Each adapter follows the Bluesky/Mastodon contract: ``connected()``, ``publish(item, on_part)`` returning
``{"external_id", "url"}``, and ``metrics()``. Publishing still only happens through ``publish_item`` after the
owner approved the exact text.
"""

from __future__ import annotations

import hashlib
import json
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


def build(settings, transport=None) -> dict[str, Any]:
    return {"threads": ThreadsAdapter(settings, transport), "telegram": TelegramChannelAdapter(settings, transport),
            "discord": DiscordAdapter(settings, transport), "slack": SlackAdapter(settings, transport)}
