"""Reach and inbox features: UTM link tagging, announcing your own new videos / episodes / articles, inbox rules
(labels only, never automatic replies), Bluesky direct messages and media uploads for quote cards."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .core.observability import log
from .tools import social as social_tools

# ------------------------------------------------------------------ UTM tagging
SKIP_UTM_HOSTS = ("bsky.app", "mastodon.social", "x.com", "twitter.com", "youtube.com", "youtu.be", "t.me",
                  "discord.com", "threads.net", "linkedin.com", "instagram.com", "facebook.com", "tiktok.com")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "stark-os"


def add_utm(text: str, platform: str, campaign: str = "") -> str:
    """Add utm_source/medium/campaign to links that point at your own sites. Links to social networks and links
    that already carry UTM parameters are left alone."""

    def tag(m: re.Match) -> str:
        url = m.group(0)
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in SKIP_UTM_HOSTS):
            return url
        query = parse_qsl(parts.query, keep_blank_values=True)
        if any(k.startswith("utm_") for k, _ in query):
            return url
        query += [("utm_source", platform), ("utm_medium", "social"), ("utm_campaign", slug(campaign or "stark-os"))]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    return social_tools.URL_RE.sub(tag, text)


def tag_item(kernel, settings, item_id: str) -> dict[str, Any] | None:
    item = social_tools._item(kernel, item_id)
    if item is None:
        return None
    if item["status"] not in ("draft", "scheduled", "failed"):
        raise ValueError(f"This post is {item['status']}.")
    text = add_utm(item["text"], item["platform"], item.get("campaign") or item.get("category") or "")
    thread = [add_utm(t, item["platform"], item.get("campaign") or "") for t in item.get("thread") or []]
    if text == item["text"] and thread == (item.get("thread") or []):
        return social_tools.summarize(item)
    merged = {**item, "text": text, "thread": thread}
    # an edit: the policy check re-runs and any earlier approval of the old text is cancelled
    data = social_tools._update(kernel, item_id, text=text, thread=thread, check=social_tools._run_check(settings, merged),
                                review={}, approved_fp=None, auto_publish=False)
    return social_tools.summarize(data)


# ------------------------------------------------------------------ inbox rules (labels only)
RULES_KEY = "inbox_rules"


def get_rules(kernel) -> list[dict[str, Any]]:
    return kernel.db.get_setting(RULES_KEY, [])


def save_rules(kernel, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean = []
    for r in rules[:50]:
        words = [w.strip().lower() for w in str(r.get("contains", "")).split(",") if w.strip()]
        label = str(r.get("label", "")).strip()[:30]
        if words and label:
            clean.append({"contains": ", ".join(words), "label": label,
                          "priority": r.get("priority") if r.get("priority") in ("high", "normal", "low") else "normal"})
    kernel.db.set_setting(RULES_KEY, clean)
    return clean


def apply_rules(rules: list[dict[str, Any]], text: str) -> list[str]:
    low = text.lower()
    out = []
    for r in rules:
        if any(w in low for w in r["contains"].split(", ")) and r["label"] not in out:
            out.append(r["label"])
    return out


# ------------------------------------------------------------------ own channels → drafts
FEEDS_KEY = "own_feeds"
DEFAULT_TEMPLATES = {"youtube": "New video: {title} {link}", "podcast": "New episode: {title} {link}",
                     "blog": "New on the blog: {title} {link}"}


def youtube_feed(value: str) -> str:
    """A channel id (UC…) or a channel/feed URL → the channel's RSS feed URL."""
    value = value.strip()
    m = re.search(r"(UC[\w-]{22})", value)
    if m:
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
    return value


def get_feeds(kernel) -> list[dict[str, Any]]:
    return kernel.db.get_setting(FEEDS_KEY, [])


def save_feeds(kernel, feeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old = {f["url"]: f for f in get_feeds(kernel)}
    clean = []
    for f in feeds[:20]:
        kind = f.get("kind") if f.get("kind") in DEFAULT_TEMPLATES else "blog"
        url = youtube_feed(str(f.get("url", ""))) if kind == "youtube" else str(f.get("url", "")).strip()
        if not url.startswith("https://"):
            raise ValueError("Feed addresses must start with https://")
        platforms = [p for p in f.get("platforms") or ["bluesky", "mastodon"] if p in social_tools.PLATFORMS]
        template = str(f.get("template") or DEFAULT_TEMPLATES[kind])[:500]
        if "{link}" not in template:
            raise ValueError("The template needs {link}")
        clean.append({"url": url, "kind": kind, "platforms": platforms, "template": template,
                      "seen": old.get(url, {}).get("seen", []), "primed": old.get(url, {}).get("primed", False)})
    kernel.db.set_setting(FEEDS_KEY, clean)
    return clean


async def check_feeds(kernel, social, settings, fetch) -> dict[str, Any]:
    """New items in your own feeds become drafts (one per platform). The first check only remembers what is
    already there, so connecting a feed never floods the queue with old posts. `fetch(url)` returns feed items."""
    from . import hub

    feeds = get_feeds(kernel)
    made, errors = [], []
    for f in feeds:
        try:
            items = await fetch(f["url"])
        except Exception as exc:  # one broken feed must not stop the others
            errors.append(f"{f['url'][:60]}: {str(exc)[:120]}")
            continue
        keys = [hashlib.sha256((i.get("url") or i.get("title", "")).encode()).hexdigest()[:16] for i in items]
        if not f["primed"]:
            f["seen"], f["primed"] = keys[:200], True
            continue
        for i, k in zip(items, keys):
            if k in f["seen"]:
                continue
            f["seen"] = [k, *f["seen"]][:200]
            text = f["template"].replace("{title}", (i.get("title") or "").strip()).replace("{link}", i.get("url") or "")
            for platform in f["platforms"]:
                try:
                    body = add_utm(text, platform, f["kind"]) if settings.utm_enabled else text
                    d = hub.create_draft(kernel, social, settings, {"platform": platform, "text": body,
                                                                    "campaign": f"own-{f['kind']}"}, created_by="announcer")
                    made.append(d["id"])
                except hub.HubError as exc:
                    errors.append(str(exc))
    kernel.db.set_setting(FEEDS_KEY, feeds)
    return {"drafts": made, "errors": errors}


# ------------------------------------------------------------------ Bluesky direct messages
CHAT_PROXY = {"atproto-proxy": "did:web:api.bsky.chat#bsky_chat"}


async def bluesky_dms(social, limit: int = 30) -> list[dict[str, Any]]:
    """Recent Bluesky conversations (needs an app password created with "Allow access to your direct messages")."""
    adapter = social.adapter("bluesky")
    if adapter is None:
        raise ValueError("Connect Bluesky first")
    async with adapter._client() as client:
        sess = await adapter._auth(client)
        h = {"Authorization": f"Bearer {sess['accessJwt']}", **CHAT_PROXY}
        r = await client.get(f"{adapter.base}/xrpc/chat.bsky.convo.listConvos", params={"limit": limit}, headers=h)
        if r.status_code in (401, 403):
            raise ValueError("Bluesky did not allow access to messages. Create a new app password with "
                             "\"Allow access to your direct messages\" ticked and reconnect.")
        r.raise_for_status()
        me = sess["did"]
        out = []
        for c in r.json().get("convos", []):
            other = next((m for m in c.get("members", []) if m.get("did") != me), {})
            last = c.get("lastMessage") or {}
            out.append({"id": c["id"], "with": "@" + other.get("handle", "?"), "name": other.get("displayName") or "",
                        "unread": c.get("unreadCount", 0), "last_text": last.get("text", ""),
                        "last_at": last.get("sentAt"), "last_from_me": (last.get("sender") or {}).get("did") == me})
        return out


async def bluesky_dm_messages(social, convo_id: str, limit: int = 40) -> list[dict[str, Any]]:
    adapter = social.adapter("bluesky")
    if adapter is None:
        raise ValueError("Connect Bluesky first")
    async with adapter._client() as client:
        sess = await adapter._auth(client)
        h = {"Authorization": f"Bearer {sess['accessJwt']}", **CHAT_PROXY}
        r = await client.get(f"{adapter.base}/xrpc/chat.bsky.convo.getMessages",
                             params={"convoId": convo_id, "limit": limit}, headers=h)
        r.raise_for_status()
        return [{"id": m.get("id"), "text": m.get("text", ""), "at": m.get("sentAt"),
                 "from_me": (m.get("sender") or {}).get("did") == sess["did"]}
                for m in reversed(r.json().get("messages", []))]


async def bluesky_dm_send(social, convo_id: str, text: str) -> dict[str, Any]:
    """Send a reply the owner typed and clicked Send on (agents never send DMs)."""
    adapter = social.adapter("bluesky")
    if adapter is None:
        raise ValueError("Connect Bluesky first")
    text = text.strip()
    if not 1 <= len(text) <= 1000:
        raise ValueError("A message is 1-1000 characters")
    async with adapter._client() as client:
        sess = await adapter._auth(client)
        h = {"Authorization": f"Bearer {sess['accessJwt']}", **CHAT_PROXY}
        r = await client.post(f"{adapter.base}/xrpc/chat.bsky.convo.sendMessage", headers=h,
                              json={"convoId": convo_id, "message": {"text": text}})
        if r.status_code != 200:
            raise ValueError(f"Bluesky did not send the message ({r.status_code})")
        return {"id": r.json().get("id"), "at": r.json().get("sentAt")}


# ------------------------------------------------------------------ uploads (quote cards, carousels)
def save_upload(settings, data: bytes, name_hint: str = "card") -> dict[str, Any]:
    from .growth import IMAGE_DIR

    mime = social_tools._sniff_image(data)
    if mime not in ("image/png", "image/jpeg", "image/webp"):
        raise ValueError("Only PNG, JPEG or WebP images")
    if len(data) > social_tools.MAX_MEDIA_BYTES:
        raise ValueError("Image too large")
    if not settings.workspace_roots:
        raise ValueError("No workspace folder is configured")
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime]
    name = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{slug(name_hint)[:30]}-{hashlib.sha256(data).hexdigest()[:8]}{ext}"
    folder = settings.workspace_roots[0] / IMAGE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    log.info(f"saved {IMAGE_DIR}/{name}")
    return {"file": f"{IMAGE_DIR}/{name}", "name": name, "mime": mime, "bytes": len(data)}


async def fetch_feed_items(kernel, url: str) -> list[dict[str, Any]]:
    """Own-feed fetch through Autopilot's SSRF-safe reader (private addresses refused, redirects re-checked)."""
    async with httpx.AsyncClient(timeout=20) as client:
        return await kernel.autopilot.rss(client, url)
