"use client";

import { Play } from "lucide-react";
import { useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { ToolInfo } from "@/lib/types";
import { AvailabilityChip, RiskChip, Section } from "./ui";

function defaults(schema: any): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries<any>(schema?.properties || {})) {
    if (v.default !== undefined) out[k] = v.default;
    else if ((schema.required || []).includes(k)) out[k] = v.type === "string" ? "" : v.type === "array" ? [] : null;
  }
  return out;
}

export function ToolsView() {
  const { client, notify } = useStark();
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [sel, setSel] = useState<ToolInfo | null>(null);
  const [args, setArgs] = useState("{}");
  const [out, setOut] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    client.get<ToolInfo[]>("/api/tools").then(setTools).catch((e) => notify("error", e.message));
  }, [client, notify]);

  const groups = tools.reduce<Record<string, ToolInfo[]>>((acc, t) => {
    (acc[t.category] ||= []).push(t);
    return acc;
  }, {});

  async function run() {
    if (!sel) return;
    setBusy(true);
    setOut(null);
    try {
      setOut(await client.post(`/api/tools/${sel.id}/run`, JSON.parse(args || "{}")));
    } catch (e: any) {
      notify("error", e instanceof SyntaxError ? "Arguments must be valid JSON" : e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1fr_480px]">
      <Section title={`Tool registry (${tools.length})`}>
        <p className="mb-3 text-xs text-[var(--color-mute)]">Every tool listed is implemented and covered by automated tests. Availability shows what still needs credentials or runs as a labelled simulation.</p>
        <div className="space-y-4">
          {Object.entries(groups).map(([cat, list]) => (
            <div key={cat}>
              <div className="panel-title mb-1.5">{cat.replace("_", " ")}</div>
              <div className="space-y-1.5">
                {list.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => {
                      setSel(t);
                      setArgs(JSON.stringify(defaults(t.input_schema), null, 2));
                      setOut(null);
                    }}
                    className={`w-full rounded-lg border p-2.5 text-left transition hover:bg-white/5 ${sel?.id === t.id ? "border-cyan-400/50" : "border-[var(--color-line)]"}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-sm">{t.id}</span>
                      <RiskChip risk={t.risk} />
                      <AvailabilityChip value={t.availability} />
                      <span className="ml-auto text-[11px] text-[var(--color-mute)]">{(t.agents || []).join(", ")}</span>
                    </div>
                    <p className="mt-1 text-xs text-[var(--color-mute)]">{t.description}</p>
                    {t.availability_detail && <p className="mt-0.5 text-[11px] text-amber-200/80">{t.availability_detail}</p>}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Section>
      <Section title={sel ? `Run ${sel.id}` : "Run a tool"}>
        {!sel ? (
          <p className="text-sm text-[var(--color-mute)]">Select a tool. You can run read-only tools directly; anything that changes state must go through an agent and the approval queue.</p>
        ) : (
          <>
            <p className="mb-2 text-xs text-[var(--color-mute)]">Timeout {sel.timeout_s}s · risk {sel.risk}</p>
            <textarea className="input min-h-40 font-mono text-xs" value={args} onChange={(e) => setArgs(e.target.value)} aria-label="Tool arguments (JSON)" />
            <button className="btn btn-primary mt-2" disabled={busy || sel.risk !== "read"} onClick={run}>
              <Play size={14} /> {busy ? "Running…" : sel.risk === "read" ? "Run" : "Agents only (needs approval)"}
            </button>
            {out && (
              <div className="mt-3">
                <div className={`mb-1 text-sm ${out.result.ok ? "text-emerald-300" : "text-red-300"}`}>
                  {out.result.simulated && <span className="chip mr-1 !text-amber-300">SIMULATED</span>}
                  {out.result.summary}
                </div>
                <pre className="max-h-[55vh] overflow-auto rounded-lg bg-black/40 p-3 font-mono text-[11px]">{JSON.stringify(out.result.data, null, 2)}</pre>
              </div>
            )}
          </>
        )}
      </Section>
    </div>
  );
}
