"""Structured logging, audit trail and token/cost accounting."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from .db import AuditEntry, Database, UsageRecord
from .events import EventBus

_SECRET_PATTERNS = [
    re.compile(r"sk-or-v1-[0-9a-fA-F]{32,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\"?\s*[:=]\s*\"?)[^\s\"',]{8,}"),
]


_LITERAL_SECRETS: set[str] = set()


def register_secret(value: str) -> None:
    """Exact secret values (API token, OpenRouter key) are always scrubbed, whatever their shape."""
    if value and len(value) >= 8:
        _LITERAL_SECRETS.add(value)


def redact(text: str) -> str:
    """Remove anything that looks like a credential before it is logged."""
    for secret in _LITERAL_SECRETS:
        text = text.replace(secret, "[REDACTED]")
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: (m.group(1) if m.groups() else "") + "[REDACTED]", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "ctx", None)
        if extra:
            base["ctx"] = json.loads(redact(json.dumps(extra, default=str)))
        if record.exc_info:
            base["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(base)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("stark")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


log = logging.getLogger("stark")


class Observability:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus

    def audit(
        self,
        actor: str,
        action: str,
        outcome: str,
        *,
        target: str = "",
        task_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        detail = json.loads(redact(json.dumps(detail or {}, default=str)))
        with self.db.session() as s:
            entry = AuditEntry(actor=actor, action=action, outcome=outcome, target=redact(target)[:2000],
                               task_id=task_id, detail=detail)
            s.add(entry)
        log.info(f"audit {actor} {action} {outcome}", extra={"ctx": {"target": target, "task_id": task_id}})
        self.bus.publish("audit", {"actor": actor, "action": action, "outcome": outcome,
                                   "target": redact(target)[:300], "task_id": task_id})

    @staticmethod
    def cost(model: str, input_tokens: int, output_tokens: int, provider: str) -> tuple[float, bool]:
        """STARK OS only calls free models; anything else is recorded as unknown cost."""
        if model.endswith(":free") or model == "openrouter/free":
            return 0.0, True
        return 0.0, False

    def record_usage(self, *, task_id: str, agent_id: str, provider: str, model: str,
                     input_tokens: int, output_tokens: int, latency_ms: int) -> float:
        cost, known = self.cost(model, input_tokens, output_tokens, provider)
        with self.db.session() as s:
            s.add(UsageRecord(task_id=task_id, agent_id=agent_id, provider=provider, model=model,
                              input_tokens=input_tokens, output_tokens=output_tokens,
                              cost_usd=cost, cost_known=known, latency_ms=latency_ms))
        self.bus.publish("usage", {"task_id": task_id, "agent_id": agent_id, "model": model,
                                   "input_tokens": input_tokens, "output_tokens": output_tokens,
                                   "cost_usd": cost, "cost_known": known})
        return cost

    def requests_today(self) -> int:
        """Model calls since 00:00 UTC (OpenRouter's free quota resets then)."""
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        with self.db.session() as s:
            return int(s.scalar(select(func.count()).select_from(UsageRecord).where(UsageRecord.ts >= since)) or 0)
