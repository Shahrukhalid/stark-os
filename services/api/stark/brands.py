"""Brands: run several brands or clients from one STARK OS.

Each brand has its own voice, audience, guidelines, preferred hashtags, words it never uses and target platforms.
The active brand is given to every agent as authoritative context, its blocked words are enforced by the post
checker, and new content is tagged with it so queues and analytics can be filtered per brand.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select

from .core import db as dbm
from .core.db import Brand, ContentItem, Setting, to_dict, utcnow

ACTIVE_KEY = "active_brand"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
LIST_MAX = 30


class BrandError(ValueError):
    pass


def _clean_list(values: Any, limit: int = LIST_MAX, size: int = 80) -> list[str]:
    if isinstance(values, str):
        values = re.split(r"[,\n]", values)
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for v in values:
        v = str(v).strip()[:size]
        if v and v.lower() not in {x.lower() for x in out}:
            out.append(v)
    return out[:limit]


def clean(data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name", "")).strip()[:80]
    if not name:
        raise BrandError("A brand needs a name.")
    color = str(data.get("color") or "#22d3ee")
    return {
        "name": name,
        "voice": str(data.get("voice", ""))[:2000],
        "audience": str(data.get("audience", ""))[:2000],
        "guidelines": str(data.get("guidelines", ""))[:6000],
        "hashtags": [h if h.startswith("#") else f"#{h}" for h in _clean_list(data.get("hashtags"), size=60)],
        "blocked_terms": _clean_list(data.get("blocked_terms")),
        "platforms": [p for p in _clean_list(data.get("platforms")) if re.fullmatch(r"[a-z_]{2,24}", p)],
        "color": color if HEX.match(color) else "#22d3ee",
    }


def _sync_active(kernel) -> None:
    """Keep the in-memory copy (used by the post checker and new content) in line with the database."""
    b = active(kernel)
    dbm.ACTIVE_BRAND.update({"name": b["name"] if b else "", "blocked_terms": list(b["blocked_terms"]) if b else []})


def all_brands(kernel) -> list[dict[str, Any]]:
    with kernel.db.session() as s:
        brands = [to_dict(b) for b in s.scalars(select(Brand).order_by(Brand.name)).all()]
        counts: dict[str, int] = {}
        for name in s.scalars(select(ContentItem.brand)).all():
            counts[name or ""] = counts.get(name or "", 0) + 1
    current = active_id(kernel)
    for b in brands:
        b["active"] = b["id"] == current
        b["items"] = counts.get(b["name"], 0)
    return brands


def active_id(kernel) -> str:
    with kernel.db.session() as s:
        row = s.get(Setting, ACTIVE_KEY)
        return row.value if row else ""


def active(kernel) -> dict[str, Any] | None:
    bid = active_id(kernel)
    if not bid:
        return None
    with kernel.db.session() as s:
        b = s.get(Brand, bid)
        return to_dict(b) if b else None


def save(kernel, data: dict[str, Any], brand_id: str | None = None) -> dict[str, Any]:
    values = clean(data)
    with kernel.db.session() as s:
        clash = s.scalars(select(Brand).where(Brand.name == values["name"])).first()
        if clash is not None and clash.id != brand_id:
            raise BrandError("Another brand already has this name.")
        if brand_id:
            b = s.get(Brand, brand_id)
            if b is None:
                raise KeyError(brand_id)
            old = b.name
            for k, v in values.items():
                setattr(b, k, v)
            b.updated_at = utcnow()
            if old != b.name:  # keep existing content attached to the renamed brand
                for item in s.scalars(select(ContentItem).where(ContentItem.brand == old)).all():
                    item.brand = b.name
        else:
            b = Brand(**values)
            s.add(b)
        s.flush()
        out = to_dict(b)
    _sync_active(kernel)
    return out


def delete(kernel, brand_id: str) -> bool:
    with kernel.db.session() as s:
        b = s.get(Brand, brand_id)
        if b is None:
            return False
        s.delete(b)
        row = s.get(Setting, ACTIVE_KEY)
        if row is not None and row.value == brand_id:
            s.delete(row)
    _sync_active(kernel)
    return True


def activate(kernel, brand_id: str | None) -> dict[str, Any] | None:
    with kernel.db.session() as s:
        if brand_id and s.get(Brand, brand_id) is None:
            raise KeyError(brand_id)
        row = s.get(Setting, ACTIVE_KEY)
        if brand_id:
            if row is None:
                s.add(Setting(key=ACTIVE_KEY, value=brand_id))
            else:
                row.value = brand_id
        elif row is not None:
            s.delete(row)
    _sync_active(kernel)
    return active(kernel)


def load(kernel) -> None:
    """At start-up: restore the active brand."""
    _sync_active(kernel)


def prompt_section(kernel) -> str:
    """Authoritative brand context for the agents' system prompts ("" when no brand is active)."""
    b = active(kernel)
    if not b:
        return ""
    lines = [f"## Active brand: {b['name']} (write as this brand; authoritative)"]
    if b["voice"]:
        lines.append(f"- Voice and tone: {b['voice']}")
    if b["audience"]:
        lines.append(f"- Audience: {b['audience']}")
    if b["platforms"]:
        lines.append(f"- Platforms this brand uses: {', '.join(b['platforms'])}")
    if b["hashtags"]:
        lines.append(f"- Preferred hashtags (use only when relevant): {' '.join(b['hashtags'][:12])}")
    if b["blocked_terms"]:
        lines.append(f"- Never use these words or phrases: {', '.join(b['blocked_terms'])}")
    if b["guidelines"]:
        lines.append("- Brand guidelines:\n" + b["guidelines"][:3000])
    return "\n".join(lines)


def by_name(kernel, name: str) -> dict[str, Any] | None:
    if not name:
        return None
    with kernel.db.session() as s:
        b = s.scalars(select(Brand).where(Brand.name == name)).first()
        return to_dict(b) if b else None


def scope(kernel, requested: str | None) -> str | None:
    """Which brand a list should show: an explicit ?brand= ("all" = every brand), else the active brand."""
    if requested == "all":
        return None
    if requested:
        return requested
    b = active(kernel)
    return b["name"] if b else None


def brief(b: dict[str, Any] | None) -> str:
    """Short brand context for one-off writing prompts (Autopilot)."""
    if not b:
        return ""
    parts = [f"Brand: {b['name']}"]
    if b["voice"]:
        parts.append(f"Brand voice: {b['voice']}")
    if b["audience"]:
        parts.append(f"Brand audience: {b['audience']}")
    if b["blocked_terms"]:
        parts.append(f"Never use: {', '.join(b['blocked_terms'])}")
    if b["guidelines"]:
        parts.append("Brand guidelines: " + b["guidelines"][:1500])
    return "\n".join(parts)
