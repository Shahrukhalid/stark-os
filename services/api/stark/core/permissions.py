"""Permission engine and human-approval workflow.

The same policy applies to every agent. J.A.R.V.I.S. being the orchestrator,
or Ultron being the critic, changes nothing here: there is no agent-specific
bypass, and no tool exists that lets an agent change modes, grants or its own
configuration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import select

from .db import Approval, Database, Grant, to_dict, utcnow
from .events import EventBus
from .tool_registry import Availability, Risk, Tool

if TYPE_CHECKING:
    from .agent_registry import AgentConfig
    from .runtime import ToolContext


class Mode(str, Enum):
    OBSERVE = "observe"  # read-only
    ASSIST = "assist"  # drafts + approval for every change (default)
    EXECUTE_APPROVED = "execute_approved"  # changes inside user-granted scopes run; others need approval
    SCHEDULED = "scheduled"  # predefined workflows (scheduler not yet implemented: behaves like ASSIST)


_RANK = {Mode.OBSERVE: 0, Mode.ASSIST: 1, Mode.SCHEDULED: 1, Mode.EXECUTE_APPROVED: 2}
ALWAYS_APPROVE = {Risk.EXTERNAL, Risk.SENSITIVE, Risk.PHYSICAL, Risk.DESTRUCTIVE}


class Verdict(str, Enum):
    ALLOW = "allow"
    APPROVAL = "approval"
    DENY = "deny"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str
    mode: Mode


def effective_mode(global_mode: Mode, agent: "AgentConfig") -> Mode:
    agent_mode = Mode(agent.permission_level)
    return global_mode if _RANK[global_mode] <= _RANK[agent_mode] else agent_mode


class PermissionEngine:
    def __init__(self, db: Database, default_mode: str = "assist") -> None:
        self.db = db
        self._default_mode = Mode(default_mode)
        self.emergency_stop = False

    @property
    def global_mode(self) -> Mode:
        return Mode(self.db.get_setting("mode", self._default_mode.value))

    def set_mode(self, mode: Mode) -> None:
        self.db.set_setting("mode", mode.value)

    def _grant_matches(self, agent_id: str, tool: Tool, args: BaseModel, ctx: "ToolContext") -> bool:
        from ..tools.filesystem import in_scope

        keys = tool.grant_scope_keys(args, ctx)
        if not keys:
            return False
        now = datetime.now(timezone.utc)
        with self.db.session() as s:
            grants = s.scalars(select(Grant).where(Grant.agent_id == agent_id, Grant.tool_id == tool.id)).all()
        for g in grants:
            exp = g.expires_at
            if exp is not None and exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp is not None and exp < now:
                continue
            if all(in_scope(k, g.scope) for k in keys):  # every touched path must be inside the scope
                return True
        return False

    def decide(self, agent: "AgentConfig", tool: Tool, args: BaseModel, ctx: "ToolContext") -> Decision:
        mode = effective_mode(self.global_mode, agent)
        if self.emergency_stop:
            return Decision(Verdict.DENY, "emergency stop is engaged", mode)
        if tool.id not in agent.tools:
            return Decision(Verdict.DENY, f"{agent.id} is not permitted to use {tool.id}", mode)
        if tool.allowed_agents is not None and agent.id not in tool.allowed_agents:
            return Decision(Verdict.DENY, f"{tool.id} is restricted to {sorted(tool.allowed_agents)}", mode)
        status, detail = tool.availability(ctx)
        if status not in (Availability.IMPLEMENTED, Availability.SIMULATED):
            return Decision(Verdict.DENY, f"{tool.id} unavailable ({status.value}): {detail}", mode)

        risk = tool.risk
        extra = tool.needs_approval(args, ctx)
        if risk is Risk.READ:
            return Decision(Verdict.APPROVAL if extra else Verdict.ALLOW,
                            "sensitive read needs approval" if extra else "read-only", mode)
        if risk is Risk.DELEGATION:
            return Decision(Verdict.ALLOW, "delegation (delegate is checked independently)", mode)
        if mode is Mode.OBSERVE:
            return Decision(Verdict.DENY, f"OBSERVE mode: {risk.value} actions are disabled", mode)
        if risk is Risk.MEMORY:
            return Decision(Verdict.APPROVAL if extra else Verdict.ALLOW,
                            "memory consent required" if extra else "own memory", mode)
        if risk in ALWAYS_APPROVE:
            return Decision(Verdict.APPROVAL, f"{risk.value} actions always need approval", mode)
        # Risk.WRITE
        if mode is Mode.EXECUTE_APPROVED and not extra and self._grant_matches(agent.id, tool, args, ctx):
            return Decision(Verdict.ALLOW, "within a user-granted scope", mode)
        return Decision(Verdict.APPROVAL, "changes need approval", mode)


class ApprovalManager:
    def __init__(self, db: Database, bus: EventBus, timeout_s: int) -> None:
        self.db = db
        self.bus = bus
        self.timeout_s = timeout_s
        self._waiters: dict[str, asyncio.Event] = {}

    def create(self, *, task_id: str, agent_id: str, tool_id: str, action: str, target: str,
               effects: str, risks: str, permissions: list[str], tool_input: dict) -> dict:
        with self.db.session() as s:
            row = Approval(task_id=task_id, agent_id=agent_id, tool_id=tool_id, action=action,
                           target=target, expected_effects=effects, risks=risks,
                           permissions=permissions, tool_input=tool_input)
            s.add(row)
            s.flush()
            data = to_dict(row)
        self._waiters[data["id"]] = asyncio.Event()
        self.bus.publish("approval.created", data)
        return data

    async def wait(self, approval_id: str) -> str:
        event = self._waiters.get(approval_id)
        if event is None:
            return self.status(approval_id)
        try:
            await asyncio.wait_for(event.wait(), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            self.decide(approval_id, "expired", decided_by="system")
        except asyncio.CancelledError:
            self.decide(approval_id, "cancelled", decided_by="system")
            raise
        finally:
            self._waiters.pop(approval_id, None)
        return self.status(approval_id)

    def status(self, approval_id: str) -> str:
        with self.db.session() as s:
            row = s.get(Approval, approval_id)
            return row.status if row else "missing"

    def decide(self, approval_id: str, status: str, decided_by: str = "user", note: str | None = None) -> dict | None:
        assert status in {"approved", "rejected", "cancelled", "expired"}
        with self.db.session() as s:
            row = s.get(Approval, approval_id)
            if row is None or row.status != "pending":
                return None
            row.status = status
            row.decided_by = decided_by
            row.decided_at = utcnow()
            row.note = note
            data = to_dict(row)
        event = self._waiters.get(approval_id)
        if event:
            event.set()
        self.bus.publish("approval.decided", data)
        return data

    def cancel_for_task(self, task_id: str) -> None:
        with self.db.session() as s:
            ids = s.scalars(select(Approval.id).where(Approval.task_id == task_id, Approval.status == "pending")).all()
        for aid in ids:
            self.decide(aid, "cancelled", decided_by="system")

    def cancel_all(self) -> int:
        with self.db.session() as s:
            ids = s.scalars(select(Approval.id).where(Approval.status == "pending")).all()
        for aid in ids:
            self.decide(aid, "cancelled", decided_by="emergency_stop")
        return len(ids)
