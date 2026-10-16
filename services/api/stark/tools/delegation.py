"""Collaboration tools: delegate to one agent, or run a parallel team review."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..core.messaging import MessageType
from ..core.runtime import DelegationError
from ..core.tool_registry import ApprovalText, Risk, Tool, ToolResult


class DelegateInput(BaseModel):
    agent_id: str = Field(..., description="Recipient agent id, e.g. 'friday', 'jocasta'")
    instruction: str = Field(..., min_length=5, description="Self-contained task with all context the agent needs")
    kind: Literal["task", "question", "review"] = "task"


class AgentDelegate(Tool):
    id = "agent.delegate"
    category = "collaboration"
    description = ("Delegate a self-contained task to another agent and wait for its attributable result. "
                   "Subject to depth, cycle, duplicate and budget limits.")
    Input = DelegateInput
    risk = Risk.DELEGATION

    def describe(self, args, ctx):
        return ApprovalText(f"Delegate to {args.agent_id}", args.agent_id, args.instruction[:300], "None")

    async def run(self, args: DelegateInput, ctx) -> ToolResult:
        msg_type = {"task": MessageType.TASK_REQUEST, "question": MessageType.INFORMATION_REQUEST,
                    "review": MessageType.REVIEW_REQUEST}[args.kind]
        try:
            out = await ctx.kernel.delegate(ctx, args.agent_id, args.instruction, msg_type=msg_type)
        except DelegationError as exc:
            return ToolResult(False, f"Delegation refused: {exc}", error="delegation_refused")
        ok = out["status"] == "completed"
        return ToolResult(ok, f"{args.agent_id} {out['status']}" + (" (duplicate request, reused result)"
                                                                     if out.get("duplicate_of") else ""),
                          {"agent": args.agent_id, "task_id": out["task_id"], "status": out["status"],
                           "result": out.get("result"), "error": out.get("error")},
                          error=None if ok else out.get("error"))


class TeamReviewInput(BaseModel):
    subject: str = Field(..., min_length=10, description="What the team should review, with all needed context")
    reviewers: list[str] | None = Field(None, description="Subset of agents; default: everyone you may delegate to")


class TeamReview(Tool):
    id = "team.review"
    category = "collaboration"
    description = ("Ask several agents to review the same subject in parallel (each from its specialty), then have "
                   "Ultron challenge the combined results. Returns every attributable review.")
    Input = TeamReviewInput
    risk = Risk.DELEGATION
    allowed_agents = {"jarvis"}

    async def run(self, args: TeamReviewInput, ctx) -> ToolResult:
        try:
            out = await ctx.kernel.team_review(ctx, args.subject, args.reviewers)
        except DelegationError as exc:
            return ToolResult(False, f"Team review refused: {exc}", error="delegation_refused")
        n_ok = sum(1 for r in out["reviews"] if r.get("status") == "completed")
        return ToolResult(n_ok > 0, f"{n_ok}/{len(out['reviews'])} reviews completed"
                          + (f"; failed: {', '.join(out['failed_reviewers'])}" if out["failed_reviewers"] else ""),
                          out)


TOOLS = [AgentDelegate(), TeamReview()]
