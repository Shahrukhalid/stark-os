"""Tool registry: every capability an agent can invoke is a registered Tool.

A tool declares its schema, risk class, which agents may use it, a timeout,
and how to describe itself for an approval request. Tools report their own
availability honestly (implemented / requires credentials / simulated ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from .agent_registry import AgentConfig
    from .runtime import ToolContext


class Risk(str, Enum):
    READ = "read"  # observe only
    MEMORY = "memory"  # writes to the agent's own memory
    DELEGATION = "delegation"  # asks another agent to work
    WRITE = "write"  # reversible change to files/state
    EXTERNAL = "external"  # communicates outside the system
    SENSITIVE = "sensitive"  # credentials, accounts, money, security settings
    PHYSICAL = "physical"  # moves or powers real (or simulated) devices
    DESTRUCTIVE = "destructive"  # irreversible


class Availability(str, Enum):
    IMPLEMENTED = "implemented"
    REQUIRES_CREDENTIALS = "requires_credentials"
    REQUIRES_HARDWARE = "requires_hardware"
    SIMULATED = "simulated"
    UNAVAILABLE = "unavailable"


@dataclass
class ToolResult:
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    simulated: bool = False
    sources: list[dict[str, Any]] = field(default_factory=list)

    def for_model(self, limit: int = 12_000) -> str:
        import json

        body = {"ok": self.ok, "summary": self.summary, "data": self.data}
        if self.error:
            body["error"] = self.error
        if self.simulated:
            body["simulated"] = True
            body["notice"] = "SIMULATION: nothing was sent to a real platform."
        text = json.dumps(body, default=str)
        if len(text) > limit:
            text = text[:limit] + '... [truncated]"}'
        return text


@dataclass
class ApprovalText:
    action: str
    target: str
    effects: str
    risks: str


class Tool:
    id: ClassVar[str]
    category: ClassVar[str]
    description: ClassVar[str]
    Input: ClassVar[type[BaseModel]]
    risk: ClassVar[Risk] = Risk.READ
    allowed_agents: ClassVar[set[str] | None] = None  # None = any agent whose allowlist includes it
    timeout_s: ClassVar[float] = 30.0

    def availability(self, ctx: "ToolContext | None" = None) -> tuple[Availability, str]:
        return Availability.IMPLEMENTED, ""

    def needs_approval(self, args: BaseModel, ctx: "ToolContext") -> bool:
        """Extra approval triggers beyond the risk class (e.g. sensitive paths)."""
        return False

    def describe(self, args: BaseModel, ctx: "ToolContext") -> ApprovalText:
        return ApprovalText(
            action=f"{self.id} {args.model_dump_json()}",
            target="",
            effects=self.description,
            risks=f"risk class: {self.risk.value}",
        )

    def audit_target(self, args: BaseModel, ctx: "ToolContext") -> str:
        """Target recorded in the audit log after a run (must not have side effects)."""
        return self.describe(args, ctx).target

    def grant_scope_keys(self, args: BaseModel, ctx: "ToolContext") -> list[str] | None:
        """Normalised workspace paths this call touches, matched against Grant.scope in
        EXECUTE_APPROVED mode. None means the tool can never be covered by a grant."""
        return None

    async def run(self, args: BaseModel, ctx: "ToolContext") -> ToolResult:  # pragma: no cover
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        schema = self.Input.model_json_schema()
        schema.pop("title", None)
        return {"name": self.id.replace(".", "__"), "description": self.description, "input_schema": schema}

    def info(self, ctx: "ToolContext | None" = None) -> dict[str, Any]:
        status, detail = self.availability(ctx)
        return {
            "id": self.id,
            "category": self.category,
            "description": self.description,
            "risk": self.risk.value,
            "timeout_s": self.timeout_s,
            "allowed_agents": sorted(self.allowed_agents) if self.allowed_agents else None,
            "availability": status.value,
            "availability_detail": detail,
            "input_schema": self.schema()["input_schema"],
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.id in self._tools:
            raise ValueError(f"duplicate tool id {tool.id}")
        self._tools[tool.id] = tool

    def get(self, tool_id: str) -> Tool:
        return self._tools[tool_id]

    def by_model_name(self, name: str) -> Tool | None:
        return self._tools.get(name.replace("__", "."))

    def ids(self) -> set[str]:
        return set(self._tools)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def for_agent(self, agent: "AgentConfig") -> list[Tool]:
        out = []
        for tool_id in agent.tools:
            tool = self._tools.get(tool_id)
            if tool and (tool.allowed_agents is None or agent.id in tool.allowed_agents):
                out.append(tool)
        return out
