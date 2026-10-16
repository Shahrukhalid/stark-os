"""Layered memory with namespace access control.

Layers: working (chat turns, stored in ``turns``), episodic, semantic, agent,
project, preference, procedural. Namespaces decide who may read/write:

    agent:<id>           private to that agent
    user:preferences     explicit, consent-based personal preferences
    shared:knowledge     facts and documents any permitted agent may use
    shared:project:<id>  collaboration context for one project/task tree
    procedures           reusable workflows

Retrieval is lexical (term overlap + recency). Vector retrieval (pgvector) is
planned; see docs/DECISIONS.md.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, or_, select

from .db import Database, Memory, to_dict, utcnow
from .events import EventBus

if TYPE_CHECKING:
    from .agent_registry import AgentConfig

LAYERS = {"episodic", "semantic", "agent", "project", "preference", "procedural"}
_STOP = set("the a an and or of to in on for is are be with that this it as at by from i me my you your we".split())
_WORD = re.compile(r"[a-z0-9][a-z0-9_\-]+")


class MemoryAccessError(PermissionError):
    pass


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


def _hash(namespace: str, content: str) -> str:
    norm = " ".join(content.lower().split())
    return hashlib.sha256(f"{namespace}\n{norm}".encode()).hexdigest()


def can_access(patterns: list[str], namespace: str) -> bool:
    return any(fnmatch.fnmatchcase(namespace, p) for p in patterns)


class MemoryService:
    def __init__(self, db: Database, bus: EventBus, enabled_default: bool = True) -> None:
        self.db = db
        self.bus = bus
        self._enabled_default = enabled_default

    @property
    def enabled(self) -> bool:
        return bool(self.db.get_setting("memory_enabled", self._enabled_default))

    def set_enabled(self, value: bool) -> None:
        self.db.set_setting("memory_enabled", value)

    # ---------- agent-facing (access controlled) ----------
    def save(self, *, actor: "AgentConfig | None", namespace: str, layer: str, content: str,
             source: str = "", consent: bool = False, tags: list[str] | None = None,
             ttl_days: int | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise MemoryAccessError("memory is disabled by the user")
        if layer not in LAYERS:
            raise ValueError(f"unknown memory layer '{layer}'")
        if actor is not None and not can_access(actor.memory.write_namespaces, namespace):
            raise MemoryAccessError(f"{actor.id} may not write to {namespace}")
        if namespace == "user:preferences" and not consent:
            raise MemoryAccessError("user preferences require explicit consent")
        content = content.strip()
        if not content:
            raise ValueError("empty memory")
        digest = _hash(namespace, content)
        expires = utcnow() + timedelta(days=ttl_days) if ttl_days else None
        with self.db.session() as s:
            existing = s.scalar(select(Memory).where(Memory.namespace == namespace, Memory.content_hash == digest))
            if existing:  # deduplicate: refresh instead of storing twice
                existing.updated_at = utcnow()
                existing.expires_at = expires  # a permanent save makes the memory permanent again
                data = to_dict(existing)
                data["deduplicated"] = True
                return data
            row = Memory(namespace=namespace, layer=layer, content=content, content_hash=digest,
                         source=source, created_by=actor.id if actor else "user", consent=consent,
                         tags=tags or [], expires_at=expires)
            s.add(row)
            s.flush()
            data = to_dict(row)
        self.bus.publish("memory.created", {"id": data["id"], "namespace": namespace, "layer": layer,
                                            "created_by": data["created_by"]})
        return data

    def search(self, *, actor: "AgentConfig | None", query: str, namespaces: list[str] | None = None,
               layers: list[str] | None = None, limit: int = 8) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        self.purge_expired()
        with self.db.session() as s:
            stmt = select(Memory)
            if layers:
                stmt = stmt.where(Memory.layer.in_(layers))
            rows = s.scalars(stmt).all()
        allowed = actor.memory.read_namespaces if actor else ["*"]
        q_tokens = set(_tokens(query))
        scored = []
        for row in rows:
            if not can_access(allowed, row.namespace):
                continue
            if namespaces and not any(fnmatch.fnmatchcase(row.namespace, n) for n in namespaces):
                continue
            tokens = _tokens(row.content + " " + " ".join(row.tags or []))
            overlap = len(q_tokens & set(tokens)) if q_tokens else 0
            if q_tokens and overlap == 0:
                continue
            score = overlap / (len(q_tokens) or 1)
            if query.lower().strip() and query.lower().strip() in row.content.lower():
                score += 1.0
            if row.layer == "preference":
                score += 0.25
            updated = row.updated_at if row.updated_at.tzinfo else row.updated_at.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - updated).days
            score += max(0.0, 0.2 - age_days * 0.005)
            item = to_dict(row)
            item["score"] = round(score, 3)
            scored.append(item)
        scored.sort(key=lambda m: m["score"], reverse=True)
        return scored[:limit]

    def preferences_for(self, actor: "AgentConfig") -> list[dict[str, Any]]:
        if not self.enabled or not can_access(actor.memory.read_namespaces, "user:preferences"):
            return []
        with self.db.session() as s:
            rows = s.scalars(select(Memory).where(Memory.namespace == "user:preferences")
                             .order_by(Memory.updated_at.desc()).limit(20)).all()
            return [to_dict(r) for r in rows]

    # ---------- user-facing (the user owns all memory) ----------
    def list(self, *, namespace: str | None = None, layer: str | None = None, q: str | None = None) -> list[dict]:
        self.purge_expired()
        with self.db.session() as s:
            stmt = select(Memory).order_by(Memory.updated_at.desc())
            if namespace:
                stmt = stmt.where(Memory.namespace == namespace)
            if layer:
                stmt = stmt.where(Memory.layer == layer)
            if q:
                stmt = stmt.where(or_(Memory.content.ilike(f"%{q}%"), Memory.source.ilike(f"%{q}%")))
            return [to_dict(r) for r in s.scalars(stmt).all()]

    def update(self, memory_id: str, content: str) -> dict | None:
        with self.db.session() as s:
            row = s.get(Memory, memory_id)
            if row is None:
                return None
            row.content = content.strip()
            row.content_hash = _hash(row.namespace, row.content)
            row.updated_at = utcnow()
            return to_dict(row)

    def delete(self, memory_id: str) -> bool:
        with self.db.session() as s:
            row = s.get(Memory, memory_id)
            if row is None:
                return False
            s.delete(row)
        self.bus.publish("memory.deleted", {"id": memory_id})
        return True

    def get(self, memory_id: str) -> dict | None:
        with self.db.session() as s:
            row = s.get(Memory, memory_id)
            return to_dict(row) if row else None

    def purge_expired(self) -> int:
        with self.db.session() as s:
            res = s.execute(delete(Memory).where(Memory.expires_at.is_not(None), Memory.expires_at < utcnow()))
            return res.rowcount or 0

    def export(self) -> str:
        return json.dumps({"exported_at": utcnow().isoformat(), "memories": self.list()}, indent=2, default=str)
