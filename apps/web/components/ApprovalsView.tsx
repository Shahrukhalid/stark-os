"use client";

import { useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { Approval } from "@/lib/types";
import { ApprovalCard } from "./ApprovalCard";
import { Empty, Section } from "./ui";
import { errorText } from "@/lib/errors";

export function ApprovalsView({ openTask }: { openTask: (id: string) => void }) {
  const { approvals, client } = useStark();
  const [history, setHistory] = useState<Approval[]>([]);
  const [historyError, setHistoryError] = useState("");

  // Reloads when the queue changes, so a decision moves into "Recent decisions" right away.
  useEffect(() => {
    let live = true;
    client
      .get<Approval[]>("/api/approvals")
      .then((all) => {
        if (!live) return;
        setHistory(all.filter((a) => a.status !== "pending").slice(0, 30));
        setHistoryError("");
      })
      .catch((e: unknown) => {
        if (live) setHistoryError(errorText(e, "Could not load recent decisions."));
      });
    return () => {
      live = false;
    };
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
          {historyError && <p role="alert" className="text-xs text-red-400">{historyError}</p>}
          {!historyError && history.length === 0 && <Empty>No decisions yet.</Empty>}
          {history.map((a) => (
            <ApprovalCard key={a.id} approval={a} compact openTask={openTask} />
          ))}
        </div>
      </Section>
    </div>
  );
}
