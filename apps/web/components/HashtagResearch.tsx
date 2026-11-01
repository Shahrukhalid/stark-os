"use client";

import { ExternalLink, Search, Sparkles } from "lucide-react";
import { useState } from "react";
import { useStark } from "@/lib/store";
import { Section } from "./ui";

type Report = {
  tag: string;
  found: number;
  last_24h: number;
  last_7d: number;
  avg_engagement: number;
  by_platform: Record<string, number>;
  sentiment: Record<string, number>;
  related: { tag: string; count: number }[];
  top_posts: { platform: string; author: string; text: string; url: string | null; likes: number; reposts: number; replies: number }[];
  advice: string;
  errors: string[];
};

/** Live research of one hashtag on Bluesky and Mastodon. */
export function HashtagResearch({ talkTo }: { talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify } = useStark();
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [r, setR] = useState<Report | null>(null);

  async function run(e?: React.FormEvent, t = tag) {
    e?.preventDefault();
    if (!t.trim()) return;
    setBusy(true);
    try {
      setR(await client.get<Report>(`/api/growth/hashtag?tag=${encodeURIComponent(t.trim())}`));
      setTag(t.replace(/^#/, ""));
    } catch (err: any) {
      notify("error", err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Hashtag research" right={<Search size={15} className="text-cyan-300" />}>
      <form onSubmit={run} className="mb-3 flex gap-2">
        <input className="input flex-1" placeholder="#hashtag" value={tag} onChange={(e) => setTag(e.target.value)} aria-label="Hashtag" />
        <button className="btn btn-primary" disabled={busy || !tag.trim()}>{busy ? "Searching…" : "Research"}</button>
      </form>
      {r && (
        <div className="space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[["Last 24 h", r.last_24h], ["Last 7 days", r.last_7d], ["Avg engagement", r.avg_engagement], ["Posts found", r.found]].map(([l, v]) => (
              <div key={l as string} className="rounded-lg border border-[var(--color-line)] p-2">
                <div className="text-lg font-semibold">{v}</div>
                <div className="text-xs text-[var(--color-mute)]">{l}</div>
              </div>
            ))}
          </div>
          <p className="text-cyan-200">{r.advice}</p>
          <p className="text-xs text-[var(--color-mute)]">
            Bluesky {r.by_platform.bluesky ?? 0} · Mastodon {r.by_platform.mastodon ?? 0} · mood: {r.sentiment.positive ?? 0} happy, {r.sentiment.negative ?? 0} unhappy
          </p>
          {r.related.length > 0 && (
            <div className="flex flex-wrap gap-2" aria-label="Related hashtags">
              {r.related.map((t) => (
                <button key={t.tag} className="chip !text-[var(--color-ink)]" onClick={() => run(undefined, t.tag)} title="Research this one">
                  {t.tag} <span className="text-[var(--color-mute)]">{t.count}</span>
                </button>
              ))}
            </div>
          )}
          {r.top_posts.length > 0 && (
            <ol className="space-y-2">
              {r.top_posts.map((p, i) => (
                <li key={i} className="rounded-lg border border-[var(--color-line)] p-2 text-xs">
                  <p className="line-clamp-3">{p.text}</p>
                  <div className="mt-1 flex items-center gap-2 text-[var(--color-mute)]">
                    {p.author} · ♥ {p.likes} · ⟲ {p.reposts} · 💬 {p.replies}
                    {p.url && <a href={p.url} target="_blank" rel="noreferrer noopener" aria-label="Open post"><ExternalLink size={11} /></a>}
                  </div>
                </li>
              ))}
            </ol>
          )}
          {r.found > 0 && (
            <button className="btn" onClick={() => talkTo("edith", `EDITH, write a post for #${r.tag} in our brand voice. What works there right now:\n\n${r.top_posts.slice(0, 3).map((p) => `- "${p.text.slice(0, 200)}"`).join("\n")}\n\nLearn from the hooks and structure, don't copy wording. Related hashtags people use: ${r.related.slice(0, 5).map((t) => t.tag).join(" ")}.`)}>
              <Sparkles size={13} className="mr-1 inline" /> Write a post for #{r.tag}
            </button>
          )}
          {r.errors.length > 0 && <p className="text-xs text-amber-300">{r.errors.join(" · ")}</p>}
        </div>
      )}
    </Section>
  );
}
