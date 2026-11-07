"""Keeps social logins alive so scheduled posts don't fail when a token runs out.

* Instagram and Threads long-lived tokens last 60 days. Meta lets you swap one for a fresh 60-day token once it
  is at least a day old, so every token saved in STARK AI is renewed about once a week.
* Pinterest access tokens last 30 days. When "Log in with Pinterest" returned a refresh token, a new access token
  is fetched through STARK Connect before the old one expires.
* LinkedIn tokens can't be renewed by ordinary apps; account health warns 10 days before the 60 days are up.

Only logins saved in the dashboard are renewed (values from .env can't be rewritten). Nothing is ever posted.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .core.observability import log, register_secret

RENEW_AFTER = {"instagram": timedelta(days=7), "threads": timedelta(days=7), "pinterest": timedelta(days=20)}
LINKEDIN_LIFETIME = timedelta(days=60)
LINKEDIN_WARN = timedelta(days=10)
KEY = "token_refresh"


def _when(value: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def token_age(store, pid: str) -> timedelta | None:
    """How long ago the current token was saved or renewed (None when unknown)."""
    entry = store.data.get(pid) or {}
    at = _when(entry.get("token_at") or entry.get("saved_at"))
    return datetime.now(timezone.utc) - at if at else None


def linkedin_days_left(store) -> int | None:
    age = token_age(store, "linkedin")
    return None if age is None else max(0, (LINKEDIN_LIFETIME - age).days)


def due(store, pid: str, now: datetime | None = None) -> bool:
    if pid not in store.data or store.from_env.get(pid):
        return False
    if pid == "pinterest" and not (store.data[pid].get("pinterest_refresh_token")
                                   and store.settings.connect_url):
        return False
    age = token_age(store, pid)
    return age is None or age >= RENEW_AFTER[pid]


async def renew(social, pid: str) -> str:
    """Fetch a fresh token for one platform and save it. Raises httpx.HTTPError or RuntimeError on failure."""
    s, store = social.settings, social.store
    async with httpx.AsyncClient(timeout=20, transport=social.transport) as c:
        if pid in ("instagram", "threads"):
            host, grant = (("graph.instagram.com", "ig_refresh_token") if pid == "instagram"
                           else ("graph.threads.net", "th_refresh_token"))
            r = await c.get(f"https://{host}/refresh_access_token",
                            params={"grant_type": grant, "access_token": getattr(s, f"{pid}_access_token")})
        elif pid == "pinterest":
            r = await c.post(f"{s.connect_url.rstrip('/')}/refresh/pinterest",
                             json={"refresh_token": store.data[pid]["pinterest_refresh_token"]})
        else:
            raise RuntimeError(f"{pid} tokens can't be renewed")
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    token = str(body.get("access_token") or "")
    if r.status_code != 200 or not token:
        err = body.get("error")
        msg = err.get("message") if isinstance(err, dict) else err
        raise RuntimeError(f"{pid} did not renew the token ({msg or r.status_code})")
    register_secret(token)
    field = f"{pid}_access_token"
    setattr(s, field, token)
    updates = {field: token, "token_at": datetime.now(timezone.utc).isoformat()}
    new_refresh = body.get("refresh_token")
    if pid == "pinterest" and new_refresh:
        register_secret(new_refresh)
        updates["pinterest_refresh_token"] = new_refresh
    store.update_many(pid, updates)
    return token


async def renew_due(kernel, social) -> dict[str, Any]:
    results: dict[str, str] = {}
    for pid in RENEW_AFTER:
        if not due(social.store, pid):
            continue
        try:
            await renew(social, pid)
            results[pid] = "renewed"
            kernel.obs.audit("system", "social.token_renewed", "ok", target=pid)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            results[pid] = f"failed: {str(exc)[:160]}"
            log.warning("token renewal failed", extra={"ctx": {"platform": pid, "error": str(exc)[:160]}})
    if results:
        kernel.db.set_setting(KEY, {"at": datetime.now(timezone.utc).isoformat(), "results": results})
    return results


async def loop(kernel, social) -> None:
    await asyncio.sleep(120)  # let startup finish first
    while True:
        try:
            await renew_due(kernel, social)
        except Exception:  # noqa: BLE001 - never stop the loop
            log.exception("token renewal loop error")
        await asyncio.sleep(6 * 3600)
