"use client";

import { MessageSquareText, Plus, Save, Send, Tags, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { Snippet } from "@/lib/types";
import { Empty, Section, timeAgo } from "./ui";

interface Convo {
  id: string;
  with: string;
  name: string;
  unread: number;
  last_text: string;
  last_at: string | null;
  last_from_me: boolean;
}

/** Bluesky direct messages: read conversations and reply yourself (saved replies help; nothing is automatic). */
export function DirectMessages() {
  const { client, notify } = useStark();
  const [convos, setConvos] = useState<Convo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Convo | null>(null);
  const [msgs, setMsgs] = useState<{ id: string; text: string; at: string; from_me: boolean }[]>([]);
  const [draft, setDraft] = useState("");
  const [saved, setSaved] = useState<Snippet[]>([]);

  const load = useCallback(() => {
    client.get<{ convos: Convo[] }>("/api/inbox/dms").then((r) => (setConvos(r.convos), setError(null)), (e) => setError(e.message));
  }, [client]);
  useEffect(() => {
    load();
    client.get<{ snippets: Snippet[] }>("/api/library").then((r) => setSaved(r.snippets.filter((s) => s.kind === "reply"))).catch(() => {});
  }, [client, load]);
  useEffect(() => {
    if (open) client.get<{ messages: typeof msgs }>(`/api/inbox/dms/${open.id}`).then((r) => setMsgs(r.messages), () => {});
  }, [client, open]);

  async function send() {
    if (!open) return;
    try {
      await client.post(`/api/inbox/dms/${open.id}`, { text: draft });
      setMsgs((m) => [...m, { id: String(Date.now()), text: draft, at: new Date().toISOString(), from_me: true }]);
      setDraft("");
      notify("success", "Message sent");
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  if (error) return <Empty>{error}</Empty>;
  if (!convos) return <Empty>Loading messages…</Empty>;
  return (
    <div className="grid gap-3 md:grid-cols-[260px_1fr]">
      <ul className="max-h-[520px] space-y-1 overflow-y-auto">
        {convos.length === 0 && <li className="text-xs text-[var(--color-mute)]">No conversations yet.</li>}
        {convos.map((c) => (
          <li key={c.id}>
            <button onClick={() => setOpen(c)} className={`w-full rounded-lg border p-2 text-left text-xs ${open?.id === c.id ? "border-cyan-400/50 bg-cyan-400/5" : "border-[var(--color-line)] hover:bg-white/5"}`}>
              <span className="flex items-center gap-2">
                <span className="truncate font-semibold">{c.name || c.with}</span>
                {c.unread > 0 && <span className="ml-auto rounded-full bg-cyan-400 px-1.5 text-[10px] font-bold text-black">{c.unread}</span>}
              </span>
              <span className="block truncate text-[var(--color-mute)]">{c.last_from_me ? "You: " : ""}{c.last_text}</span>
              <span className="block text-[10px] text-[var(--color-mute)]">{timeAgo(c.last_at)}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="flex min-h-[300px] flex-col rounded-lg border border-[var(--color-line)] p-3">
        {!open ? (
          <Empty>Pick a conversation.</Empty>
        ) : (
          <>
            <div className="mb-2 text-sm font-semibold">{open.name || open.with} <span className="font-normal text-[var(--color-mute)]">{open.with}</span></div>
            <ol className="flex-1 space-y-1.5 overflow-y-auto">
              {msgs.map((m) => (
                <li key={m.id} className={`max-w-[80%] rounded-xl px-3 py-1.5 text-sm ${m.from_me ? "ml-auto bg-cyan-400/15" : "bg-white/5"}`}>
                  {m.text}
                </li>
              ))}
            </ol>
            <div className="mt-2 flex flex-wrap gap-2">
              {saved.length > 0 && (
                <select className="input !w-auto !py-1 text-xs" aria-label="Saved reply" value="" onChange={(e) => setDraft(saved.find((s) => s.id === e.target.value)?.body || draft)}>
                  <option value="">Saved replies…</option>
                  {saved.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              )}
              <input className="input min-w-0 flex-1" aria-label="Your message" placeholder="Write a reply…" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === "Enter" && draft.trim() && send()} />
              <button className="btn btn-primary" disabled={!draft.trim()} onClick={send}>
                <Send size={14} /> Send
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Inbox rules: words that add a label (and priority) to listening results. Labels only, never replies. */
export function InboxRules() {
  const { client, notify } = useStark();
  const [rules, setRules] = useState<{ contains: string; label: string; priority: string }[]>([]);
  const [form, setForm] = useState({ contains: "", label: "", priority: "normal" });
  useEffect(() => {
    client.get<{ rules: typeof rules }>("/api/inbox/rules").then((r) => setRules(r.rules)).catch(() => {});
  }, [client]);
  const save = (next: typeof rules) => client.put<{ rules: typeof rules }>("/api/inbox/rules", { rules: next }).then((r) => (setRules(r.rules), notify("success", "Rules saved")), (e) => notify("error", e.message));
  return (
    <Section title="Inbox rules" right={<Tags size={15} className="text-amber-300" />}>
      <p className="mb-2 text-[11px] text-[var(--color-mute)]">Add a label when a post contains certain words. Labels only: nothing is ever answered automatically.</p>
      <ul className="mb-2 space-y-1 text-xs">
        {rules.map((r, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="chip !text-amber-300">{r.label}</span>
            <span className="min-w-0 flex-1 truncate text-[var(--color-mute)]">{r.contains}</span>
            <button aria-label={`Remove rule ${r.label}`} onClick={() => save(rules.filter((_, j) => j !== i))}>
              <X size={12} />
            </button>
          </li>
        ))}
      </ul>
      <div className="grid gap-1.5">
        <input className="input !py-1 text-xs" aria-label="Rule words" placeholder="Words, comma separated: refund, money back" value={form.contains} onChange={(e) => setForm({ ...form, contains: e.target.value })} />
        <div className="flex gap-1.5">
          <input className="input !py-1 text-xs" aria-label="Rule label" placeholder="Label: Billing" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
          <button className="btn !py-1 text-xs" disabled={!form.contains.trim() || !form.label.trim()} onClick={() => (save([...rules, form]), setForm({ contains: "", label: "", priority: "normal" }))} aria-label="Add rule">
            <Plus size={12} />
          </button>
        </div>
      </div>
    </Section>
  );
}

/** Your own YouTube channel, podcast and blog: new items become drafts automatically. */
export function OwnFeeds() {
  const { client, notify } = useStark();
  const [feeds, setFeeds] = useState<{ url: string; kind: string; platforms: string[]; template: string; primed?: boolean }[]>([]);
  const [form, setForm] = useState({ kind: "youtube", url: "" });
  useEffect(() => {
    client.get<{ feeds: typeof feeds }>("/api/feeds").then((r) => setFeeds(r.feeds)).catch(() => {});
  }, [client]);
  const save = (next: typeof feeds) => client.put<{ feeds: typeof feeds }>("/api/feeds", { feeds: next }).then((r) => (setFeeds(r.feeds), notify("success", "Saved. The first check only remembers what is already there."), true), (e) => (notify("error", e.message), false));
  return (
    <Section title="Your channels → drafts" right={<MessageSquareText size={15} className="text-cyan-300" />}>
      <p className="mb-2 text-xs text-[var(--color-mute)]">When you publish a new YouTube video, podcast episode or blog post, STARK OS drafts an announcement for your platforms (checked every hour). You still approve each one.</p>
      <ul className="mb-2 space-y-1 text-xs">
        {feeds.map((f, i) => (
          <li key={f.url} className="flex items-center gap-2">
            <span className="chip capitalize">{f.kind}</span>
            <span className="break-anywhere min-w-0 flex-1 text-[var(--color-mute)]">{f.url}</span>
            <button aria-label={`Remove ${f.url}`} onClick={() => save(feeds.filter((_, j) => j !== i))}>
              <X size={12} />
            </button>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-1.5">
        <select className="input !w-auto !py-1 text-xs" aria-label="Feed type" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          <option value="youtube">YouTube channel</option>
          <option value="podcast">Podcast RSS</option>
          <option value="blog">Blog RSS</option>
        </select>
        <input className="input min-w-0 flex-1 !py-1 text-xs" aria-label="Feed address" placeholder={form.kind === "youtube" ? "Channel URL or id (UC…)" : "https://…/feed"} value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
        <button className="btn !py-1 text-xs" disabled={!form.url.trim()} onClick={async () => (await save([...feeds, { ...form, platforms: ["bluesky", "mastodon"], template: "" }])) && setForm({ ...form, url: "" })}>
          <Save size={12} /> Add feed
        </button>
        <button className="btn !py-1 text-xs" disabled={!feeds.length} onClick={() => client.post("/api/feeds/check").then((r: any) => notify(r.errors.length ? "warn" : "success", `${r.drafts.length} new draft(s)${r.errors.length ? ` · ${r.errors[0]}` : ""}`), (e) => notify("error", e.message))}>
          Check now
        </button>
      </div>
    </Section>
  );
}
