"""Growth features.

* **Listening**: follow keywords, hashtags and competitor accounts on Bluesky and Mastodon, triage what is found
  with the same rules as the inbox, and hand interesting posts to F.R.I.D.A.Y. for a reply draft.
* **Phone notifications**: Telegram messages with Approve / Reject and Publish / Discard buttons, a Discord
  webhook, and a daily digest. A button only ever acts on the exact text it showed.
* **Free AI images**: a generated image saved in the workspace so it can be attached to a post.

Nothing here posts publicly by itself: publishing still goes through ``social.publish_item`` with the
fingerprint of the content the owner saw.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select

from .core.db import Approval, ContentItem, Mention, Watch, to_dict, utcnow
from .core.observability import log
from .core.tool_registry import ApprovalText, Availability, Risk, Tool, ToolResult
from .tools import social as social_tools

KINDS = ("keyword", "hashtag", "account")
PUBLIC_BSKY = "https://public.api.bsky.app"
DEFAULT_MASTODON = "https://mastodon.social"
URGENT = {"escalate", "complaint", "question", "abuse"}


class GrowthError(ValueError):
    pass


def _dt(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def clean_watch(data: dict[str, Any]) -> dict[str, Any]:
    kind = data.get("kind")
    if kind not in KINDS:
        raise GrowthError("kind must be keyword, hashtag or account")
    q = str(data.get("query", "")).strip()
    if kind == "hashtag":
        q = q.lstrip("#")
        if not re.fullmatch(r"[\w]{1,100}", q):
            raise GrowthError("A hashtag is one word: letters, numbers and _ only.")
    elif kind == "account":
        q = q.lstrip("@")
        if not re.fullmatch(r"[\w.\-]+(@[\w.\-]+)?", q) or len(q) > 200:
            raise GrowthError("Enter a handle like name.bsky.social, or user@server for Mastodon.")
    elif not 2 <= len(q) <= 120:
        raise GrowthError("Keyword must be 2-120 characters.")
    platforms = [p for p in data.get("platforms") or ["bluesky", "mastodon"] if p in ("bluesky", "mastodon")]
    if not platforms:
        raise GrowthError("Pick Bluesky, Mastodon or both.")
    interval = int(data.get("interval_min") or 15)
    return {"kind": kind, "query": q, "platforms": platforms, "label": str(data.get("label") or "")[:120],
            "interval_min": max(5, min(interval, 1440)), "enabled": bool(data.get("enabled", True))}


# ------------------------------------------------------------------ listening
class Listening:
    def __init__(self, kernel, social: social_tools.Social, settings,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.kernel = kernel
        self.social = social
        self.settings = settings
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=20, transport=self.transport, headers={"User-Agent": "STARK-OS listening"})

    # -- storage
    def watches(self) -> list[dict[str, Any]]:
        with self.kernel.db.session() as s:
            rows = [to_dict(w) for w in s.scalars(select(Watch).order_by(Watch.created_at)).all()]
            counts: dict[str, int] = {}
            for wid in s.scalars(select(Mention.watch_id).where(Mention.status == "new")).all():
                counts[wid] = counts.get(wid, 0) + 1
        for r in rows:
            r["new"] = counts.get(r["id"], 0)
        return rows

    def add(self, data: dict[str, Any]) -> dict[str, Any]:
        clean = clean_watch(data)
        with self.kernel.db.session() as s:
            if len(s.scalars(select(Watch.id)).all()) >= 50:
                raise GrowthError("You can follow up to 50 keywords, hashtags and accounts.")
            row = Watch(**clean)
            s.add(row)
            s.flush()
            return to_dict(row)

    def update(self, watch_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        with self.kernel.db.session() as s:
            row = s.get(Watch, watch_id)
            if row is None:
                return None
            merged = clean_watch({**to_dict(row), **data})
            for k, v in merged.items():
                setattr(row, k, v)
            s.flush()
            return to_dict(row)

    def delete(self, watch_id: str) -> bool:
        with self.kernel.db.session() as s:
            row = s.get(Watch, watch_id)
            if row is None:
                return False
            s.delete(row)
            for m in s.scalars(select(Mention).where(Mention.watch_id == watch_id)).all():
                s.delete(m)
            return True

    def mentions(self, status: str = "new", watch_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.kernel.db.session() as s:
            q = select(Mention).order_by(Mention.posted_at.desc().nullslast(), Mention.created_at.desc()).limit(limit)
            if status != "all":
                q = q.where(Mention.status == status)
            if watch_id:
                q = q.where(Mention.watch_id == watch_id)
            return [to_dict(m) for m in s.scalars(q).all()]

    def set_status(self, mention_id: str, status: str) -> bool:
        if status not in ("new", "done", "dismissed"):
            raise GrowthError("bad status")
        with self.kernel.db.session() as s:
            row = s.get(Mention, mention_id)
            if row is None:
                return False
            row.status = status
            return True

    def competitors(self) -> list[dict[str, Any]]:
        """Per followed account: posts seen, average engagement and their best posts (what works for them)."""
        out = []
        with self.kernel.db.session() as s:
            for w in s.scalars(select(Watch).where(Watch.kind == "account")).all():
                posts = [to_dict(m) for m in s.scalars(select(Mention).where(Mention.watch_id == w.id)).all()]
                score = [p["likes"] + 2 * (p["reposts"] + p["replies"]) for p in posts]
                best = sorted(posts, key=lambda p: p["likes"] + 2 * (p["reposts"] + p["replies"]), reverse=True)[:3]
                out.append({"watch_id": w.id, "account": w.query, "label": w.label, "posts": len(posts),
                            "avg_score": round(sum(score) / len(score), 1) if score else 0,
                            "best": [{"text": b["text"][:200], "url": b["url"], "likes": b["likes"],
                                      "reposts": b["reposts"], "replies": b["replies"]} for b in best]})
        return out

    # -- fetching
    async def run_once(self, force: bool = False) -> dict[str, Any]:
        now = utcnow()
        with self.kernel.db.session() as s:
            due = [to_dict(w) for w in s.scalars(select(Watch).where(Watch.enabled.is_(True))).all()]
        if not force:
            due = [w for w in due if not w["last_run_at"]
                   or _dt(w["last_run_at"]) + timedelta(minutes=w["interval_min"]) <= now]
        found, errors = 0, []
        for w in due:
            posts: list[dict[str, Any]] = []
            err: list[str] = []
            for platform in w["platforms"]:
                try:
                    posts += [{**p, "platform": platform} for p in await self._fetch(platform, w)]
                except (httpx.HTTPError, social_tools.AdapterError, GrowthError, KeyError, ValueError) as exc:
                    err.append(f"{platform}: {str(exc)[:160] or exc.__class__.__name__}")
            new = self._store(w, posts)
            found += len(new)
            errors += [f"{w['query']} · {e}" for e in err]
            with self.kernel.db.session() as s:
                row = s.get(Watch, w["id"])
                if row is not None:
                    row.last_run_at = now
                    row.last_error = "; ".join(err) or None
            for m in new[:10]:
                self.kernel.bus.publish("listening.hit", {**m, "watch": w["query"], "kind": w["kind"]})
        return {"watches": len(due), "new": found, "errors": errors}

    def _store(self, w: dict[str, Any], posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        new = []
        own = {h.lower() for h in (self.settings.bluesky_handle,) if h}
        with self.kernel.db.session() as s:
            seen = set(s.scalars(select(Mention.external_id).where(Mention.watch_id == w["id"])).all())
            for p in posts:
                if p["external_id"] in seen or (w["kind"] != "account" and p["author"].lstrip("@").lower() in own):
                    continue
                seen.add(p["external_id"])
                cat = social_tools.triage(p["text"])["category"] if w["kind"] != "account" else "competitor"
                row = Mention(watch_id=w["id"], platform=p["platform"], external_id=p["external_id"][:300],
                              url=(p.get("url") or "")[:500] or None, author=p["author"][:200], text=p["text"][:5000],
                              posted_at=_dt(p.get("posted_at")), likes=p.get("likes", 0), reposts=p.get("reposts", 0),
                              replies=p.get("replies", 0), category=cat,
                              # competitors' posts are research, not a to-do list
                              status="done" if w["kind"] == "account" else "new")
                s.add(row)
                s.flush()
                new.append(to_dict(row))
        return new

    async def _fetch(self, platform: str, w: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._client() as client:
            if platform == "bluesky":
                return await self._bluesky(client, w)
            return await self._mastodon(client, w)

    async def _bluesky(self, client: httpx.AsyncClient, w: dict[str, Any]) -> list[dict[str, Any]]:
        if w["kind"] == "account":
            if "@" in w["query"]:
                return []  # a Mastodon address
            r = await client.get(f"{PUBLIC_BSKY}/xrpc/app.bsky.feed.getAuthorFeed",
                                 params={"actor": w["query"], "limit": 30, "filter": "posts_no_replies"})
            r.raise_for_status()
            return [_bsky_post(i["post"]) for i in r.json().get("feed", []) if "reason" not in i]
        q = f"#{w['query']}" if w["kind"] == "hashtag" else w["query"]
        params = {"q": q, "limit": 30, "sort": "latest"}
        adapter = self.social.adapter("bluesky")
        if adapter is not None:  # search needs a login on most servers; use the connected account when there is one
            sess = await adapter._auth(client)
            r = await client.get(f"{adapter.base}/xrpc/app.bsky.feed.searchPosts", params=params,
                                 headers={"Authorization": f"Bearer {sess['accessJwt']}"})
        else:
            r = await client.get(f"{PUBLIC_BSKY}/xrpc/app.bsky.feed.searchPosts", params=params)
        if r.status_code in (401, 403):
            raise GrowthError("Bluesky search needs a connected Bluesky account (Content page)")
        r.raise_for_status()
        return [_bsky_post(p) for p in r.json().get("posts", [])]

    async def _mastodon(self, client: httpx.AsyncClient, w: dict[str, Any]) -> list[dict[str, Any]]:
        base = (self.settings.mastodon_base_url or DEFAULT_MASTODON).rstrip("/")
        token = self.settings.mastodon_access_token if self.settings.mastodon_base_url else ""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if w["kind"] == "account":
            if "@" not in w["query"] and "." in w["query"]:
                return []  # a Bluesky handle
            r = await client.get(f"{base}/api/v1/accounts/lookup", params={"acct": w["query"]}, headers=headers)
            r.raise_for_status()
            acct = r.json()["id"]
            r = await client.get(f"{base}/api/v1/accounts/{acct}/statuses",
                                 params={"limit": 30, "exclude_replies": "true", "exclude_reblogs": "true"},
                                 headers=headers)
            r.raise_for_status()
            return [_masto_post(p) for p in r.json()]
        if w["kind"] == "keyword" and token:
            r = await client.get(f"{base}/api/v2/search", params={"q": w["query"], "type": "statuses", "limit": 30},
                                 headers=headers)
            r.raise_for_status()
            return [_masto_post(p) for p in r.json().get("statuses", [])]
        tag = re.sub(r"\W", "", w["query"])  # without a login Mastodon only offers hashtag timelines
        if not tag:
            return []
        r = await client.get(f"{base}/api/v1/timelines/tag/{quote(tag)}", params={"limit": 30}, headers=headers)
        r.raise_for_status()
        return [_masto_post(p) for p in r.json()]


def _bsky_post(p: dict[str, Any]) -> dict[str, Any]:
    handle = p.get("author", {}).get("handle", "?")
    rkey = p.get("uri", "").rsplit("/", 1)[-1]
    return {"external_id": p.get("uri", ""), "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
            "author": "@" + handle, "text": (p.get("record") or {}).get("text", ""),
            "posted_at": (p.get("record") or {}).get("createdAt") or p.get("indexedAt"),
            "likes": p.get("likeCount", 0), "reposts": p.get("repostCount", 0) + p.get("quoteCount", 0),
            "replies": p.get("replyCount", 0)}


def _masto_post(p: dict[str, Any]) -> dict[str, Any]:
    return {"external_id": str(p.get("uri") or p.get("id")), "url": p.get("url"),
            "author": "@" + (p.get("account") or {}).get("acct", "?"),
            "text": social_tools._strip_html(p.get("content") or ""), "posted_at": p.get("created_at"),
            "likes": p.get("favourites_count", 0), "reposts": p.get("reblogs_count", 0),
            "replies": p.get("replies_count", 0)}


# ------------------------------------------------------------------ phone notifications
class Notifier:
    """Telegram (with buttons) and Discord (webhook) notifications. Only the configured Telegram chat can press
    buttons; every press is re-checked against the current state and the exact text that was shown."""

    def __init__(self, kernel, social, settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.kernel = kernel
        self.social = social
        self.settings = settings
        self.transport = transport
        self._notified: set[str] = set()
        self._offset = 0
        self._last_digest: str | None = None

    @property
    def telegram(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.settings.telegram_chat_id)

    @property
    def discord(self) -> bool:
        return self.settings.discord_webhook_url.startswith("https://discord.com/api/webhooks/") or \
            self.settings.discord_webhook_url.startswith("https://discordapp.com/api/webhooks/")

    def status(self) -> dict[str, Any]:
        return {"telegram": self.telegram, "discord": self.discord, "digest_hour": self.settings.digest_hour}

    def _client(self, timeout: float = 20) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self.transport)

    def _tg(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/{method}"

    async def send(self, text: str, buttons: list[list[dict[str, str]]] | None = None) -> None:
        async with self._client() as client:
            if self.telegram:
                body: dict[str, Any] = {"chat_id": self.settings.telegram_chat_id, "text": text[:4000],
                                        "disable_web_page_preview": True}
                if buttons:
                    body["reply_markup"] = {"inline_keyboard": buttons}
                r = await client.post(self._tg("sendMessage"), json=body)
                if r.status_code != 200:
                    log.warning(f"telegram send failed ({r.status_code})")
            if self.discord:
                await client.post(self.settings.discord_webhook_url, json={"content": text[:1900],
                                                                          "allowed_mentions": {"parse": []}})

    # -- what gets sent
    def message_for(self, ev: dict[str, Any]) -> tuple[str, list[list[dict[str, str]]] | None] | None:
        t, d = ev["type"], ev["data"]
        if t == "approval.created":
            key = f"ap:{d['id']}"
            if key in self._notified:
                return None
            self._notified.add(key)
            text = (f"🛡 Approval needed ({d.get('agent_id', '?').upper()})\n\n{d.get('action', '')}\n\n"
                    f"Effects: {d.get('expected_effects', '')}")
            return text, [[{"text": "✅ Approve", "callback_data": f"ap:{d['id']}:a"},
                           {"text": "✖ Reject", "callback_data": f"ap:{d['id']}:r"}]]
        if t == "content.updated" and d.get("status") == "draft" and d.get("id"):
            key = f"cn:{d['id']}"
            if key in self._notified or (d.get("check") or {}).get("verdict") == "fail":
                return None
            self._notified.add(key)
            fp = social_tools.fingerprint(d)[:10]
            live = self.social.adapter(d["platform"]) is not None
            text = (f"📝 New {d['platform']} {d.get('kind', 'post')} draft by {str(d.get('created_by', '')).upper()}"
                    f"\n\n{d.get('text', '')}" + "".join(f"\n\n— {p}" for p in d.get("thread") or [])
                    + ("" if live else "\n\n(Not connected: publishing will be a simulation.)"))
            return text, [[{"text": "🚀 Publish now" if live else "🧪 Run simulation", "callback_data": f"cn:{d['id']}:p:{fp}"},
                           {"text": "🗑 Discard", "callback_data": f"cn:{d['id']}:d:{fp}"}]]
        if t == "listening.hit" and d.get("category") in URGENT:
            return (f"👂 {d.get('category', '').title()} on {d.get('platform')} ({d.get('watch')})\n"
                    f"{d.get('author')}: {d.get('text', '')[:600]}\n{d.get('url') or ''}"), None
        if t == "autopilot.alert":
            return f"⚠️ Autopilot · {d.get('campaign')}: {d.get('message')}", None
        if t == "estop" and d.get("engaged"):
            return "🛑 Emergency stop engaged. All work is cancelled and the queue is paused.", None
        return None

    async def handle_callback(self, cb: dict[str, Any]) -> str:
        chat = str(((cb.get("message") or {}).get("chat") or {}).get("id", ""))
        if chat != str(self.settings.telegram_chat_id):
            return "Not allowed."
        parts = str(cb.get("data", "")).split(":")
        k = self.kernel
        if parts[0] == "ap" and len(parts) == 3:
            status = "approved" if parts[2] == "a" else "rejected"
            if status == "approved" and k.perms.emergency_stop:
                return "Emergency stop is engaged: reset it first."
            out = k.approvals.decide(parts[1], status, decided_by="telegram")
            if out is None:
                return "Already decided or expired."
            k.obs.audit("user", "approval.decide", status, target=out["tool_id"], task_id=out["task_id"],
                        detail={"via": "telegram"})
            return "Approved ✅" if status == "approved" else "Rejected ✖"
        if parts[0] == "cn" and len(parts) == 4:
            item = social_tools._item(k, parts[1])
            if item is None:
                return "That post no longer exists."
            fp = social_tools.fingerprint(item)
            if not fp.startswith(parts[3]):
                return "The post changed since this message. Check it in the dashboard."
            if parts[2] == "d":
                if item["status"] in ("published", "publishing"):
                    return "Already published."
                if item.get("autopilot"):
                    k.autopilot.veto(item["id"])
                else:
                    social_tools._update(k, item["id"], status="rejected", auto_publish=False, approved_fp=None)
                k.obs.audit("user", "social.discard", "ok", target=item["id"], detail={"via": "telegram"})
                return "Discarded 🗑"
            if item["status"] not in ("draft", "scheduled", "failed"):
                return f"This post is {item['status']}."
            res = await social_tools.publish_item(k, self.social, self.settings, item["id"], approved_fp=fp,
                                                  actor="user")
            k.obs.audit("user", "social.publish", "ok" if res.ok else "error", target=item["id"],
                        detail={"summary": res.summary[:300], "simulated": res.simulated, "via": "telegram"})
            return ("Published 🚀" if not res.simulated else "Simulated 🧪") if res.ok else f"Not published: {res.summary[:150]}"
        return "Unknown button."

    async def poll_once(self) -> None:
        async with self._client(timeout=40) as client:
            r = await client.get(self._tg("getUpdates"), params={"timeout": 25, "offset": self._offset,
                                                                  "allowed_updates": json.dumps(["callback_query"])})
            if r.status_code != 200:
                await asyncio.sleep(10)
                return
            for u in r.json().get("result", []):
                self._offset = max(self._offset, u["update_id"] + 1)
                cb = u.get("callback_query")
                if not cb:
                    continue
                answer = await self.handle_callback(cb)
                await client.post(self._tg("answerCallbackQuery"), json={"callback_query_id": cb["id"], "text": answer})
                msg = cb.get("message") or {}
                if msg.get("message_id"):
                    await client.post(self._tg("editMessageReplyMarkup"),
                                      json={"chat_id": msg["chat"]["id"], "message_id": msg["message_id"],
                                            "reply_markup": {"inline_keyboard": [[{"text": answer, "callback_data": "noop"}]]}})

    def digest_text(self) -> str:
        k = self.kernel
        items = social_tools.list_queue(k, "all", None, None, 500)
        today = datetime.now().astimezone().date()
        drafts = sum(1 for i in items if i["status"] == "draft")
        sched = [i for i in items if i["status"] == "scheduled" and i["scheduled_for"]
                 and datetime.fromisoformat(i["scheduled_for"]).astimezone().date() == today]
        with k.db.session() as s:
            new_mentions = len(s.scalars(select(Mention.id).where(Mention.status == "new")).all())
            since = utcnow() - timedelta(days=1)
            published = len(s.scalars(select(ContentItem.id).where(ContentItem.status == "published",
                                                                   ContentItem.published_at >= since)).all())
            pending = len(s.scalars(select(Approval.id).where(Approval.status == "pending")).all())
        return (f"☀️ STARK OS daily digest\n\n• {drafts} draft(s) waiting for you\n• {len(sched)} post(s) scheduled today\n"
                f"• {published} published in the last 24 h\n• {new_mentions} new listening result(s)\n"
                + (f"• {pending} approval(s) pending\n" if pending else ""))

    async def maybe_digest(self) -> None:
        now = datetime.now().astimezone()
        key = now.date().isoformat()
        if now.hour == self.settings.digest_hour and self._last_digest != key:
            self._last_digest = key
            await self.send(self.digest_text())

    async def run(self) -> None:
        """Forward events to the phone and handle button presses. Runs until cancelled."""
        if not (self.telegram or self.discord):
            return
        q = self.kernel.bus.subscribe()

        async def forward() -> None:
            while True:
                ev = json.loads(await q.get())
                try:
                    msg = self.message_for(ev)
                    if msg:
                        await self.send(*msg)
                except Exception as exc:  # never let notifications break the API
                    log.warning(f"notify error: {exc}")

        async def buttons() -> None:
            while True:
                try:
                    await self.poll_once()
                except Exception as exc:
                    log.warning(f"telegram poll error: {exc}")
                    await asyncio.sleep(15)

        async def digest() -> None:
            while True:
                try:
                    await self.maybe_digest()
                except Exception as exc:
                    log.warning(f"digest error: {exc}")
                await asyncio.sleep(60)

        jobs = [asyncio.create_task(forward()), asyncio.create_task(digest())]
        if self.telegram:
            jobs.append(asyncio.create_task(buttons()))
        try:
            await asyncio.gather(*jobs)
        finally:
            for j in jobs:
                j.cancel()
            self.kernel.bus.unsubscribe(q)


# ------------------------------------------------------------------ free AI images
IMAGE_DIR = "media/generated"


async def generate_image(settings, prompt: str, width: int = 1024, height: int = 1024,
                         transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """Create an image with the free Pollinations service and save it in the workspace (media/generated/)."""
    if settings.image_generator != "pollinations":
        raise GrowthError("Image generation is off (set STARK_IMAGE_GENERATOR=pollinations to turn it on).")
    prompt = " ".join(prompt.split())[:600]
    if len(prompt) < 3:
        raise GrowthError("Describe the image in a few words.")
    if not settings.workspace_roots:
        raise GrowthError("No workspace folder is configured.")
    url = f"https://image.pollinations.ai/prompt/{quote(prompt)}"
    params = {"width": max(256, min(width, 1536)), "height": max(256, min(height, 1536)), "nologo": "true",
              "safe": "true", "seed": int(hashlib.sha256(prompt.encode()).hexdigest()[:6], 16)}
    async with httpx.AsyncClient(timeout=90, transport=transport, follow_redirects=True) as client:
        r = await client.get(url, params=params)
    if r.status_code != 200:
        raise GrowthError(f"The image service answered {r.status_code}. Try again in a minute.")
    data = r.content
    mime = social_tools._sniff_image(data)
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(mime or "")
    if not ext or len(data) > social_tools.MAX_MEDIA_BYTES:
        raise GrowthError("The image service did not return a usable image.")
    name = f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{hashlib.sha256(data).hexdigest()[:8]}{ext}"
    folder = settings.workspace_roots[0] / IMAGE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return {"file": f"{IMAGE_DIR}/{name}", "mime": mime, "bytes": len(data), "prompt": prompt}


class ImageInput(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=600, description="What the image shows. No real people, logos or brands.")
    width: int = Field(1024, ge=256, le=1536)
    height: int = Field(1024, ge=256, le=1536)


class GenerateImage(Tool):
    id = "media.generate_image"
    category = "media"
    description = ("Create an original illustration from a text prompt with a free image service and save it in "
                   "the workspace (media/generated/). Attach it to a draft with media[].file plus alt text. Never "
                   "depict real people, logos or trademarked characters.")
    Input = ImageInput
    risk = Risk.EXTERNAL  # the prompt leaves the computer
    timeout_s = 120.0

    def __init__(self, settings) -> None:
        self.settings = settings

    def availability(self, ctx=None) -> tuple[Availability, str]:
        if self.settings.image_generator != "pollinations":
            return Availability.UNAVAILABLE, "off (STARK_IMAGE_GENERATOR)"
        return Availability.IMPLEMENTED, "Pollinations (free, no key)"

    def describe(self, args: ImageInput, ctx) -> ApprovalText:
        return ApprovalText(action=f"Generate an image: {args.prompt[:200]}", target="image.pollinations.ai",
                            effects="Sends the prompt to a free image service and saves the image in media/generated/",
                            risks="The prompt text leaves your computer")

    async def run(self, args: ImageInput, ctx) -> ToolResult:
        try:
            out = await generate_image(self.settings, args.prompt, args.width, args.height)
        except (GrowthError, httpx.HTTPError) as exc:
            return ToolResult(False, f"Image not created: {exc}", error="image_failed")
        return ToolResult(True, f"Image saved as {out['file']} ({out['bytes'] // 1024} KB). Attach it with "
                                f"media=[{{file: '{out['file']}', alt_text: '…', description: '…'}}].", out)
