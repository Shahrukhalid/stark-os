"""Growth insights: follower history, posting consistency, top fans, rising hashtags, competitor outliers,
the posting plan (content categories + weekly time slots) and Bluesky starter packs."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select

from .core.db import AccountStat, ContentItem, Mention, Watch, to_dict, utcnow
from .core.observability import log
from .tools import social as social_tools

PLAN_KEY = "posting_plan"
DEFAULT_PLAN: dict[str, Any] = {
    "categories": [{"name": "Tips", "share": 40, "color": "#22d3ee"},
                   {"name": "News", "share": 30, "color": "#a78bfa"},
                   {"name": "Promo", "share": 30, "color": "#f472b6"}],
    "slots": [{"weekday": d, "time": "10:00"} for d in range(5)],  # Monday-Friday, 10:00 local time
}
HASHTAG = re.compile(r"(?<![\w#])#([A-Za-z][\w]{1,49})")


class InsightError(ValueError):
    pass


# ------------------------------------------------------------------ posting plan
def get_plan(kernel) -> dict[str, Any]:
    return kernel.db.get_setting(PLAN_KEY, DEFAULT_PLAN)


def save_plan(kernel, plan: dict[str, Any]) -> dict[str, Any]:
    cats = []
    for c in plan.get("categories") or []:
        name = str(c.get("name", "")).strip()[:40]
        if name and name.lower() not in {x["name"].lower() for x in cats}:
            cats.append({"name": name, "share": max(0, min(100, int(c.get("share") or 0))),
                         "color": str(c.get("color") or "#22d3ee")[:9]})
    if len(cats) > 12:
        raise InsightError("Up to 12 categories")
    slots = []
    for sl in plan.get("slots") or []:
        wd, tm = int(sl.get("weekday", -1)), str(sl.get("time", ""))
        if not 0 <= wd <= 6 or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", tm):
            raise InsightError("Each time slot needs a weekday (0 = Monday) and a time like 09:30")
        if {"weekday": wd, "time": tm} not in slots:
            slots.append({"weekday": wd, "time": tm})
    if len(slots) > 70:
        raise InsightError("Up to 70 time slots a week")
    clean = {"categories": cats, "slots": sorted(slots, key=lambda x: (x["weekday"], x["time"]))}
    kernel.db.set_setting(PLAN_KEY, clean)
    return clean


def set_item_options(kernel, item_id: str, category: str | None = None,
                     reply_control: str | None = None) -> dict[str, Any] | None:
    item = social_tools._item(kernel, item_id)
    if item is None:
        return None
    fields: dict[str, Any] = {}
    if category is not None:
        fields["category"] = category.strip()[:40]
    if reply_control is not None:
        if reply_control not in social_tools.THREADGATES:
            raise InsightError("reply_control must be everyone, followers, following, mentioned or nobody")
        if item["platform"] != "bluesky" and reply_control != "everyone":
            raise InsightError("Reply controls are a Bluesky feature")
        fields["reply_control"] = None if reply_control == "everyone" else reply_control
    return social_tools.summarize(social_tools._update(kernel, item_id, **fields)) if fields else \
        social_tools.summarize(item)


# ------------------------------------------------------------------ followers & consistency
async def _counts(social, platform: str, transport=None) -> dict[str, int] | None:
    adapter = social.adapter(platform)
    if adapter is None:
        return None
    if platform == "bluesky":
        async with adapter._client() as client:
            sess = await adapter._auth(client)
            r = await client.get(f"{adapter.base}/xrpc/app.bsky.actor.getProfile", params={"actor": sess["did"]},
                                 headers={"Authorization": f"Bearer {sess['accessJwt']}"})
            r.raise_for_status()
            p = r.json()
            return {"followers": p.get("followersCount", 0), "following": p.get("followsCount", 0),
                    "posts": p.get("postsCount", 0)}
    async with adapter._client() as client:
        r = await client.get("/api/v1/accounts/verify_credentials")
        r.raise_for_status()
        p = r.json()
        return {"followers": p.get("followers_count", 0), "following": p.get("following_count", 0),
                "posts": p.get("statuses_count", 0)}


async def snapshot(kernel, social) -> int:
    """Store today's counts for every connected account (once a day; later calls update today's row)."""
    day = utcnow().date().isoformat()
    saved = 0
    for platform in ("bluesky", "mastodon"):
        try:
            c = await _counts(social, platform)
        except (httpx.HTTPError, social_tools.AdapterError, KeyError, ValueError) as exc:
            log.warning(f"follower snapshot {platform}: {exc.__class__.__name__}")
            continue
        if c is None:
            continue
        with kernel.db.session() as s:
            row = s.scalars(select(AccountStat).where(AccountStat.platform == platform,
                                                      AccountStat.day == day)).first()
            if row is None:
                s.add(AccountStat(platform=platform, day=day, **c))
            else:
                row.followers, row.following, row.posts = c["followers"], c["following"], c["posts"]
        saved += 1
    return saved


def growth_report(kernel, days: int = 90) -> dict[str, Any]:
    since = (utcnow() - timedelta(days=days)).date().isoformat()
    with kernel.db.session() as s:
        stats = [to_dict(r) for r in s.scalars(select(AccountStat).where(AccountStat.day >= since)
                                                .order_by(AccountStat.day)).all()]
        year_ago = utcnow() - timedelta(days=371)
        published = [r.published_at for r in s.scalars(select(ContentItem).where(
            ContentItem.status == "published", ContentItem.published_at >= year_ago)).all() if r.published_at]
    series: dict[str, list[dict[str, Any]]] = {}
    for r in stats:
        series.setdefault(r["platform"], []).append({k: r[k] for k in ("day", "followers", "following", "posts")})
    summary = {}
    for platform, rows in series.items():
        first, last = rows[0], rows[-1]
        week = next((x for x in reversed(rows) if x["day"] <= (utcnow() - timedelta(days=7)).date().isoformat()),
                    first)
        summary[platform] = {"followers": last["followers"], "change_total": last["followers"] - first["followers"],
                             "change_7d": last["followers"] - week["followers"], "since": first["day"]}
    per_day = Counter(p.date().isoformat() if isinstance(p, datetime) else str(p)[:10] for p in published)
    today = utcnow().date()
    streak = 0
    d = today
    while per_day.get(d.isoformat()):
        streak += 1
        d -= timedelta(days=1)
    return {"series": series, "summary": summary, "posted_days": dict(per_day), "streak": streak,
            "active_days_30": sum(1 for i in range(30) if per_day.get((today - timedelta(days=i)).isoformat()))}


# ------------------------------------------------------------------ top fans
async def top_fans(social, limit: int = 20) -> dict[str, Any]:
    """Who interacts with you most (likes, reposts, replies, mentions, quotes, follows) in recent notifications."""
    scores: dict[str, dict[str, Any]] = {}
    weights = {"like": 1, "repost": 2, "reblog": 2, "favourite": 1, "reply": 3, "mention": 3, "quote": 3,
               "follow": 1, "status": 0}
    errors = []

    def add(platform: str, who: str, kind: str) -> None:
        if not who:
            return
        k = f"{platform}:{who}"
        e = scores.setdefault(k, {"platform": platform, "account": who, "score": 0, "kinds": Counter()})
        e["score"] += weights.get(kind, 1)
        e["kinds"][kind] += 1

    for platform in ("bluesky", "mastodon"):
        adapter = social.adapter(platform)
        if adapter is None:
            continue
        try:
            async with adapter._client() as client:
                if platform == "bluesky":
                    sess = await adapter._auth(client)
                    r = await client.get(f"{adapter.base}/xrpc/app.bsky.notification.listNotifications",
                                         params={"limit": 100}, headers={"Authorization": f"Bearer {sess['accessJwt']}"})
                    r.raise_for_status()
                    for n in r.json().get("notifications", []):
                        add(platform, "@" + (n.get("author") or {}).get("handle", ""), n.get("reason", ""))
                else:
                    r = await client.get("/api/v1/notifications", params={"limit": 80})
                    r.raise_for_status()
                    for n in r.json():
                        add(platform, "@" + (n.get("account") or {}).get("acct", ""), n.get("type", ""))
        except (httpx.HTTPError, social_tools.AdapterError, ValueError) as exc:
            errors.append(f"{platform}: {exc.__class__.__name__}")
    fans = sorted(scores.values(), key=lambda e: -e["score"])[:limit]
    return {"fans": [{**f, "kinds": dict(f["kinds"])} for f in fans], "errors": errors}


# ------------------------------------------------------------------ trends & outliers
def rising_hashtags(kernel, now: datetime | None = None, limit: int = 15) -> list[dict[str, Any]]:
    """Hashtags in listening results: last 7 days compared with the 7 days before."""
    now = now or utcnow()
    with kernel.db.session() as s:
        rows = [(m.text, m.posted_at or m.created_at) for m in s.scalars(
            select(Mention).where(Mention.created_at >= now - timedelta(days=14))).all()]
    recent, before = Counter(), Counter()
    for text, at in rows:
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        bucket = recent if at >= now - timedelta(days=7) else before
        for tag in {t.lower() for t in HASHTAG.findall(text or "")}:
            bucket[tag] += 1
    out = [{"tag": t, "count": c, "before": before[t], "growth": c - before[t]} for t, c in recent.items() if c >= 2]
    return sorted(out, key=lambda x: (-x["growth"], -x["count"]))[:limit]


def outliers(kernel, factor: float = 3.0) -> list[dict[str, Any]]:
    """Competitor posts that did at least `factor` times better than that account's average: proven ideas."""
    out = []
    with kernel.db.session() as s:
        for w in s.scalars(select(Watch).where(Watch.kind == "account")).all():
            posts = [to_dict(m) for m in s.scalars(select(Mention).where(Mention.watch_id == w.id)).all()]
            if len(posts) < 4:
                continue
            sc = [p["likes"] + 2 * (p["reposts"] + p["replies"]) for p in posts]
            avg = sum(sc) / len(sc)
            for p, v in zip(posts, sc):
                if avg > 0 and v >= factor * avg:
                    out.append({"account": w.query, "text": p["text"][:300], "url": p["url"], "score": v,
                                "times_average": round(v / avg, 1)})
    return sorted(out, key=lambda x: -x["times_average"])[:20]


# ------------------------------------------------------------------ Bluesky starter packs
async def create_starter_pack(social, name: str, description: str, handles: list[str]) -> dict[str, Any]:
    """Create a public Bluesky starter pack (a list + a starter pack record) from up to 150 handles."""
    adapter = social.adapter("bluesky")
    if adapter is None:
        raise InsightError("Connect your Bluesky account first (Content → Your accounts)")
    name = name.strip()[:50]
    if not name:
        raise InsightError("Give the starter pack a name")
    handles = list(dict.fromkeys(h.strip().lstrip("@").lower() for h in handles if h.strip()))
    if not 1 <= len(handles) <= 150:
        raise InsightError("Add between 1 and 150 Bluesky handles")
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    async with adapter._client() as client:
        sess = await adapter._auth(client)
        h = {"Authorization": f"Bearer {sess['accessJwt']}"}
        dids, missing = [], []
        for i in range(0, len(handles), 25):
            r = await client.get(f"{adapter.base}/xrpc/app.bsky.actor.getProfiles",
                                 params=[("actors", x) for x in handles[i:i + 25]], headers=h)
            r.raise_for_status()
            found = {p["handle"].lower(): p["did"] for p in r.json().get("profiles", [])}
            for x in handles[i:i + 25]:
                (dids.append(found[x]) if x in found else missing.append(x))
        if not dids:
            raise InsightError("None of those handles were found on Bluesky")

        async def create(collection: str, record: dict[str, Any]) -> str:
            r = await client.post(f"{adapter.base}/xrpc/com.atproto.repo.createRecord", headers=h,
                                  json={"repo": sess["did"], "collection": collection, "record": record})
            if r.status_code != 200:
                raise social_tools.AdapterError(f"Bluesky refused the {collection.rsplit('.', 1)[-1]} ({r.status_code})")
            return r.json()["uri"]

        list_uri = await create("app.bsky.graph.list", {"$type": "app.bsky.graph.list", "name": name,
                                                        "purpose": "app.bsky.graph.defs#referencelist",
                                                        "description": description[:300], "createdAt": now})
        for did in dids:
            await create("app.bsky.graph.listitem", {"$type": "app.bsky.graph.listitem", "subject": did,
                                                     "list": list_uri, "createdAt": now})
        pack_uri = await create("app.bsky.graph.starterpack", {"$type": "app.bsky.graph.starterpack", "name": name,
                                                               "description": description[:300], "list": list_uri,
                                                               "createdAt": now})
    handle = adapter.settings.bluesky_handle.lstrip("@")
    return {"uri": pack_uri, "url": f"https://bsky.app/starter-pack/{handle}/{pack_uri.rsplit('/', 1)[-1]}",
            "added": len(dids), "not_found": missing}
