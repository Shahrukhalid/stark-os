"use client";

import { ExternalLink, PauseCircle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useStark } from "@/lib/store";
import type { ContentItem, SocialAccount } from "@/lib/types";
import { Empty, Section, timeAgo } from "./ui";

const STATUSES = ["all", "draft", "scheduled", "published", "failed", "rejected"] as const;

const VERDICT: Record<string, string> = {
  pass: "!text-emerald-300",
  warn: "!text-amber-300",
  fail: "!text-red-300",
};

/** Read-only view of the content queue. Publishing always goes through D.U.M.-E. and an approval. */
export function ContentView({ talkTo }: { talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify, events } = useStark();
  const [items, setItems] = useState<ContentItem[]>([]);
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("all");

  const load = useCallback(async () => {
    try {
      const [q, a] = await Promise.all([
        client.get<{ items: ContentItem[] }>(`/api/social/queue?status=${status}`),
        client.get<{ accounts: SocialAccount[] }>("/api/social/accounts"),
      ]);
      setItems(q.items);
      setAccounts(a.accounts);
    } catch (e: any) {
      notify("error", e.message);
    }
  }, [client, notify, status]);

  const contentEvents = useMemo(() => events.filter((e) => e.type.startsWith("content.")).length, [events]);
  useEffect(() => {
    load();
  }, [load, contentEvents]);

  const connected = accounts.filter((a) => a.mode === "connected");
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
      <Section
        title="Content queue"
        right={
          <div className="flex items-center gap-2">
            <select className="input !py-1 text-xs" value={status} onChange={(e) => setStatus(e.target.value as any)} aria-label="Filter by status">
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <button className="btn" onClick={load} title="Refresh"><RefreshCw size={14} /></button>
          </div>
        }
      >
        {!items.length ? (
          <Empty>No content yet. Try: &ldquo;EDITH, draft a launch post for Bluesky and LinkedIn&rdquo;.</Empty>
        ) : (
          <ul className="space-y-3">
            {items.map((it) => (
              <li key={it.id} className="rounded-lg border border-[var(--color-line)] bg-black/20 p-3" data-testid="content-item">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                  <span className="chip">{it.platform}</span>
                  <span className="chip">{it.kind}</span>
                  <span className="chip">{it.status}</span>
                  {it.check?.verdict && <span className={`chip ${VERDICT[it.check.verdict] || ""}`}>check {it.check.verdict.toUpperCase()}</span>}
                  {it.review?.verdict && <span className="chip">J.A.R.V.I.S.: {it.review.verdict}</span>}
                  {it.simulated && <span className="chip !text-amber-300">{it.status === "published" ? "SIMULATED" : "simulated platform"}</span>}
                  {it.paused && <span className="chip !text-red-300"><PauseCircle size={12} className="mr-1 inline" />paused</span>}
                  {it.due && <span className="chip !text-cyan-300">due now</span>}
                  <span className="ml-auto font-mono text-[var(--color-mute)]">{it.id} · by {it.created_by}</span>
                </div>
                <p className="whitespace-pre-wrap text-sm">{it.text}</p>
                {it.thread?.map((p, i) => (
                  <p key={i} className="mt-1 border-l-2 border-[var(--color-line)] pl-2 text-sm text-[var(--color-mute)]">{p}</p>
                ))}
                {it.media?.length > 0 && (
                  <ul className="mt-2 list-disc pl-5 text-xs text-[var(--color-mute)]">
                    {it.media.map((m, i) => <li key={i}>Media brief: {m.description}{m.alt_text ? ` (alt: ${m.alt_text})` : " (no alt text)"}</li>)}
                  </ul>
                )}
                {it.check?.issues?.length > 0 && (
                  <ul className="mt-2 space-y-0.5 text-xs">
                    {it.check.issues.map((iss, i) => (
                      <li key={i} className={iss.level === "fail" ? "text-red-300" : "text-amber-200"}>{iss.level.toUpperCase()} · {iss.message}</li>
                    ))}
                  </ul>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--color-mute)]">
                  {it.scheduled_for && <span>scheduled {new Date(it.scheduled_for).toLocaleString()} ({timeAgo(it.scheduled_for)})</span>}
                  {it.error && <span className="text-red-300">{it.error}</span>}
                  {it.external_url && (
                    <a className="inline-flex items-center gap-1 text-cyan-300 hover:underline" href={it.external_url} target="_blank" rel="noreferrer noopener">
                      view post <ExternalLink size={12} />
                    </a>
                  )}
                  {["draft", "scheduled", "failed"].includes(it.status) && (
                    <button className="btn ml-auto !py-0.5 text-xs" onClick={() => talkTo("dum_e", `DUM-E, publish ${it.id}`)}>
                      Ask D.U.M.-E. to publish
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title="Platforms">
        <p className="mb-2 text-xs text-[var(--color-mute)]">
          {connected.length ? `${connected.length} connected for real posting.` : "No account connected: every publish is a SIMULATION."} Every publish needs your approval.
        </p>
        <ul className="space-y-1.5 text-sm">
          {accounts.map((a) => (
            <li key={a.platform} className="flex items-start gap-2">
              <span className={`chip ${a.mode === "connected" ? "!text-emerald-300" : "!text-amber-300"}`}>{a.mode === "connected" ? "LIVE" : "SIM"}</span>
              <div>
                <div>{a.name} <span className="text-xs text-[var(--color-mute)]">· {a.char_limit} chars</span></div>
                <div className="text-xs text-[var(--color-mute)]">{a.detail}</div>
              </div>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
