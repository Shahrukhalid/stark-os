"""Workflow features: drafts from outside tools, bulk CSV import, evergreen recycling, the Library (templates,
hashtag groups, signatures), outgoing webhooks for automation apps, and the analytics report.

Every path here creates drafts or schedules without auto-publish: publishing still needs the owner's approval
of the exact text, as everywhere else in STARK OS.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy import select

from .core.db import ContentItem, Snippet, to_dict, utcnow
from .core.observability import log
from .core.tool_registry import Risk, Tool, ToolResult
from .tools import social as social_tools

SNIPPET_KINDS = ("template", "hashtags", "signature", "reply")
MAX_IMPORT_ROWS = 500


class HubError(ValueError):
    pass


# ------------------------------------------------------------------ drafts
def create_draft(kernel, social, settings, data: dict[str, Any], created_by: str = "user") -> dict[str, Any]:
    """Save a draft exactly like the social.draft tool does (policy check included)."""
    platform = str(data.get("platform", "")).lower()
    if platform not in social_tools.PLATFORMS:
        raise HubError(f"unknown platform {platform!r}")
    text = str(data.get("text") or "").strip()
    if not 1 <= len(text) <= 10_000:
        raise HubError("text must be 1-10000 characters")
    thread = [str(t) for t in (data.get("thread") or [])][:25]
    item = {"platform": platform, "kind": "thread" if thread else str(data.get("kind") or "post"), "text": text,
            "thread": thread, "media": [], "reply_to": data.get("reply_to"), "sponsored": bool(data.get("sponsored")),
            "campaign": str(data.get("campaign") or "")[:120], "category": str(data.get("category") or "")[:40]}
    rc = data.get("reply_control")
    if rc and rc != "everyone":
        if rc not in social_tools.THREADGATES or platform != "bluesky":
            raise HubError("reply_control (everyone, followers, following, mentioned, nobody) is for Bluesky posts")
        item["reply_control"] = rc
    if settings.utm_enabled:
        from .reach import add_utm

        item["text"] = add_utm(item["text"], platform, item["campaign"] or item["category"])
        item["thread"] = [add_utm(t, platform, item["campaign"] or item["category"]) for t in item["thread"]]
    if item["kind"] not in ("post", "reply", "thread", "video"):
        raise HubError("kind must be post, reply, thread or video")
    check = social_tools._run_check(settings, item)
    with kernel.db.session() as s:
        row = ContentItem(**item, check=check, created_by=created_by, simulated=social.adapter(platform) is None,
                          paused=social_tools.queue_paused(kernel))
        s.add(row)
        s.flush()
        out = to_dict(row)
    kernel.bus.publish("content.updated", out)
    return social_tools.summarize(out)


def _parse_when(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        raise HubError(f"bad date {raw!r}: use 2026-11-05 09:30 (UTC) or ISO 8601 with an offset") from None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def import_csv(kernel, social, settings, text: str) -> dict[str, Any]:
    """CSV with a header row: platform, text, and optional scheduled_for, campaign, thread (parts split by ||).
    Rows with a time become scheduled (not auto-published); rows that fail the policy check stay drafts."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    cols = {c.strip().lower() for c in reader.fieldnames or []}
    if not {"platform", "text"} <= cols:
        raise HubError("The CSV needs a header row with at least: platform, text")
    created, scheduled, errors = [], 0, []
    now = utcnow()
    for n, raw in enumerate(reader, start=2):
        if len(created) >= MAX_IMPORT_ROWS:
            errors.append(f"stopped after {MAX_IMPORT_ROWS} rows")
            break
        row = {str(k).strip().lower(): (v or "").strip() for k, v in raw.items() if k}
        if not row.get("text"):
            continue
        try:
            when = _parse_when(row.get("scheduled_for", ""))
            item = create_draft(kernel, social, settings, {
                "platform": row.get("platform"), "text": row["text"], "campaign": row.get("campaign", ""),
                "thread": [p.strip() for p in row.get("thread", "").split("||") if p.strip()]}, created_by="import")
        except HubError as exc:
            errors.append(f"line {n}: {exc}")
            continue
        created.append(item["id"])
        if when and when > now and item["check"]["verdict"] != "fail":
            social_tools._update(kernel, item["id"], status="scheduled", scheduled_for=when, auto_publish=False)
            scheduled += 1
        elif when:
            errors.append(f"line {n}: kept as a draft ({'time is in the past' if when <= now else 'check failed'})")
    return {"created": len(created), "scheduled": scheduled, "errors": errors[:50], "ids": created}


# ------------------------------------------------------------------ evergreen
def set_evergreen(kernel, item_id: str, days: int | None) -> dict[str, Any] | None:
    if days is not None and not 7 <= days <= 365:
        raise HubError("Recycle every 7 to 365 days")
    item = social_tools._item(kernel, item_id)
    if item is None:
        return None
    return social_tools.summarize(social_tools._update(kernel, item_id, evergreen_days=days))


def recycle_due(kernel, social, settings, now: datetime | None = None) -> list[str]:
    """Published evergreen posts whose time has come return as fresh drafts (the owner approves them again).
    The evergreen setting moves to the new copy, so each post recycles once per period."""
    now = now or utcnow()
    with kernel.db.session() as s:
        rows = [to_dict(r) for r in s.scalars(select(ContentItem).where(
            ContentItem.status == "published", ContentItem.evergreen_days.is_not(None),
            ContentItem.simulated.is_(False))).all()]
    made = []
    for r in rows:
        pub = datetime.fromisoformat(r["published_at"]) if r["published_at"] else None
        if pub is None or pub + timedelta(days=r["evergreen_days"]) > now:
            continue
        copy = create_draft(kernel, social, settings, {**r, "thread": r["thread"]}, created_by="recycler")
        social_tools._update(kernel, copy["id"], evergreen_days=r["evergreen_days"], recycled_from=r["id"])
        social_tools._update(kernel, r["id"], evergreen_days=None)
        made.append(copy["id"])
    return made


# ------------------------------------------------------------------ library
def clean_snippet(data: dict[str, Any]) -> dict[str, Any]:
    kind = data.get("kind")
    if kind not in SNIPPET_KINDS:
        raise HubError("kind must be template, hashtags, signature or reply")
    name = str(data.get("name") or "").strip()[:120]
    body = str(data.get("body") or "").strip()
    if not name or not body or len(body) > 5000:
        raise HubError("A snippet needs a name and 1-5000 characters of text")
    if kind == "hashtags":
        tags = [t if t.startswith("#") else f"#{t}" for t in body.replace(",", " ").split() if t.strip("#")]
        body = " ".join(dict.fromkeys(tags))
    platforms = [p for p in data.get("platforms") or [] if p in social_tools.PLATFORMS]
    return {"kind": kind, "name": name, "body": body, "platforms": platforms}


def snippets(kernel) -> list[dict[str, Any]]:
    with kernel.db.session() as s:
        return [to_dict(x) for x in s.scalars(select(Snippet).order_by(Snippet.kind, Snippet.name)).all()]


def add_snippet(kernel, data: dict[str, Any]) -> dict[str, Any]:
    clean = clean_snippet(data)
    with kernel.db.session() as s:
        if len(s.scalars(select(Snippet.id)).all()) >= 300:
            raise HubError("The library holds up to 300 snippets")
        row = Snippet(**clean)
        s.add(row)
        s.flush()
        return to_dict(row)


def delete_snippet(kernel, snippet_id: str) -> bool:
    with kernel.db.session() as s:
        row = s.get(Snippet, snippet_id)
        if row is None:
            return False
        s.delete(row)
        return True


class LibraryInput(BaseModel):
    kind: str | None = None


class LibraryList(Tool):
    id = "library.list"
    category = "social"
    description = ("The owner's Library: post templates, hashtag groups and signatures. Use them when writing posts "
                   "(fill the template, add the matching hashtag group or signature) unless asked otherwise.")
    Input = LibraryInput
    risk = Risk.READ

    async def run(self, args: LibraryInput, ctx) -> ToolResult:
        items = [x for x in snippets(ctx.kernel) if not args.kind or x["kind"] == args.kind]
        rows = [{"kind": x["kind"], "name": x["name"], "body": x["body"], "platforms": x["platforms"] or "all"}
                for x in items]
        return ToolResult(True, f"{len(rows)} snippet(s) in the Library", {"snippets": rows})


# ------------------------------------------------------------------ outgoing webhooks
WEBHOOK_EVENTS = {"content.updated", "listening.hit", "approval.created", "autopilot.alert", "estop"}


def webhook_payload(ev: dict[str, Any]) -> dict[str, Any] | None:
    """What automation apps (n8n, Make, Zapier…) receive. Only a few meaningful events, with stable names."""
    t, d = ev["type"], ev["data"]
    if t not in WEBHOOK_EVENTS:
        return None
    if t == "content.updated":
        status = d.get("status")
        if status not in ("draft", "scheduled", "published", "failed"):
            return None
        name = {"draft": "post.drafted", "scheduled": "post.scheduled", "published": "post.published",
                "failed": "post.failed"}[status]
        data = {k: d.get(k) for k in ("id", "platform", "kind", "text", "campaign", "scheduled_for", "external_url",
                                       "simulated", "created_by")}
    elif t == "listening.hit":
        name, data = "mention.found", {k: d.get(k) for k in ("platform", "author", "text", "url", "category", "watch")}
    elif t == "approval.created":
        name, data = "approval.needed", {k: d.get(k) for k in ("id", "agent_id", "tool_id", "action")}
    elif t == "autopilot.alert":
        name, data = "autopilot.alert", dict(d)
    else:
        name, data = "estop", dict(d)
    return {"event": name, "at": ev.get("ts"), "data": data}


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class Webhooks:
    def __init__(self, kernel, settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.kernel = kernel
        self.settings = settings
        self.transport = transport
        self._seen: set[tuple[str, str]] = set()

    @property
    def urls(self) -> list[str]:
        return [u for u in self.settings.webhook_urls if u.startswith("https://")
                or (self.settings.allow_private_fetch and u.startswith("http://"))]

    def status(self) -> dict[str, Any]:
        return {"count": len(self.urls), "signed": bool(self.settings.webhook_secret),
                "events": ["post.drafted", "post.scheduled", "post.published", "post.failed", "mention.found",
                           "approval.needed", "autopilot.alert", "estop"]}

    def payload_for(self, ev: dict[str, Any]) -> dict[str, Any] | None:
        p = webhook_payload(ev)
        if p is None:
            return None
        key = (p["event"], str(p["data"].get("id") or json.dumps(p["data"], sort_keys=True, default=str)))
        if key in self._seen:  # one call per post per state, even though the queue publishes many updates
            return None
        self._seen.add(key)
        return p

    async def send(self, payload: dict[str, Any]) -> int:
        body = json.dumps(payload, default=str).encode()
        headers = {"content-type": "application/json", "user-agent": "STARK-OS-webhook"}
        if self.settings.webhook_secret:
            headers["x-stark-signature"] = sign(self.settings.webhook_secret, body)
        ok = 0
        async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
            for url in self.urls:
                try:
                    r = await client.post(url, content=body, headers=headers)
                    ok += r.status_code < 400
                except httpx.HTTPError as exc:
                    log.warning(f"webhook {url[:40]}… failed: {exc.__class__.__name__}")
        return ok

    async def run(self) -> None:
        if not self.urls:
            return
        q = self.kernel.bus.subscribe()
        try:
            while True:
                ev = json.loads(await q.get())
                p = self.payload_for(ev)
                if p:
                    await self.send(p)
        finally:
            self.kernel.bus.unsubscribe(q)


async def recycler_loop(kernel, social, settings, every_s: float = 3600.0) -> None:
    while True:
        try:
            made = recycle_due(kernel, social, settings)
            if made:
                log.info(f"evergreen: {len(made)} post(s) back as drafts")
        except Exception as exc:
            log.warning(f"evergreen error: {exc}")
        await asyncio.sleep(every_s)
