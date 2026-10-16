"use client";

import { Check, ChevronDown, ChevronUp, Ban, X } from "lucide-react";
import { useState } from "react";
import { useStark } from "@/lib/store";
import type { Approval } from "@/lib/types";
import { AgentGlyph, timeAgo } from "./ui";

export function ApprovalCard({ approval, compact = false, openTask }: { approval: Approval; compact?: boolean; openTask?: (id: string) => void }) {
  const { client, notify, agentById } = useStark();
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(!compact);
  const agent = agentById(approval.agent_id);

  async function decide(decision: "approve" | "reject" | "cancel") {
    setBusy(true);
    try {
      await client.post(`/api/approvals/${approval.id}/decision`, { decision });
      notify(decision === "approve" ? "success" : "info", `${decision === "approve" ? "Approved" : decision === "reject" ? "Rejected" : "Cancelled"}: ${approval.action}`.slice(0, 140));
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy(false);
    }
  }

  const pending = approval.status === "pending";
  return (
    <div className={`rounded-xl border p-3 ${pending ? "border-amber-300/40 bg-amber-300/[0.04]" : "border-[var(--color-line)]"}`}>
      <div className="flex items-start gap-3">
        {agent && <AgentGlyph icon={agent.icon} color={agent.color} size={22} />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="hud-label" style={{ color: agent?.color }}>
              {agent?.name || approval.agent_id}
            </span>
            <span className="chip">{approval.tool_id}</span>
            <span className="text-xs text-[var(--color-mute)]">{timeAgo(approval.created_at)}</span>
            {!pending && <span className="chip">{approval.status}</span>}
          </div>
          <div className="mt-1 text-sm font-medium">{approval.action}</div>
        </div>
        <button className="text-[var(--color-mute)]" onClick={() => setOpen(!open)} aria-label="Review details">
          {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
      </div>
      {open && (
        <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-[120px_1fr]">
          <dt className="hud-label text-[var(--color-mute)]">Target</dt>
          <dd className="font-mono text-xs break-all">{approval.target || "—"}</dd>
          <dt className="hud-label text-[var(--color-mute)]">Expected effects</dt>
          <dd className="prose-stark max-h-56 overflow-auto font-mono text-xs">{approval.expected_effects}</dd>
          <dt className="hud-label text-[var(--color-mute)]">Potential risks</dt>
          <dd className="text-amber-100/90">{approval.risks}</dd>
          <dt className="hud-label text-[var(--color-mute)]">Permissions</dt>
          <dd className="flex flex-wrap gap-1">
            {approval.permissions.map((p) => (
              <span key={p} className="chip">
                {p}
              </span>
            ))}
          </dd>
          <dt className="hud-label text-[var(--color-mute)]">Raw input</dt>
          <dd>
            <pre className="max-h-40 overflow-auto rounded-lg bg-black/40 p-2 font-mono text-[11px]">{JSON.stringify(approval.tool_input, null, 2)}</pre>
          </dd>
        </dl>
      )}
      {pending && (
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="btn btn-primary" disabled={busy} onClick={() => decide("approve")}>
            <Check size={14} /> Approve once
          </button>
          <button className="btn btn-danger" disabled={busy} onClick={() => decide("reject")}>
            <X size={14} /> Reject
          </button>
          <button className="btn" disabled={busy} onClick={() => decide("cancel")}>
            <Ban size={14} /> Cancel
          </button>
          {openTask && (
            <button className="btn ml-auto" onClick={() => openTask(approval.task_id)}>
              View task
            </button>
          )}
        </div>
      )}
    </div>
  );
}
