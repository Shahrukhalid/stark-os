"use client";

import { useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import { Empty, Section, timeAgo } from "./ui";

interface Row {
  key: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
}

export function UsageView() {
  const { client, events, agentById } = useStark();
  const [data, setData] = useState<any>(null);
  const usageEvents = events.filter((e) => e.type === "usage").length;

  useEffect(() => {
    client.get("/api/usage").then(setData).catch(() => {});
  }, [client, usageEvents]);

  if (!data) return <Section title="Usage">Loading…</Section>;
  const q = data.quota;
  const pct = q && q.limit ? Math.min(100, ((q.limit - q.remaining) / q.limit) * 100) : 0;
  const table = (rows: Row[], label: string) => (
    <table className="w-full text-left text-sm">
      <thead className="text-xs text-[var(--color-mute)]">
        <tr>
          <th className="py-1">{label}</th>
          <th className="text-right">Calls</th>
          <th className="text-right">Input tok</th>
          <th className="text-right">Output tok</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} className="border-t border-[var(--color-line)]">
            <td className="py-1.5 font-mono text-xs" style={{ color: agentById(r.key)?.color }}>
              {agentById(r.key)?.name || r.key}
            </td>
            <td className="text-right font-mono">{r.calls}</td>
            <td className="text-right font-mono">{r.input_tokens.toLocaleString()}</td>
            <td className="text-right font-mono">{r.output_tokens.toLocaleString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Section title="Free request quota (OpenRouter, resets 00:00 UTC)" className="xl:col-span-2">
        {q ? (
          <>
            <div className="flex items-end gap-3">
              <div className="text-3xl font-semibold">{q.remaining}</div>
              <div className="pb-1 text-sm text-[var(--color-mute)]">of {q.limit} free-model requests left today · {data.requests_today} made by STARK OS since midnight UTC</div>
            </div>
            <div className="mt-3 h-2 rounded-full bg-white/5">
              <div className="h-2 rounded-full" style={{ width: `${pct}%`, background: pct > 80 ? "#f87171" : "#22d3ee" }} />
            </div>
          </>
        ) : (
          <p className="text-sm text-[var(--color-mute)]">Quota unknown (OpenRouter unreachable or no key). {data.requests_today} model requests made today.</p>
        )}
        <p className="mt-2 text-xs text-[var(--color-mute)]">Every model is free ($0). A free OpenRouter key allows 50 free-model requests per day; a one-time $10 credit purchase raises that to 1000/day. Each agent step is one request, so a whole-team review uses roughly 10–20.</p>
      </Section>
      <Section title="By agent">{data.by_agent.length ? table(data.by_agent, "Agent") : <Empty>No model calls yet.</Empty>}</Section>
      <Section title="By model">{data.by_model.length ? table(data.by_model, "Model") : <Empty>No model calls yet.</Empty>}</Section>
      <Section title="Recent model calls" className="xl:col-span-2">
        {data.recent.length === 0 ? (
          <Empty>No model calls yet.</Empty>
        ) : (
          <table className="w-full text-left text-xs">
            <tbody>
              {data.recent.map((u: any) => (
                <tr key={u.id} className="border-t border-[var(--color-line)]">
                  <td className="py-1 text-[var(--color-mute)]">{timeAgo(u.ts)}</td>
                  <td>{agentById(u.agent_id)?.name || u.agent_id}</td>
                  <td className="font-mono">{u.model}</td>
                  <td className="text-right font-mono">{u.input_tokens}+{u.output_tokens}</td>
                  <td className="text-right font-mono">{u.latency_ms}ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  );
}
