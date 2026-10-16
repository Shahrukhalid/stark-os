"use client";

import { Ban, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { AgentMessage, Approval, AuditEntry, Task } from "@/lib/types";
import { ApprovalCard } from "./ApprovalCard";
import { CollabGraph } from "./CollabGraph";
import { AgentGlyph, duration, Empty, Section, TaskStatus, timeAgo } from "./ui";

interface Detail {
  task: Task;
  tree: Task[];
  messages: AgentMessage[];
  audit: AuditEntry[];
  approvals: Approval[];
}

export function TasksView({ focus, setFocus }: { focus: string | null; setFocus: (id: string | null) => void }) {
  const { tasks, client, agents, notify, events } = useStark();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [filter, setFilter] = useState("all");
  const roots = tasks.filter((t) => !t.parent_id && (filter === "all" || t.agent_id === filter));

  const load = useCallback(async () => {
    if (!focus) return setDetail(null);
    try {
      setDetail(await client.get<Detail>(`/api/tasks/${focus}`));
    } catch (e: any) {
      notify("error", e.message);
    }
  }, [client, focus, notify]);

  useEffect(() => {
    load();
  }, [load]);

  // refresh the open task when real events for its tree arrive
  const last = events[events.length - 1];
  useEffect(() => {
    if (!detail || !last) return;
    const ids = new Set(detail.tree.map((t) => t.id));
    if (ids.has(last.data.task_id) || ids.has(last.data.id) || last.data.root_id === detail.task.root_id) {
      const t = setTimeout(load, 300);
      return () => clearTimeout(t);
    }
  }, [last]); // eslint-disable-line react-hooks/exhaustive-deps

  const agentOf = (id: string) => agents.find((a) => a.id === id);
  const root = detail?.tree.find((t) => !t.parent_id) || detail?.task;

  return (
    <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
      <Section
        title="Task history"
        right={
          <select className="input !w-auto !py-1 text-xs" value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">All agents</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
            <option value="user">Direct tool runs</option>
          </select>
        }
      >
        <div className="max-h-[75vh] space-y-1.5 overflow-y-auto pr-1">
          {roots.length === 0 && <Empty>No tasks yet.</Empty>}
          {roots.map((t) => {
            const a = agentOf(t.agent_id);
            const kids = tasks.filter((x) => x.root_id === t.id && x.id !== t.id).length;
            return (
              <button
                key={t.id}
                onClick={() => setFocus(t.id)}
                className={`w-full rounded-lg border p-2.5 text-left text-sm transition hover:bg-white/5 ${focus === t.id ? "border-cyan-400/50 bg-cyan-400/5" : "border-[var(--color-line)]"}`}
              >
                <div className="flex items-center gap-2">
                  {a ? <AgentGlyph icon={a.icon} color={a.color} size={16} /> : <span className="chip">user</span>}
                  <span className="truncate font-medium">{t.instruction.slice(0, 70)}</span>
                </div>
                <div className="mt-1.5 flex items-center gap-2 text-xs text-[var(--color-mute)]">
                  <TaskStatus status={t.status} />
                  {kids > 0 && <span className="chip">{kids} delegated</span>}
                  <span className="ml-auto">{timeAgo(t.created_at)}</span>
                </div>
              </button>
            );
          })}
        </div>
      </Section>

      {!detail || !root ? (
        <Section title="Task detail">
          <Empty>Select a task to inspect its delegation tree, agent messages, approvals and audit trail.</Empty>
        </Section>
      ) : (
        <div className="space-y-4">
          <Section
            title={`Task ${root.id}`}
            right={
              <div className="flex gap-2">
                <button className="btn" onClick={load}>
                  <RefreshCw size={13} />
                </button>
                {!["completed", "failed", "cancelled"].includes(root.status) && (
                  <button className="btn btn-danger" onClick={() => client.post(`/api/tasks/${root.id}/cancel`).then(load).catch((e) => notify("error", e.message))}>
                    <Ban size={13} /> Cancel
                  </button>
                )}
              </div>
            }
          >
            <p className="mb-2 text-sm">{root.instruction}</p>
            <div className="flex flex-wrap gap-2 text-xs">
              <TaskStatus status={root.status} />
              <span className="chip">{root.kind}</span>
              {root.model && <span className="chip font-mono">{root.provider}/{root.model}</span>}
              <span className="chip">{detail.tree.reduce((s, t) => s + t.input_tokens + t.output_tokens, 0).toLocaleString()} tokens (tree)</span>
              <span className="chip">${detail.tree.reduce((s, t) => s + t.cost_usd, 0).toFixed(4)}</span>
              <span className="chip">{duration(root.started_at, root.finished_at)}</span>
            </div>
            {root.error && <p className="mt-3 rounded-lg border border-red-400/30 bg-red-400/10 p-2 text-sm text-red-200">{root.error}</p>}
          </Section>

          {detail.approvals.filter((a) => a.status === "pending").map((a) => <ApprovalCard key={a.id} approval={a} />)}

          <div className="grid gap-4 2xl:grid-cols-2">
            <Section title="Collaboration">
              <CollabGraph agents={agents} messages={detail.messages} tree={detail.tree} />
              <div className="mt-2 space-y-1">
                {detail.tree.map((t) => {
                  const a = agentOf(t.agent_id);
                  return (
                    <div key={t.id} className="flex items-center gap-2 text-xs" style={{ paddingLeft: t.depth * 18 }}>
                      {t.depth > 0 && <span className="text-[var(--color-mute)]">└</span>}
                      {a && <AgentGlyph icon={a.icon} color={a.color} size={14} />}
                      <span style={{ color: a?.color }}>{a?.name || t.agent_id}</span>
                      <span className="chip">{t.kind}</span>
                      <TaskStatus status={t.status} />
                      <span className="ml-auto text-[var(--color-mute)]">{duration(t.started_at, t.finished_at)}</span>
                    </div>
                  );
                })}
              </div>
            </Section>
            <Section title={`Agent messages (${detail.messages.length})`}>
              <ol className="max-h-[420px] space-y-1.5 overflow-y-auto font-mono text-[11px]">
                {detail.messages.length === 0 && <Empty>No inter-agent messages in this task.</Empty>}
                {detail.messages.map((m) => (
                  <li key={m.id} className="rounded-md border border-[var(--color-line)] p-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span style={{ color: agentOf(m.sender)?.color }}>{m.sender}</span>→<span style={{ color: agentOf(m.recipient)?.color }}>{m.recipient}</span>
                      <span className="chip">{m.type}</span>
                      <span className="ml-auto text-[var(--color-mute)]">{new Date(m.created_at).toLocaleTimeString()}</span>
                    </div>
                    {Object.keys(m.payload).length > 0 && (
                      <div className="mt-1 line-clamp-3 text-[var(--color-mute)]">{String((m.payload as any).instruction || (m.payload as any).result || (m.payload as any).action || (m.payload as any).error || "")}</div>
                    )}
                  </li>
                ))}
              </ol>
            </Section>
          </div>

          {detail.tree.map((t) => (
            <Section key={t.id} title={`${agentOf(t.agent_id)?.name || t.agent_id} · ${t.kind} result`}>
              {t.result ? <div className="prose-stark max-h-[480px] overflow-auto text-sm">{t.result}</div> : <Empty>{t.error || "No result yet."}</Empty>}
              {t.sources.length > 0 && (
                <div className="mt-3">
                  <div className="panel-title mb-1">Retrieved sources</div>
                  <ul className="space-y-0.5 text-xs">
                    {t.sources.map((s) => (
                      <li key={s.url}>
                        <a href={/^https?:\/\//i.test(s.url) ? s.url : undefined} target="_blank" rel="noreferrer noopener" className="text-cyan-300 hover:underline">
                          {s.title || s.url}
                        </a>{" "}
                        <span className="text-[var(--color-mute)]">{s.retrieved_at ? `retrieved ${new Date(s.retrieved_at).toLocaleString()}` : ""}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Section>
          ))}

          <Section title={`Audit trail (${detail.audit.length})`}>
            <table className="w-full text-left text-xs">
              <tbody>
                {detail.audit.map((a) => (
                  <tr key={a.id} className="border-t border-[var(--color-line)]">
                    <td className="py-1 pr-2 font-mono text-[var(--color-mute)]">{new Date(a.ts).toLocaleTimeString()}</td>
                    <td className="pr-2">{a.actor}</td>
                    <td className="pr-2 font-mono">{a.action}</td>
                    <td className={a.outcome === "ok" || a.outcome === "approved" ? "text-emerald-300" : a.outcome === "denied" || a.outcome === "error" || a.outcome === "rejected" ? "text-red-300" : ""}>{a.outcome}</td>
                    <td className="max-w-[300px] truncate pl-2 text-[var(--color-mute)]">{String((a.detail as any).summary || (a.detail as any).reason || a.target || "")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
        </div>
      )}
    </div>
  );
}
