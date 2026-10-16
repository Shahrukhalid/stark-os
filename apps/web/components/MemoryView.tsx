"use client";

import { Download, Pencil, Plus, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useStark } from "@/lib/store";
import type { Memory } from "@/lib/types";
import { Empty, Section, timeAgo } from "./ui";

const LAYERS = ["", "preference", "episodic", "semantic", "agent", "project", "procedural"];

export function MemoryView() {
  const { client, notify, events } = useStark();
  const [items, setItems] = useState<Memory[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [ns, setNs] = useState("");
  const [layer, setLayer] = useState("");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [newPref, setNewPref] = useState("");

  const reqId = useRef(0); // search runs on every keystroke: keep only the newest answer
  const load = useCallback(async () => {
    const id = ++reqId.current;
    const params = new URLSearchParams();
    if (ns) params.set("namespace", ns);
    if (layer) params.set("layer", layer);
    if (q) params.set("q", q);
    try {
      const res = await client.get<{ enabled: boolean; memories: Memory[] }>(`/api/memory?${params}`);
      if (id !== reqId.current) return;
      setItems(res.memories);
      setEnabled(res.enabled);
    } catch (e: any) {
      notify("error", e.message);
    }
  }, [client, ns, layer, q, notify]);

  const memEvents = events.filter((e) => e.type.startsWith("memory.")).length;
  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0); // debounce typing; reload on memory events
    return () => clearTimeout(t);
  }, [load, memEvents, q]);

  const namespaces = Array.from(new Set(items.map((m) => m.namespace))).sort();

  async function act(fn: () => Promise<unknown>, ok: string) {
    try {
      await fn();
      notify("success", ok);
      load();
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  async function exportAll() {
    try {
      const text = await client.get<string>("/api/memory/export");
      const blob = new Blob([typeof text === "string" ? text : JSON.stringify(text, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "stark-memory-export.json";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  return (
    <div className="space-y-4">
      <Section
        title="Memory controls"
        right={
          <div className="flex flex-wrap gap-2">
            <button className={`btn ${enabled ? "" : "btn-primary"}`} onClick={() => act(() => client.post("/api/memory/settings", { enabled: !enabled }), enabled ? "Memory disabled" : "Memory enabled")}>
              {enabled ? "Disable memory" : "Enable memory"}
            </button>
            <button className="btn" onClick={exportAll}>
              <Download size={14} /> Export my data
            </button>
          </div>
        }
      >
        <p className="text-xs text-[var(--color-mute)]">
          Status: <b className={enabled ? "text-emerald-300" : "text-red-300"}>{enabled ? "enabled" : "disabled — agents neither read nor write memory"}</b>. Personal preferences are stored only with your consent. Episodic task summaries expire automatically. Retrieval is keyword-based (vector search is planned).
        </p>
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (newPref.trim()) act(() => client.post("/api/memory", { content: newPref.trim() }), "Preference saved").then(() => setNewPref(""));
          }}
        >
          <input className="input" aria-label="New preference" placeholder="Add a preference yourself, e.g. “I prefer concise technical explanations”" value={newPref} onChange={(e) => setNewPref(e.target.value)} />
          <button className="btn btn-primary" disabled={!newPref.trim()}>
            <Plus size={14} /> Add
          </button>
        </form>
      </Section>

      <Section title={`Memory explorer (${items.length})`}>
        <div className="mb-3 grid gap-2 sm:grid-cols-3">
          <select className="input" value={ns} onChange={(e) => setNs(e.target.value)} aria-label="Namespace">
            <option value="">All namespaces</option>
            {Array.from(new Set(["user:preferences", "shared:knowledge", ...namespaces, ns].filter(Boolean))).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <select className="input" value={layer} onChange={(e) => setLayer(e.target.value)} aria-label="Layer">
            {LAYERS.map((l) => (
              <option key={l} value={l}>
                {l || "All layers"}
              </option>
            ))}
          </select>
          <input className="input" aria-label="Search memories" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="space-y-2">
          {items.length === 0 && <Empty>No memories match.</Empty>}
          {items.map((m) => (
            <div key={m.id} className="rounded-lg border border-[var(--color-line)] p-3">
              <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                <span className="chip">{m.namespace}</span>
                <span className="chip">{m.layer}</span>
                {m.consent && <span className="chip !text-emerald-300">consented</span>}
                <span className="text-[var(--color-mute)]">by {m.created_by} · {timeAgo(m.updated_at)}</span>
                {m.expires_at && <span className="text-[var(--color-mute)]">· expires {new Date(m.expires_at).toLocaleDateString()}</span>}
                <span className="ml-auto flex gap-1">
                  {editing === m.id ? (
                    <button className="btn !px-2 !py-1" aria-label="Save memory" title="Save" onClick={() => act(() => client.patch(`/api/memory/${m.id}`, { content: draft }), "Memory updated").then(() => setEditing(null))}>
                      <Save size={12} />
                    </button>
                  ) : (
                    <button
                      className="btn !px-2 !py-1"
                      aria-label="Edit"
                      onClick={() => {
                        setEditing(m.id);
                        setDraft(m.content);
                      }}
                    >
                      <Pencil size={12} />
                    </button>
                  )}
                  <button className="btn btn-danger !px-2 !py-1" aria-label="Delete" onClick={() => act(() => client.del(`/api/memory/${m.id}`), "Memory deleted")}>
                    <Trash2 size={12} />
                  </button>
                </span>
              </div>
              {editing === m.id ? (
                <textarea className="input min-h-24 font-mono text-xs" value={draft} onChange={(e) => setDraft(e.target.value)} />
              ) : (
                <div className="prose-stark line-clamp-6 text-sm">{m.content}</div>
              )}
              {m.source && <div className="mt-1 font-mono text-[10.5px] text-[var(--color-mute)]">source: {m.source}</div>}
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
