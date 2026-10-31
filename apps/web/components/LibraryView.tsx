"use client";

import { Copy, FileUp, Hash, Image as ImageIcon, PenLine, Plug, Plus, Signature, Trash2, Webhook } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useStark } from "@/lib/store";
import type { Snippet } from "@/lib/types";
import { Empty, Section } from "./ui";

const KINDS = [
  { id: "template", label: "Templates", icon: PenLine, hint: "A post skeleton, e.g. “New video: {title}. {one-line hook} {link}”" },
  { id: "hashtags", label: "Hashtag groups", icon: Hash, hint: "#BuildInPublic #OpenSource #AI" },
  { id: "signature", label: "Signatures", icon: Signature, hint: "— The STARK OS team · stark.example" },
] as const;

function Thumb({ name }: { name: string }) {
  const { client } = useStark();
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let u: string | null = null;
    client
      .blob(`/api/media/file?name=${encodeURIComponent(name)}`)
      .then((b) => setUrl((u = URL.createObjectURL(b))))
      .catch(() => {});
    return () => {
      if (u) URL.revokeObjectURL(u);
    };
  }, [client, name]);
  // eslint-disable-next-line @next/next/no-img-element
  return url ? <img src={url} alt={name} className="h-full w-full object-cover" /> : <div className="shimmer h-full w-full" />;
}

/** Library: templates, hashtag groups and signatures the agents use; media; bulk import; integrations. */
export function LibraryView() {
  const { client, notify } = useStark();
  const [items, setItems] = useState<Snippet[]>([]);
  const [kind, setKind] = useState<Snippet["kind"]>("template");
  const [form, setForm] = useState({ name: "", body: "" });
  const [images, setImages] = useState<{ name: string; file: string }[]>([]);
  const [hooks, setHooks] = useState<{ count: number; signed: boolean; events: string[] } | null>(null);
  const [imported, setImported] = useState<{ created: number; scheduled: number; errors: string[] } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    client.get<{ snippets: Snippet[] }>("/api/library").then((r) => setItems(r.snippets)).catch(() => {});
    client.get<{ images: { name: string; file: string }[] }>("/api/media").then((r) => setImages(r.images)).catch(() => {});
    client.get("/api/webhooks").then(setHooks).catch(() => {});
  }, [client]);
  useEffect(load, [load]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    try {
      await client.post("/api/library", { kind, ...form });
      setForm({ name: "", body: "" });
      load();
    } catch (err: any) {
      notify("error", err.message);
    }
  }

  async function importFile(f: File) {
    try {
      const out = await client.post<{ created: number; scheduled: number; errors: string[] }>("/api/social/import", { csv: await f.text() });
      setImported(out);
      notify(out.errors.length ? "warn" : "success", `${out.created} post(s) imported, ${out.scheduled} scheduled`);
    } catch (err: any) {
      notify("error", err.message);
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const copy = (text: string) => navigator.clipboard?.writeText(text).then(() => notify("success", "Copied"), () => {});
  const meta = KINDS.find((k) => k.id === kind)!;
  const mcpConfig = JSON.stringify({ mcpServers: { "stark-os": { command: "<STARK OS folder>/services/api/.venv/bin/python", args: ["-m", "stark.mcp_server"], cwd: "<STARK OS folder>/services/api" } } }, null, 2);

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="panel p-4">
        <div className="hud-label text-cyan-300">Content library</div>
        <h1 className="holo-text text-xl font-semibold">Library</h1>
        <p className="text-xs text-[var(--color-mute)]">Templates, hashtag groups and signatures every agent uses; your images; bulk import; and connections to other tools.</p>
      </section>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1.2fr_1fr]">
        <section className="panel p-4">
          <div className="mb-3 flex flex-wrap gap-2" role="tablist">
            {KINDS.map((k) => (
              <button key={k.id} role="tab" aria-selected={kind === k.id} onClick={() => setKind(k.id)} className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs ${kind === k.id ? "bg-cyan-400/15 text-cyan-200 ring-1 ring-cyan-400/30" : "text-[var(--color-mute)] hover:bg-white/5"}`}>
                <k.icon size={13} /> {k.label} <span className="opacity-60">{items.filter((x) => x.kind === k.id).length}</span>
              </button>
            ))}
          </div>
          <form onSubmit={add} className="mb-4 grid gap-2 sm:grid-cols-[180px_1fr_auto]">
            <input className="input" aria-label="Name" placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input className="input" aria-label="Text" placeholder={meta.hint} value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
            <button className="btn btn-primary justify-center" disabled={!form.name.trim() || !form.body.trim()}>
              <Plus size={14} /> Add
            </button>
          </form>
          {items.filter((x) => x.kind === kind).length === 0 ? (
            <Empty>No {meta.label.toLowerCase()} yet. The writers use these automatically once you add them.</Empty>
          ) : (
            <ul className="space-y-2">
              {items
                .filter((x) => x.kind === kind)
                .map((x) => (
                  <li key={x.id} className="flex items-start gap-2 rounded-lg border border-[var(--color-line)] p-2.5 text-sm">
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium">{x.name}</span>
                      <span className="break-anywhere block whitespace-pre-wrap text-xs text-[var(--color-mute)]">{x.body}</span>
                    </span>
                    <button className="text-[var(--color-mute)] hover:text-cyan-300" onClick={() => copy(x.body)} aria-label={`Copy ${x.name}`}>
                      <Copy size={13} />
                    </button>
                    <button className="text-[var(--color-mute)] hover:text-red-300" onClick={() => client.del(`/api/library/${x.id}`).then(load)} aria-label={`Delete ${x.name}`}>
                      <Trash2 size={13} />
                    </button>
                  </li>
                ))}
            </ul>
          )}
        </section>

        <div className="space-y-4">
          <Section title="Bulk import (CSV)" right={<FileUp size={15} className="text-cyan-300" />}>
            <p className="text-xs text-[var(--color-mute)]">
              Columns: <span className="font-mono">platform, text</span> and optionally <span className="font-mono">scheduled_for</span> (2026-11-05 09:30 UTC), <span className="font-mono">campaign</span>, <span className="font-mono">thread</span> (parts split by ||). Up to 500 rows. Every row is policy-checked; scheduled rows still need your approval to go out on their own.
            </p>
            <input ref={fileRef} type="file" accept=".csv,text/csv" className="mt-2 block text-xs" aria-label="CSV file" onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
            {imported && (
              <div className="mt-2 text-xs">
                <span className="text-emerald-300">{imported.created} imported · {imported.scheduled} scheduled</span>
                {imported.errors.map((er) => (
                  <div key={er} className="text-amber-300">{er}</div>
                ))}
              </div>
            )}
          </Section>

          <Section title={`Media · ${images.length}`} right={<ImageIcon size={15} className="text-fuchsia-300" />}>
            {images.length === 0 ? (
              <p className="text-xs text-[var(--color-mute)]">Images you create in Studio appear here.</p>
            ) : (
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                {images.slice(0, 24).map((im) => (
                  <button key={im.name} className="aspect-square overflow-hidden rounded-lg border border-[var(--color-line)] hover:border-cyan-400/50" title={`${im.file} (click to copy the path)`} onClick={() => copy(im.file)}>
                    <Thumb name={im.name} />
                  </button>
                ))}
              </div>
            )}
          </Section>
        </div>
      </div>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-2">
        <Section title="Automation apps (webhooks)" right={<Webhook size={15} className="text-violet-300" />}>
          <p className="text-xs text-[var(--color-mute)]">
            n8n, Make, Zapier or your own server get a POST for {hooks?.events.join(", ") || "post and mention events"}. Add <span className="font-mono">STARK_WEBHOOK_URLS</span> (comma-separated https URLs) and optionally <span className="font-mono">STARK_WEBHOOK_SECRET</span> to <span className="font-mono">.env</span>; each call is then signed in the <span className="font-mono">X-Stark-Signature</span> header.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="chip">{hooks?.count ? `${hooks.count} URL(s)${hooks.signed ? " · signed" : ""}` : "not set up"}</span>
            <button className="btn !py-1 text-xs" disabled={!hooks?.count} onClick={() => client.post("/api/webhooks/test").then((r: any) => notify("success", `Delivered to ${r.delivered}/${r.of}`), (e) => notify("error", e.message))}>
              Send a test
            </button>
          </div>
        </Section>
        <Section title="AI assistants and editors (MCP)" right={<Plug size={15} className="text-emerald-300" />}>
          <p className="text-xs text-[var(--color-mute)]">
            Any assistant or editor that supports MCP servers can read your queue, analytics and mentions, save drafts, put drafts on the calendar and give the team tasks. It can never publish: that always needs you. Add this to the app&apos;s MCP settings (replace the folder):
          </p>
          <pre className="mt-2 overflow-x-auto rounded-lg border border-[var(--color-line)] bg-black/20 p-2 font-mono text-[11px]">{mcpConfig}</pre>
          <button className="btn mt-2 !py-1 text-xs" onClick={() => copy(mcpConfig)}>
            <Copy size={12} /> Copy
          </button>
        </Section>
      </div>
    </div>
  );
}
