"use client";

import { useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { Approval } from "@/lib/types";
import { ApprovalCard } from "./ApprovalCard";
import { Empty, Section } from "./ui";

export function ApprovalsView({ openTask }: { openTask: (id: string) => void }) {
  const { approvals, client } = useStark();
  const [history, setHistory] = useState<Approval[]>([]);

  useEffect(() => {
    client.get<Approval[]>("/api/approvals").then((all) => setHistory(all.filter((a) => a.status !== "pending").slice(0, 30))).catch(() => {});
  }, [client, approvals.length]);

  return (
    <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1fr_420px]">
      <Section title={`Approval queue (${approvals.length})`}>
        <p className="mb-3 text-xs text-[var(--color-mute)]">
          Every change, every publish and every sensitive read waits here. Agents stay paused until you decide; requests expire automatically.
        </p>
        <div className="space-y-3">
          {approvals.length === 0 && <Empty>Nothing waiting for approval.</Empty>}
          {approvals.map((a) => (
            <ApprovalCard key={a.id} approval={a} openTask={openTask} />
          ))}
        </div>
      </Section>
      <Section title="Recent decisions">
        <div className="space-y-2">
          {history.length === 0 && <Empty>No decisions yet.</Empty>}
          {history.map((a) => (
            <ApprovalCard key={a.id} approval={a} compact openTask={openTask} />
          ))}
        </div>
      </Section>
    </div>
  );
}
