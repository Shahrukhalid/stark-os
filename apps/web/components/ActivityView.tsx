"use client";

import { useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { AuditEntry } from "@/lib/types";
import { Section } from "./ui";

export function ActivityView({ openTask }: { openTask: (id: string) => void }) {
  const { client, events } = useStark();
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const auditEvents = events.filter((e) => e.type === "audit").length;

  useEffect(() => {
    client.get<AuditEntry[]>("/api/audit?limit=300").then(setAudit).catch(() => {});
  }, [client, auditEvents]);

  return (
    <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1fr_420px]">
      <Section title="Audit log">
        <div className="max-h-[78vh] overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-[var(--color-panel)] text-[var(--color-mute)]">
              <tr>
                <th className="py-1.5">Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Outcome</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((a) => (
                <tr key={a.id} className="border-t border-[var(--color-line)] align-top">
                  <td className="whitespace-nowrap py-1 pr-2 font-mono text-[var(--color-mute)]">{new Date(a.ts).toLocaleString()}</td>
                  <td className="pr-2">{a.actor}</td>
                  <td className="pr-2 font-mono">{a.action}</td>
                  <td className={`pr-2 ${["denied", "error", "rejected", "engaged"].includes(a.outcome) ? "text-red-300" : "text-emerald-300"}`}>{a.outcome}</td>
                  <td className="max-w-[360px] text-[var(--color-mute)]">
                    <span className="line-clamp-2">{String((a.detail as any).summary || (a.detail as any).reason || (a.detail as any).error || a.target || "")}</span>
                    {a.task_id && (
                      <button className="text-cyan-300 hover:underline" onClick={() => openTask(a.task_id!)}>
                        {a.task_id}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <Section title="Live event stream">
        <ol className="max-h-[78vh] space-y-1 overflow-auto font-mono text-[11px]">
          {[...events].reverse().slice(0, 200).map((e, i) => (
            <li key={i} className="border-b border-[var(--color-line)] pb-1">
              <span className="text-[var(--color-mute)]">{new Date(e.ts).toLocaleTimeString()}</span> <span className="text-cyan-300">{e.type}</span>{" "}
              <span className="text-[var(--color-ink)]/70">{(e.data.agent_id || e.data.actor || e.data.sender || "") + " " + (e.data.tool || e.data.action || e.data.status || e.data.type || "")}</span>
            </li>
          ))}
        </ol>
      </Section>
    </div>
  );
}
