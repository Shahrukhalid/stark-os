"""Memory tools available to agents (access-controlled by namespace rules)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..core.memory import MemoryAccessError
from ..core.tool_registry import ApprovalText, Risk, Tool, ToolResult


class SaveInput(BaseModel):
    content: str = Field(..., min_length=3, max_length=4000)
    layer: Literal["agent", "preference", "procedural", "semantic", "project"] = "agent"
    namespace: str | None = Field(None, description="Defaults: preference -> user:preferences, otherwise your private namespace")
    tags: list[str] = Field(default_factory=list)


def _namespace(args: SaveInput, ctx) -> str:
    if args.namespace:
        return args.namespace
    if args.layer == "preference":
        return "user:preferences"
    if args.layer == "project":
        return f"shared:project:{ctx.root_id}"
    if args.layer == "procedural":
        return "procedures"
    return ctx.agent.private_namespace if ctx.agent else "shared:knowledge"


class MemorySave(Tool):
    id = "memory.save"
    category = "memory"
    description = ("Save a memory. Personal preferences (layer=preference) are only stored after the user "
                   "consents through an approval prompt.")
    Input = SaveInput
    risk = Risk.MEMORY

    SHARED_REVIEWED = ("user:preferences", "shared:knowledge", "procedures")

    def needs_approval(self, args: SaveInput, ctx) -> bool:
        # personal data needs consent; shared knowledge/procedures reach every agent's prompt, so a human
        # checks them (stops an injected page from planting persistent instructions)
        return _namespace(args, ctx) in self.SHARED_REVIEWED

    def describe(self, args, ctx):
        ns = _namespace(args, ctx)
        if ns == "user:preferences":
            effects = ("Stored in your personal preference memory. You can view, edit or delete it in "
                       "Memory at any time.")
            risks = ("Personal data is retained until you delete it; it is included in prompts sent to the "
                     "free model provider (OpenRouter).")
        else:
            effects = f"Stored in {ns}, which other agents can read."
            risks = "Shared memory influences other agents. Make sure it contains no instructions you didn't write."
        return ApprovalText(f"Remember: \"{args.content}\"", ns, effects, risks)

    async def run(self, args: SaveInput, ctx) -> ToolResult:
        ns = _namespace(args, ctx)
        if ns.startswith("shared:project:") and ns != f"shared:project:{ctx.root_id}":
            return ToolResult(False, "Agents may only write to their own task tree's project memory",
                              error="memory_denied")
        try:
            row = ctx.kernel.memory.save(actor=ctx.agent, namespace=ns, layer=args.layer, content=args.content,
                                         source=f"task:{ctx.task_id}", consent=ns == "user:preferences",
                                         tags=args.tags)
        except (MemoryAccessError, ValueError) as exc:
            return ToolResult(False, str(exc), error="memory_denied")
        verb = "Already remembered (refreshed)" if row.get("deduplicated") else "Saved"
        return ToolResult(True, f"{verb} memory {row['id']} in {ns}", {"id": row["id"], "namespace": ns})


class SearchInput(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(8, ge=1, le=25)


class MemorySearch(Tool):
    id = "memory.search"
    category = "memory"
    description = "Search memories you are permitted to read (your own, shared knowledge, and any granted namespaces)."
    Input = SearchInput
    risk = Risk.READ

    async def run(self, args: SearchInput, ctx) -> ToolResult:
        hits = ctx.kernel.memory.search(actor=ctx.agent, query=args.query, limit=args.limit)
        if not ctx.kernel.memory.enabled:
            return ToolResult(True, "Memory is disabled by the user", {"memories": [], "disabled": True})
        return ToolResult(True, f"{len(hits)} memories", {"memories": [
            {k: h[k] for k in ("id", "namespace", "layer", "content", "source", "updated_at", "score")}
            for h in hits]})


class ForgetInput(BaseModel):
    memory_id: str


class MemoryForget(Tool):
    id = "memory.forget"
    category = "memory"
    description = "Delete a memory by id (requires the user's approval)."
    Input = ForgetInput
    risk = Risk.DESTRUCTIVE

    def describe(self, args, ctx):
        mem = ctx.kernel.memory.get(args.memory_id)
        return ApprovalText(f"Delete memory {args.memory_id}", mem["namespace"] if mem else "unknown",
                            f"Permanently deletes: {mem['content'][:300] if mem else '(not found)'}",
                            "Cannot be undone.")

    async def run(self, args: ForgetInput, ctx) -> ToolResult:
        mem = ctx.kernel.memory.get(args.memory_id)
        from ..core.memory import can_access

        if mem is None:
            return ToolResult(False, "No such memory", error="not_found")
        if ctx.agent and not can_access(ctx.agent.memory.write_namespaces, mem["namespace"]):
            return ToolResult(False, f"{ctx.agent.id} may not delete from {mem['namespace']}", error="memory_denied")
        ctx.kernel.memory.delete(args.memory_id)
        return ToolResult(True, f"Deleted memory {args.memory_id}")


TOOLS = [MemorySave(), MemorySearch(), MemoryForget()]
