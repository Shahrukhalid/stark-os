"""Typed agent-to-agent collaboration protocol.

Every inter-agent interaction is recorded as an ``AgentMessage`` so the whole
collaboration is inspectable in the dashboard (Tasks -> collaboration view).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from .db import AgentMessageRow, Database, new_id, to_dict
from .events import EventBus


class MessageType(str, Enum):
    TASK_REQUEST = "TASK_REQUEST"
    TASK_ACCEPTED = "TASK_ACCEPTED"
    TASK_RESULT = "TASK_RESULT"
    TASK_FAILED = "TASK_FAILED"
    INFORMATION_REQUEST = "INFORMATION_REQUEST"
    INFORMATION_RESPONSE = "INFORMATION_RESPONSE"
    REVIEW_REQUEST = "REVIEW_REQUEST"
    REVIEW_RESULT = "REVIEW_RESULT"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    STATUS_UPDATE = "STATUS_UPDATE"
    CANCEL_TASK = "CANCEL_TASK"


class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    sender: str
    recipient: str
    task_id: str
    root_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "sent"
    correlation_id: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    permission_context: dict[str, Any] = Field(default_factory=dict)


class MessageLog:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus

    def send(self, msg: AgentMessage) -> AgentMessage:
        with self.db.session() as s:
            s.add(AgentMessageRow(id=msg.message_id, correlation_id=msg.correlation_id, task_id=msg.task_id,
                                  root_id=msg.root_id, sender=msg.sender, recipient=msg.recipient,
                                  type=msg.type.value, status=msg.status, payload=msg.payload,
                                  evidence=msg.evidence, permission_context=msg.permission_context,
                                  created_at=msg.timestamp))
        self.bus.publish("message", msg.model_dump(mode="json"))
        return msg

    def for_root(self, root_id: str) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = s.scalars(select(AgentMessageRow).where(AgentMessageRow.root_id == root_id)
                             .order_by(AgentMessageRow.created_at)).all()
            return [to_dict(r) for r in rows]

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.db.session() as s:
            rows = s.scalars(select(AgentMessageRow).order_by(AgentMessageRow.created_at.desc()).limit(limit)).all()
            return [to_dict(r) for r in rows]
