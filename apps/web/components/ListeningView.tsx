"use client";

import { Check, ExternalLink, Hash, Plus, Radar, RefreshCw, Reply, Sparkles, Trash2, User, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useStark } from "@/lib/store";
import type { Competitor, Mention, Watch } from "@/lib/types";
import { Empty, Section, timeAgo } from "./ui";

const CAT: Record<string, string> = { escalate: "#f87171", abuse: "#fb923c", complaint: "#fbbf24", question: "#22d3ee", praise: "#34d399", spam: "#7d8d99", general: "#a78bfa", competitor: "#f472b6" };
const KIND_ICON = { keyword: Radar, hashtag: Hash, account: User } as const;

/** Social listening: keywords, hashtags and competitor accounts on Bluesky and Mastodon. */
export function ListeningView({ talkTo }: { talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify, eventSeq } = useStark();
  const [watches, setWatches] = useState<Watch[]>([]);
  const [mentions, setMentions] = useState<Mention[]>([]);
  const [rivals, setRivals] = useState<Competitor[]>([]);
  const [tab, setTab] = useState<"new" | "done" | "rivals">("new");
  const [filter, setFilter] = useState<string>("");
  const [form, setForm] = useState({ kind: "keyword" as Watch["kind"], query: "", bluesky: true, mastodon: true });
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    client.get<{ watches: Watch[] }>("/api/listening/watches").then((r) => setWatches(r.watches)).catch(() => {});
    client
      .get<{ mentions: Mention[]; competitors: Competitor[] }>(`/api/listening/mentions?status=${tab === "done" ? "done" : "new"}${filter ? `&watch_id=${filter}` : ""}`)
      .then((r) => {
        setMentions(r.mentions);
        setRivals(r.competitors);
      })
      .catch(() => {});
  }, [client, tab, filter]);
  useEffect(load, [load, eventSeq.listening]);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const platforms = [form.bluesky && "bluesky", form.mastodon && "mastodon"].filter(Boolean);
    try {
      await client.post("/api/listening/watches", { kind: form.kind, query: form.query, platforms });
      setForm((f) => ({ ...f, query: "" }));
      notify("success", "Following it. First results in a moment.");
      await client.post("/api/listening/run");
      load();
    } catch (err: any) {
      notify("error", err.message);
    }
  }
  async function runNow() {
    setBusy(true);
    try {
      const r = await client.post<{ new: number; errors: string[] }>("/api/listening/run");
      notify(r.errors.length ? "warn" : "success", `${r.new} new result(s)${r.errors.length ? ` · ${r.errors.join("; ")}` : ""}`);
      load();
    } catch (err: any) {
      notify("error", err.message);
    } finally {
      setBusy(false);
    }
  }
  const setStatus = (id: string, status: string) => client.post(`/api/listening/mentions/${id}/status?status=${status}`).then(load).catch((e) => notify("error", e.message));
  const toggle = (w: Watch) => client.patch(`/api/listening/watches/${w.id}`, { enabled: !w.enabled }).then(load);
  const remove = (w: Watch) => client.del(`/api/listening/watches/${w.id}`).then(load);
  const watchName = (id: string) => watches.find((w) => w.id === id)?.query || "";

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="panel flex flex-wrap items-center gap-3 p-4">
        <div>
          <div className="hud-label text-cyan-300">Social listening</div>
          <h1 className="holo-text text-xl font-semibold">Listening</h1>
          <p className="text-xs text-[var(--color-mute)]">Follow keywords, hashtags and competitor accounts on Bluesky and Mastodon. Questions and complaints are flagged; F.R.I.D.A.Y. drafts replies for you to approve.</p>
        </div>
        <button className="btn ml-auto text-xs" onClick={runNow} disabled={busy || !watches.length}>
          <RefreshCw size={13} className={busy ? "anim-spin-fast" : ""} /> Check now
        </button>
      </section>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[320px_1fr]">
        <div className="space-y-4">
          <Section title="Follow something new">
            <form onSubmit={add} className="space-y-2">
              <div className="flex rounded-lg border border-[var(--color-line-strong)] p-0.5 text-xs" role="radiogroup" aria-label="What to follow">
                {(["keyword", "hashtag", "account"] as const).map((k) => (
                  <button type="button" key={k} role="radio" aria-checked={form.kind === k} onClick={() => setForm({ ...form, kind: k })} className={`flex-1 rounded-md px-2 py-1 capitalize ${form.kind === k ? "bg-cyan-400/15 text-cyan-200" : "text-[var(--color-mute)]"}`}>
                    {k}
                  </button>
                ))}
              </div>
              <input
                className="input"
                aria-label="Keyword, hashtag or account"
                placeholder={form.kind === "account" ? "rival.bsky.social or user@mastodon.social" : form.kind === "hashtag" ? "BuildInPublic" : "your brand or product name"}
                value={form.query}
                onChange={(e) => setForm({ ...form, query: e.target.value })}
              />
              <div className="flex gap-3 text-xs">
                {(["bluesky", "mastodon"] as const).map((p) => (
                  <label key={p} className="flex items-center gap-1.5 capitalize">
                    <input type="checkbox" checked={form[p]} onChange={(e) => setForm({ ...form, [p]: e.target.checked })} /> {p}
                  </label>
                ))}
              </div>
              <button className="btn btn-primary w-full justify-center" disabled={form.query.trim().length < 2}>
                <Plus size={14} /> Follow
              </button>
            </form>
          </Section>
          <Section title={`Following · ${watches.length}`}>
            {watches.length === 0 ? (
              <p className="text-xs text-[var(--color-mute)]">Start with your brand name, your main hashtag and one competitor.</p>
            ) : (
              <ul className="space-y-1.5">
                {watches.map((w) => {
                  const Icon = KIND_ICON[w.kind];
                  return (
                    <li key={w.id} className={`flex items-center gap-2 rounded-lg border p-2 text-xs ${filter === w.id ? "border-cyan-400/50 bg-cyan-400/5" : "border-[var(--color-line)]"}`}>
                      <Icon size={13} className="shrink-0 text-cyan-300" />
                      <button className="min-w-0 flex-1 text-left" onClick={() => setFilter(filter === w.id ? "" : w.id)} title={w.last_error || `Last checked ${timeAgo(w.last_run_at)}`}>
                        <span className={`block truncate font-medium ${w.enabled ? "" : "line-through opacity-60"}`}>{w.kind === "hashtag" ? "#" : ""}{w.query}</span>
                        <span className={`block text-[10px] ${w.last_error ? "text-amber-300" : "text-[var(--color-mute)]"}`}>{w.last_error ? "check failed" : w.platforms.join(" · ")}</span>
                      </button>
                      {w.new > 0 && <span className="rounded-full bg-cyan-400 px-1.5 text-[10px] font-bold text-black">{w.new}</span>}
                      <button className="text-[var(--color-mute)] hover:text-cyan-300" onClick={() => toggle(w)} aria-label={w.enabled ? "Pause" : "Resume"}>
                        {w.enabled ? <Check size={13} /> : <RefreshCw size={13} />}
                      </button>
                      <button className="text-[var(--color-mute)] hover:text-red-300" onClick={() => remove(w)} aria-label={`Stop following ${w.query}`}>
                        <Trash2 size={13} />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Section>
        </div>

        <section className="panel p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {([["new", "To handle"], ["done", "Handled"], ["rivals", "Competitors"]] as const).map(([id, label]) => (
              <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className={`rounded-lg px-3 py-1.5 text-xs ${tab === id ? "bg-cyan-400/15 text-cyan-200 ring-1 ring-cyan-400/30" : "text-[var(--color-mute)] hover:bg-white/5"}`}>
                {label}
              </button>
            ))}
            {filter && (
              <button className="chip ml-auto" onClick={() => setFilter("")}>
                {watchName(filter)} <X size={11} />
              </button>
            )}
          </div>
          {tab === "rivals" ? (
            rivals.length === 0 ? (
              <Empty>Follow a competitor account to see what works for them.</Empty>
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                {rivals.map((r) => (
                  <div key={r.watch_id} className="rounded-lg border border-[var(--color-line)] p-3">
                    <div className="flex items-center gap-2">
                      <User size={14} className="text-fuchsia-300" />
                      <span className="font-semibold">@{r.account}</span>
                      <span className="ml-auto text-xs text-[var(--color-mute)]">{r.posts} posts · avg {r.avg_score}</span>
                    </div>
                    <ol className="mt-2 space-y-2">
                      {r.best.map((b, i) => (
                        <li key={i} className="text-xs">
                          <p className="line-clamp-3">{b.text}</p>
                          <div className="mt-1 flex items-center gap-2 text-[var(--color-mute)]">
                            ♥ {b.likes} · ⟲ {b.reposts} · 💬 {b.replies}
                            {b.url && (
                              <a href={b.url} target="_blank" rel="noreferrer noopener" className="hover:text-cyan-300" aria-label="Open post">
                                <ExternalLink size={11} />
                              </a>
                            )}
                            <button className="ml-auto text-cyan-300 hover:underline" onClick={() => talkTo("edith", `EDITH, this post from a competitor did well:\n\n"${b.text}"\n\nWrite our own original post on a similar topic in our brand voice. Learn from its structure and hook, but don't copy its wording.`)}>
                              <Sparkles size={11} className="mr-1 inline" />
                              Learn from it
                            </button>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </div>
                ))}
              </div>
            )
          ) : mentions.length === 0 ? (
            <Empty>{watches.length ? "Nothing here right now. New posts are checked every 15 minutes." : "Follow a keyword, hashtag or account to start listening."}</Empty>
          ) : (
            <ul className="space-y-2">
              {mentions.map((m) => (
                <li key={m.id} className="rounded-lg border border-[var(--color-line)] p-3 text-sm" style={{ borderLeft: `3px solid ${CAT[m.category] || "#22d3ee"}` }}>
                  <div className="mb-1 flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-semibold">{m.author}</span>
                    <span className="chip" style={{ color: CAT[m.category], borderColor: `${CAT[m.category]}55` }}>{m.category}</span>
                    <span className="text-[var(--color-mute)]"><span className="capitalize">{m.platform}</span> · {watchName(m.watch_id)}</span>
                    <span className="ml-auto text-[var(--color-mute)]">{timeAgo(m.posted_at || m.created_at)}</span>
                  </div>
                  <p className="break-anywhere whitespace-pre-wrap">{m.text}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button className="btn !py-1 text-xs" onClick={() => talkTo("friday", `Friday, draft a ${m.platform} reply to this post by ${m.author}${m.platform === "bluesky" ? ` (reply_to: ${m.external_id})` : ""}:\n\n"${m.text}"\n\nKeep it short, helpful and in our brand voice.`)}>
                      <Reply size={12} /> Draft reply
                    </button>
                    {m.url && (
                      <a className="btn !py-1 text-xs" href={m.url} target="_blank" rel="noreferrer noopener">
                        <ExternalLink size={12} /> Open
                      </a>
                    )}
                    {tab === "new" ? (
                      <>
                        <button className="btn !py-1 text-xs" onClick={() => setStatus(m.id, "done")}>
                          <Check size={12} /> Handled
                        </button>
                        <button className="btn !py-1 text-xs" onClick={() => setStatus(m.id, "dismissed")}>
                          <X size={12} /> Ignore
                        </button>
                      </>
                    ) : (
                      <button className="btn !py-1 text-xs" onClick={() => setStatus(m.id, "new")}>
                        Back to “to handle”
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
