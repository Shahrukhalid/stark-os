"use client";

import { Activity } from "lucide-react";
import { useState } from "react";
import { useStark } from "@/lib/store";
import { AvailabilityChip, Section } from "./ui";

function Bar({ label, value, warn = 85 }: { label: string; value: number; warn?: number }) {
  const color = value >= warn ? "#f87171" : value >= warn - 20 ? "#fbbf24" : "#22d3ee";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-[var(--color-mute)]">{label}</span>
        <span className="font-mono">{value.toFixed(1)}%</span>
      </div>
      <div className="h-2 rounded-full bg-white/5">
        <div className="h-2 rounded-full transition-all" style={{ width: `${Math.min(100, value)}%`, background: color }} />
      </div>
    </div>
  );
}

export function DiagnosticsView() {
  const { status, client, notify, sseConnected } = useStark();
  const [metrics, setMetrics] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  async function measure() {
    setBusy(true);
    try {
      const res = await client.post("/api/tools/system.metrics/run", { top_n: 8, sample_seconds: 1 });
      setMetrics(res.result.data);
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-2">
      <Section title="Platform">
        {!status ? (
          <p className="text-sm text-[var(--color-mute)]">Loading…</p>
        ) : (
          <dl className="grid grid-cols-[150px_1fr] gap-y-1.5 text-sm">
            <dt className="text-[var(--color-mute)]">Version</dt>
            <dd>{status.version}</dd>
            <dt className="text-[var(--color-mute)]">API host</dt>
            <dd>
              {status.host.os} {status.host.release} · {status.host.arch} · Python {status.host.python}
            </dd>
            <dt className="text-[var(--color-mute)]">Event stream</dt>
            <dd className={sseConnected ? "text-emerald-300" : "text-red-300"}>{sseConnected ? "connected" : "disconnected"}</dd>
            <dt className="text-[var(--color-mute)]">Database</dt>
            <dd>{status.database}</dd>
            <dt className="text-[var(--color-mute)]">Mode</dt>
            <dd className="uppercase">{status.mode.replace("_", " ")}</dd>
            <dt className="text-[var(--color-mute)]">Emergency stop</dt>
            <dd className={status.emergency_stop ? "text-red-300" : ""}>{status.emergency_stop ? "ENGAGED" : "off"}</dd>
            <dt className="text-[var(--color-mute)]">Workspace</dt>
            <dd className="font-mono text-xs">{status.workspace_roots.join(", ")}</dd>
            <dt className="text-[var(--color-mute)]">Running tasks</dt>
            <dd>{status.running_tasks}</dd>
          </dl>
        )}
      </Section>
      <Section title="Model provider (OpenRouter, free models only)">
        <div className="space-y-2">
          {status &&
            Object.entries(status.providers).map(([name, p]) => (
              <div key={name} className="rounded-lg border border-[var(--color-line)] p-2.5 text-sm">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${p.healthy ? "bg-emerald-400" : p.configured ? "bg-amber-400" : "bg-white/20"}`} />
                  <span className="font-medium">{name}</span>
                  <span className="ml-auto text-xs text-[var(--color-mute)]">{p.configured ? (p.healthy ? "healthy" : "configured, unreachable") : "not configured"}</span>
                </div>
                <div className="mt-1 text-xs text-[var(--color-mute)]">{p.detail}</div>
                {p.configured && (
                  <div className="mt-1 text-[11px] text-[var(--color-mute)]">
                    {p.pool_size} free tool-capable models in the pool
                    {status.quota ? ` · ${status.quota.remaining}/${status.quota.limit} free requests left today` : ""} · see the Models panel
                  </div>
                )}
              </div>
            ))}
        </div>
      </Section>
      <Section
        title="Live system metrics (API host)"
        right={
          <button className="btn" onClick={measure} disabled={busy}>
            <Activity size={14} /> {busy ? "Sampling…" : "Measure now"}
          </button>
        }
      >
        {!metrics ? (
          <p className="text-sm text-[var(--color-mute)]">Runs the real system.metrics tool (psutil) on the machine hosting the API. Nothing is shown until it actually runs.</p>
        ) : (
          <div className="space-y-3">
            <Bar label="CPU" value={metrics.cpu_percent} />
            <Bar label={`Memory (${metrics.memory.total_gb} GB)`} value={metrics.memory.used_percent} />
            {metrics.disks.map((d: any) => (
              <Bar key={d.mount} label={`Disk ${d.mount} (${d.total_gb} GB)`} value={d.used_percent} warn={90} />
            ))}
            {metrics.warnings.length > 0 && <p className="text-xs text-amber-200">⚠ {metrics.warnings.join(" · ")}</p>}
            <table className="w-full text-left text-xs">
              <thead className="text-[var(--color-mute)]">
                <tr>
                  <th className="py-1">Top CPU process</th>
                  <th>PID</th>
                  <th className="text-right">CPU %</th>
                  <th className="text-right">MB</th>
                </tr>
              </thead>
              <tbody>
                {metrics.top_cpu.map((p: any) => (
                  <tr key={p.pid} className="border-t border-[var(--color-line)]">
                    <td className="py-1">{p.name}</td>
                    <td className="font-mono">{p.pid}</td>
                    <td className="text-right font-mono">{p.cpu_percent}</td>
                    <td className="text-right font-mono">{p.memory_mb}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      <Section title="Capabilities">
        <div className="space-y-1.5 text-sm">
          {status &&
            Object.entries(status.tools).map(([id, a]) => (
              <div key={id} className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs">{id}</span>
                <AvailabilityChip value={a} />
              </div>
            ))}
        </div>
      </Section>
    </div>
  );
}
