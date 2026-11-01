"""Account health: checks every connected social account without posting anything.

A login that expired, a revoked token, a bot removed from its channel or a deleted webhook is found before a
scheduled post fails. Results are kept, shown on Home with a Reconnect button, and a change to "needs attention"
raises an ``account.unhealthy`` event (automations and webhooks can alert you).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select

from .core.db import ContentItem
from .core.observability import log

KEY = "account_health"
OK, WARN, BAD = "ok", "warning", "error"


async def _check(adapter) -> tuple[str, str]:
    """(status, message) for one connected adapter. Never posts."""
    p, s = adapter.platform, adapter.settings
    async with httpx.AsyncClient(timeout=15, transport=getattr(adapter, "transport", None)) as c:
        if p == "bluesky":
            adapter._session = None  # a fresh login proves the app password still works
            sess = await adapter._auth(c)
            return OK, f"Signed in as @{sess.get('handle', s.bluesky_handle)}"
        if p == "mastodon":
            r = await c.get(f"{s.mastodon_base_url.rstrip('/')}/api/v1/accounts/verify_credentials",
                            headers={"Authorization": f"Bearer {s.mastodon_access_token}"})
            if r.status_code == 200:
                return OK, f"Signed in as @{r.json().get('acct', '?')}"
            return BAD, f"The server rejected the access token ({r.status_code}). Create a new token and reconnect."
        if p == "threads":
            r = await c.get("https://graph.threads.net/v1.0/me",
                            params={"fields": "id,username", "access_token": s.threads_access_token})
            if r.status_code == 200:
                return OK, f"Connected as @{r.json().get('username', '?')}"
            return BAD, "Threads rejected the access token (it may have expired). Create a new one and reconnect."
        if p == "telegram":
            api = f"https://api.telegram.org/bot{s.telegram_bot_token}"
            me = await c.get(f"{api}/getMe")
            if me.status_code != 200 or not me.json().get("ok"):
                return BAD, "Telegram rejected the bot token. Create a new token with your bot settings and reconnect."
            bot_id = me.json()["result"]["id"]
            m = await c.get(f"{api}/getChatMember", params={"chat_id": s.telegram_channel_id, "user_id": bot_id})
            status = (m.json().get("result") or {}).get("status") if m.status_code == 200 else None
            if status in ("administrator", "creator"):
                return OK, f"Bot can post in {s.telegram_channel_id}"
            return BAD, f"The bot is not an admin of {s.telegram_channel_id} any more. Add it back as an admin."
        if p == "discord":
            r = await c.get(adapter.url)
            if r.status_code == 200:
                return OK, f"Webhook for #{r.json().get('name', 'channel')} is active"
            return BAD, "The Discord webhook was deleted or is invalid. Create a new one and reconnect."
        if p == "slack":
            return WARN, "Slack webhooks cannot be checked without posting; recent posts are used instead."
    return WARN, "No check available for this platform."


def _recent_failures(kernel, platform: str, days: int = 3) -> tuple[int, str]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with kernel.db.session() as s:
        rows = s.scalars(select(ContentItem).where(ContentItem.platform == platform, ContentItem.status == "failed",
                                                   ContentItem.updated_at >= since)).all()
        last = max(rows, key=lambda r: r.updated_at).error if rows else ""
    return len(rows), (last or "")[:200]


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    bad = [e["platform"] for e in entries if e["status"] == BAD]
    warn = [e["platform"] for e in entries if e["status"] == WARN]
    return {"overall": BAD if bad else WARN if warn else OK, "needs_attention": bad, "warnings": warn}


async def check_all(kernel, social) -> dict[str, Any]:
    previous = {e["platform"]: e for e in (kernel.db.get_setting(KEY) or {}).get("accounts", [])}
    entries = []
    for pid, adapter in social.adapters.items():
        if not adapter.connected():
            continue
        try:
            status, message = await asyncio.wait_for(_check(adapter), 30)
        except asyncio.TimeoutError:
            status, message = WARN, "The platform did not answer in time; will check again later."
        except httpx.HTTPError:
            status, message = WARN, "Could not reach the platform (network); will check again later."
        except Exception as exc:  # noqa: BLE001 - e.g. AdapterError for a rejected login
            status, message = BAD, str(exc)[:200]
        failed, last_error = _recent_failures(kernel, pid)
        if failed and status == OK:
            status, message = WARN, f"{message}. {failed} post(s) failed in the last 3 days: {last_error}"
        elif failed and status == WARN and pid == "slack":
            status, message = BAD, f"{failed} post(s) failed in the last 3 days: {last_error}"
        entry = {"platform": pid, "status": status, "message": message, "failed_recently": failed,
                 "checked_at": datetime.now(timezone.utc).isoformat()}
        entries.append(entry)
        was = (previous.get(pid) or {}).get("status")
        if status == BAD and was != BAD:
            kernel.bus.publish("account.unhealthy", {"platform": pid, "message": message})
    result = {"accounts": entries, **summarize(entries), "checked_at": datetime.now(timezone.utc).isoformat()}
    kernel.db.set_setting(KEY, result)
    return result


def cached(kernel) -> dict[str, Any]:
    return kernel.db.get_setting(KEY) or {"accounts": [], **summarize([]), "checked_at": None}


async def loop(kernel, social, every: float = 6 * 3600) -> None:
    await asyncio.sleep(90)  # let the app finish starting
    while True:
        try:
            await check_all(kernel, social)
        except Exception as exc:  # never let the loop die
            log.warning(f"account health error: {exc}")
        await asyncio.sleep(every)
