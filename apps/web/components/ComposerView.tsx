"use client";

import { CalendarPlus, Gauge, Plus, Save, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { nextPlanSlot, scoreDraft } from "@/lib/score";
import { useStark } from "@/lib/store";
import type { AnalyticsReport, ContentItem, PostingPlan, Snippet, SocialAccount } from "@/lib/types";
import { PostPreview } from "./PostPreview";
import { Section } from "./ui";

const PLATFORMS = ["bluesky", "mastodon", "x", "threads", "linkedin", "instagram", "facebook", "tiktok", "youtube", "telegram", "discord", "slack"];
const LANGS = ["Spanish", "French", "German", "Portuguese", "Italian", "Arabic", "Hindi", "Urdu", "Japanese", "Chinese", "Korean", "Indonesian", "Turkish"];
const NAMES: Record<string, string> = { bluesky: "Bluesky", mastodon: "Mastodon", x: "X", threads: "Threads", linkedin: "LinkedIn", instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok", youtube: "YouTube", telegram: "Telegram", discord: "Discord", slack: "Slack" };
const REPLIES = [
  ["everyone", "Everyone can reply"],
  ["followers", "Only my followers"],
  ["following", "Only people I follow"],
  ["mentioned", "Only people I mention"],
  ["nobody", "Nobody"],
] as const;

/** Write a post by hand: live preview per platform, engagement score, category, reply control, queue. */
export function ComposerView({ talkTo }: { talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify } = useStark();
  const [platform, setPlatform] = useState("bluesky");
  const [text, setText] = useState("");
  const [thread, setThread] = useState<string[]>([]);
  const [category, setCategory] = useState("");
  const [reply, setReply] = useState("everyone");
  const [accounts, setAccounts] = useState<SocialAccount[]>([]);
  const [plan, setPlan] = useState<PostingPlan | null>(null);
  const [report, setReport] = useState<AnalyticsReport | null>(null);
  const [snips, setSnips] = useState<Snippet[]>([]);
  const [queue, setQueue] = useState<ContentItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [utm, setUtm] = useState(false);

  useEffect(() => {
    client.get<{ accounts: SocialAccount[] }>("/api/social/accounts").then((r) => setAccounts(r.accounts)).catch(() => {});
    client.get<PostingPlan>("/api/plan").then(setPlan).catch(() => {});
    client.get<AnalyticsReport>("/api/social/analytics").then(setReport).catch(() => {});
    client.get<{ snippets: Snippet[] }>("/api/library").then((r) => setSnips(r.snippets)).catch(() => {});
    client.get<{ items: ContentItem[] }>("/api/social/queue?status=scheduled&limit=500").then((r) => setQueue(r.items)).catch(() => {});
  }, [client]);

  const limit = accounts.find((a) => a.platform === platform)?.char_limit;
  const history = useMemo(() => (report?.posts ?? []).filter((p) => p.platform === platform || (report?.posts ?? []).filter((x) => x.platform === platform).length < 5), [report, platform]);
  const score = useMemo(() => scoreDraft(text, history), [text, history]);
  const live = accounts.find((a) => a.platform === platform)?.mode === "connected";
  const color = score.score >= 65 ? "#34d399" : score.score >= 45 ? "#fbbf24" : "#f87171";

  const insert = (body: string) => setText((t) => (t ? `${t.trimEnd()}\n\n${body}` : body));
  const reset = () => {
    setText("");
    setThread([]);
  };

  async function save(): Promise<ContentItem | null> {
    setBusy(true);
    try {
      let item = await client.post<ContentItem>("/api/social/drafts", { platform, text, thread: thread.filter((t) => t.trim()), category, reply_control: platform === "bluesky" ? reply : null });
      if (utm && /https?:\/\//.test(text)) item = await client.post<ContentItem>(`/api/social/items/${item.id}/utm`);
      notify(item.check.verdict === "fail" ? "warn" : "success", item.check.verdict === "fail" ? "Saved, but the policy check failed: fix it in Content." : "Draft saved in Content.");
      return item;
    } catch (e: any) {
      notify("error", e.message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function addToQueue() {
    const when = nextPlanSlot(plan?.slots ?? [], queue.filter((q) => q.scheduled_for).map((q) => new Date(q.scheduled_for!)));
    if (!when) return notify("warn", "No free time slot in the next 4 weeks. Add slots in Calendar → Posting plan.");
    const item = await save();
    if (!item || item.check.verdict === "fail") return;
    try {
      await client.post(`/api/social/items/${item.id}/schedule`, { fingerprint: item.fingerprint, when: when.toISOString(), auto: false });
      setQueue((q) => [...q, { ...item, scheduled_for: when.toISOString(), status: "scheduled" }]);
      notify("success", `Queued for ${when.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}. Approve it in Content to let it go out on its own.`);
      reset();
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="panel p-4">
        <div className="hud-label text-cyan-300">Composer</div>
        <h1 className="holo-text text-xl font-semibold">Write a post</h1>
        <p className="text-xs text-[var(--color-mute)]">Write it yourself with a live preview and a score based on your own results, then save it or put it in the next free time slot.</p>
      </section>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1.15fr_1fr]">
        <section className="panel space-y-3 p-4">
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Platform">
            {PLATFORMS.map((p) => (
              <button key={p} role="radio" aria-checked={platform === p} onClick={() => setPlatform(p)} className={`chip ${platform === p ? "!border-cyan-400/60 !text-cyan-200" : ""}`}>
                {NAMES[p]}
                {accounts.find((a) => a.platform === p)?.mode === "connected" && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" title="Connected" />}
              </button>
            ))}
          </div>
          <textarea className="input min-h-[150px]" aria-label="Post text" placeholder="What do you want to say?" value={text} onChange={(e) => setText(e.target.value)} />
          {thread.map((t, i) => (
            <div key={i} className="flex gap-2">
              <textarea className="input min-h-[80px]" aria-label={`Thread part ${i + 2}`} value={t} onChange={(e) => setThread((th) => th.map((x, j) => (j === i ? e.target.value : x)))} />
              <button className="text-[var(--color-mute)] hover:text-red-300" onClick={() => setThread((th) => th.filter((_, j) => j !== i))} aria-label={`Remove part ${i + 2}`}>
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn !py-1 text-xs" onClick={() => setThread((th) => [...th, ""])}>
              <Plus size={12} /> Add thread part
            </button>
            {snips.length > 0 && (
              <select className="input !w-auto !py-1 text-xs" aria-label="Insert from Library" value="" onChange={(e) => e.target.value && insert(snips.find((s) => s.id === e.target.value)!.body)}>
                <option value="">Insert from Library…</option>
                {snips.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.kind === "hashtags" ? "#" : s.kind === "signature" ? "✍ " : "▤ "}
                    {s.name}
                  </option>
                ))}
              </select>
            )}
            <select className="input !w-auto !py-1 text-xs" aria-label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">No category</option>
              {plan?.categories.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name}
                </option>
              ))}
            </select>
            {platform === "bluesky" && (
              <select className="input !w-auto !py-1 text-xs" aria-label="Who can reply" value={reply} onChange={(e) => setReply(e.target.value)}>
                {REPLIES.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="flex flex-wrap gap-2 border-t border-[var(--color-line)] pt-3">
            <button className="btn" disabled={busy || !text.trim()} onClick={() => save().then((i) => i && reset())}>
              <Save size={14} /> Save draft
            </button>
            <button className="btn btn-primary" disabled={busy || !text.trim()} onClick={addToQueue}>
              <CalendarPlus size={14} /> Add to queue
            </button>
            <button className="btn" disabled={!text.trim()} onClick={() => talkTo("edith", `EDITH, improve this ${NAMES[platform]} post without changing its meaning, then save it as a draft:\n\n${text}`)}>
              <Sparkles size={14} /> Improve with E.D.I.T.H.
            </button>
            <select
              className="input !w-auto text-xs"
              aria-label="Translate"
              value=""
              disabled={!text.trim()}
              onChange={(e) => e.target.value && talkTo("edith", `EDITH, translate this ${NAMES[platform]} post into ${e.target.value}. Keep the meaning, tone, links, @mentions and hashtags (translate hashtags only if a common local one exists), stay within ${NAMES[platform]}'s length limit, and save it as a new draft:\n\n${text}`)}
            >
              <option value="">Translate into…</option>
              {LANGS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1.5 text-xs" title="Adds utm_source, utm_medium and utm_campaign to links to your own sites, so your website analytics shows which post brought each visit">
              <input type="checkbox" checked={utm} onChange={(e) => setUtm(e.target.checked)} /> Tag links for click tracking
            </label>
          </div>
          {!live && <p className="text-xs text-amber-300">{NAMES[platform]} isn&apos;t connected: publishing will be a simulation, and you can copy the text from Content.</p>}
        </section>

        <div className="space-y-4">
          <Section title="Predicted engagement" right={<Gauge size={15} style={{ color }} />}>
            <div className="flex items-center gap-4">
              <div className="relative h-20 w-20 shrink-0">
                <svg viewBox="0 0 36 36" className="h-full w-full -rotate-90">
                  <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--color-line)" strokeWidth="3" />
                  <circle cx="18" cy="18" r="15.5" fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeDasharray={`${(score.score / 100) * 97.4} 97.4`} style={{ transition: "stroke-dasharray .5s" }} />
                </svg>
                <span className="absolute inset-0 flex items-center justify-center font-mono text-xl font-semibold" style={{ color }}>
                  {score.score}
                </span>
              </div>
              <div className="min-w-0 text-xs">
                <p className="text-[var(--color-mute)]">
                  {score.basis === "history" ? `Compared with your average (50), from ${score.measured} measured posts.` : "General guidance: the score learns from your own results after 5 measured posts."}
                </p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4">
                  {score.tips.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                  {!score.tips.length && text.trim() && (score.score >= 60 ? <li className="text-emerald-300">Looks strong for your audience.</li> : <li>About your usual level: nothing obvious to change.</li>)}
                </ul>
              </div>
            </div>
          </Section>
          <Section title={`Preview · ${NAMES[platform]}`}>
            <PostPreview platform={platform} text={text} thread={thread} limit={limit} />
            <p className="mt-2 text-[11px] text-[var(--color-mute)]">An approximation of the platform&apos;s layout; the policy check runs when you save.</p>
          </Section>
        </div>
      </div>
    </div>
  );
}
