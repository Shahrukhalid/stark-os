"use client";

import { RefreshCw, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { ModelsInfo } from "@/lib/types";
import { Empty, Section } from "./ui";

interface PingResult {
  model: string;
  ok: boolean;
  ms: number;
  served_by?: string;
  tool_calling?: boolean;
  error?: string;
  kind?: string;
}

export function ModelsView() {
  const { client, notify } = useStark();
  const [info, setInfo] = useState<ModelsInfo | null>(null);
  const [pings, setPings] = useState<Record<string, PingResult>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async (refresh = false) => {
    try {
      setInfo(refresh ? await client.post<ModelsInfo>("/api/models/refresh") : await client.get<ModelsInfo>("/api/models"));
    } catch (e: any) {
      notify("error", e.message);
    }
  }, [client, notify]);

  useEffect(() => {
    load();
  }, [load]);

  async function ping(models: string[]) {
    setBusy(models.length === 1 ? models[0] : "all");
    try {
      const res = await client.post<{ results: PingResult[] }>("/api/models/ping", { models, limit: models.length });
      setPings((p) => ({ ...p, ...Object.fromEntries(res.results.map((r) => [r.model, r])) }));
      const ok = res.results.filter((r) => r.ok).length;
      notify(ok === res.results.length ? "success" : "warn", `${ok}/${res.results.length} models answered with a tool call`);
      load();
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy(null);
    }
  }

  if (!info) return <Section title="Models">Loading…</Section>;
  if (!info.configured)
    return (
      <Section title="Models">
        <Empty>Add a free OPENROUTER_API_KEY to .env and restart the API.</Empty>
      </Section>
    );

  const q = info.quota;
  return (
    <div className="space-y-4">
      <Section
        title="Free model pool (OpenRouter)"
        right={
          <div className="flex gap-2">
            <button className="btn" onClick={() => load(true)}>
              <RefreshCw size={13} /> Refresh catalogue
            </button>
            <button className="btn btn-primary" disabled={!!busy} onClick={() => ping(info.pool)}>
              <Zap size={13} /> {busy === "all" ? "Pinging…" : `Ping all ${info.pool.length}`}
            </button>
          </div>
        }
      >
        <p className="text-sm">
          STARK OS uses only <b>free</b> models. Agents try their tier's models in order and automatically fail over when one is rate-limited or unavailable.
        </p>
        <p className="mt-1 text-xs text-[var(--color-mute)]">
          {q ? `${q.remaining} of ${q.limit} free requests left today (resets 00:00 UTC). ` : ""}
          Each ping uses one request.{info.catalog_error ? ` Catalogue fetch failed (${info.catalog_error}); using the verified snapshot.` : ""}
        </p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          {Object.entries(info.tiers).map(([tier, list]) => (
            <div key={tier} className="rounded-lg border border-[var(--color-line)] p-2.5">
              <div className="panel-title mb-1">
                {tier} tier{info.pins[tier] ? " (pinned)" : ""}
              </div>
              <ol className="list-decimal pl-4 font-mono text-[11px]">
                {list.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      </Section>

      <Section title={`All free models listed by OpenRouter (${info.catalog.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[var(--color-mute)]">
              <tr>
                <th className="py-1.5">Model</th>
                <th>Context</th>
                <th>Tools</th>
                <th>Inputs</th>
                <th>Verified 2026-10-16</th>
                <th>This session</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {info.catalog.map((m) => {
                const p = pings[m.id];
                const h = m.health;
                return (
                  <tr key={m.id} className={`border-t border-[var(--color-line)] ${m.in_pool ? "" : "text-[var(--color-mute)]"}`}>
                    <td className="py-1.5 pr-2 font-mono">
                      {m.id}
                      {!m.in_pool && <span className="ml-1 text-[var(--color-mute)]">{m.excluded ? "(excluded: API-restricted)" : "(not usable by agents)"}</span>}
                    </td>
                    <td className="font-mono">{m.context_length ? `${Math.round(m.context_length / 1000)}k` : "—"}</td>
                    <td>{m.tools ? "✓" : "—"}</td>
                    <td>{m.input_modalities.join(", ")}</td>
                    <td className={m.snapshot ? (m.snapshot.ok ? "text-emerald-300" : "text-amber-300") : "text-[var(--color-mute)]"}>
                      {m.snapshot ? (m.snapshot.ok ? `ok · ${m.snapshot.ms}ms` : m.snapshot.error) : "new / not tested"}
                    </td>
                    <td>
                      {p ? (
                        <span className={p.ok ? "text-emerald-300" : "text-red-300"}>
                          {p.ok ? `ok · ${p.ms}ms${p.tool_calling ? " · tool call" : " · no tool call"}` : `${p.kind}: ${p.error?.slice(0, 60)}`}
                        </span>
                      ) : h ? (
                        <span className={h.cooling_down_s ? "text-amber-300" : "text-[var(--color-mute)]"}>
                          {h.ok} ok / {h.failed} failed{h.cooling_down_s ? ` · cooling ${h.cooling_down_s}s (${h.cooldown_reason})` : ""}
                        </span>
                      ) : (
                        <span className="text-[var(--color-mute)]">—</span>
                      )}
                    </td>
                    <td className="text-right">
                      {m.in_pool && (
                        <button className="btn !px-2 !py-0.5 text-[11px]" disabled={!!busy} onClick={() => ping([m.id])}>
                          {busy === m.id ? "…" : "Ping"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}
