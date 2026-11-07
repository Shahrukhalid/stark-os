"use client";

import { Ban, Check, ChevronLeft, ExternalLink, PauseCircle, Pencil, PlayCircle, Plus, Radar, RefreshCw, Rocket, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStark } from "@/lib/store";
import type { Campaign, CampaignDetail, CampaignSource, ContentItem, RunReport, TrustLevel } from "@/lib/types";
import { Empty, Section, timeAgo } from "./ui";

const PLATFORMS: { id: string; name: string }[] = [
  { id: "bluesky", name: "Bluesky" },
  { id: "mastodon", name: "Mastodon" },
  { id: "x", name: "X" },
  { id: "threads", name: "Threads" },
  { id: "linkedin", name: "LinkedIn" },
  { id: "facebook", name: "Facebook Page" },
];

const TRUST: Record<TrustLevel, { label: string; short: string; help: string; color: string }> = {
  copilot: {
    label: "Co-pilot",
    short: "you approve",
    help: "Autopilot researches and writes. Every post waits for you; approve a whole batch with one click.",
    color: "!text-cyan-300",
  },
  veto: {
    label: "Autopilot with veto",
    short: "goes out unless you cancel",
    help: "Posts that pass every check go out automatically after a waiting period in which you can cancel them. Anything borderline still waits for you.",
    color: "!text-amber-300",
  },
  auto: {
    label: "Full auto",
    short: "short cancel window",
    help: "Like veto with a shorter window. Unlocks after a run of clean posts; any veto drops the campaign back to veto.",
    color: "!text-emerald-300",
  },
};

const SOURCE_LABEL: Record<CampaignSource["type"], { label: string; placeholder: string }> = {
  rss: { label: "RSS / Atom feed", placeholder: "https://example.com/feed.xml" },
  hn: { label: "Hacker News search", placeholder: "ai agents" },
  reddit: { label: "Subreddit (top today)", placeholder: "MachineLearning" },
  search: { label: "Web news search", placeholder: "open source ai" },
};

interface ListResponse {
  campaigns: Campaign[];
  auto_unlock: number;
  queue_paused: boolean;
  emergency_stop: boolean;
  can_write: boolean;
  search_configured: boolean;
}

const splitList = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

/** Autopilot: campaigns that research, write, check and schedule posts on their own, within the limits you set. */
export function AutopilotView() {
  const { client, notify, eventSeq } = useStark();
  const [data, setData] = useState<ListResponse | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [editing, setEditing] = useState<Campaign | "new" | null>(null);

  const reqId = useRef(0);
  const load = useCallback(async () => {
    const id = ++reqId.current;
    try {
      const res = await client.get<ListResponse>("/api/autopilot/campaigns");
      if (id === reqId.current) setData(res);
    } catch (e: any) {
      notify("error", e.message);
    }
  }, [client, notify]);

  const seq = (eventSeq.autopilot ?? 0) + (eventSeq.content ?? 0);
  useEffect(() => {
    load();
  }, [load, seq]);

  if (editing) {
    return (
      <CampaignForm
        initial={editing === "new" ? null : editing}
        searchConfigured={!!data?.search_configured}
        onDone={(saved) => {
          setEditing(null);
          load();
          if (saved) setOpen(saved.id);
        }}
      />
    );
  }
  if (open) return <CampaignPage id={open} onBack={() => { setOpen(null); load(); }} onEdit={(c) => setEditing(c)} />;

  const campaigns = data?.campaigns ?? [];
  return (
    <div className="space-y-4">
      <Section
        title="Autopilot"
        right={
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            <Plus size={14} /> New campaign
          </button>
        }
      >
        <p className="text-sm text-[var(--color-mute)]">
          Set a campaign once: topics, sources, platforms and posting times. Autopilot finds fresh stories, picks keywords and hashtags,
          writes a post for each platform, fact-checks it against the source and schedules it. <b className="text-[var(--color-ink)]">How much it posts on its own is
          up to you</b>, and it pauses itself if something looks wrong.
        </p>
        {data && !data.can_write && (
          <p className="mt-2 text-xs text-amber-300">No AI model is configured, so Autopilot can research but not write. Add your free OpenRouter key in Settings.</p>
        )}
        {(data?.queue_paused || data?.emergency_stop) && (
          <p className="mt-2 flex items-center gap-1 text-xs text-red-300">
            <PauseCircle size={13} /> {data.emergency_stop ? "Emergency stop is engaged" : "The content queue is paused"}: Autopilot is not running.
          </p>
        )}
      </Section>

      {data && campaigns.length === 0 ? (
        <Empty>
          No campaigns yet. A campaign might be: “Post about open source AI to Bluesky and Mastodon at 9:00 and 17:00, from Hacker News and two blogs.”
          <div className="mt-3">
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              <Rocket size={14} /> Create your first campaign
            </button>
          </div>
        </Empty>
      ) : (
        <ul className="grid gap-3 lg:grid-cols-2">
          {campaigns.map((c) => (
            <CampaignCard key={c.id} c={c} onOpen={() => setOpen(c.id)} onChange={load} />
          ))}
        </ul>
      )}
    </div>
  );
}

function CampaignCard({ c, onOpen, onChange }: { c: Campaign; onOpen: () => void; onChange: () => void }) {
  const { client, notify } = useStark();
  const [busy, setBusy] = useState(false);
  const t = TRUST[c.trust_level];

  async function act(fn: () => Promise<any>, ok: (r: any) => string) {
    setBusy(true);
    try {
      notify("success", ok(await fn()));
      onChange();
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="panel p-4" data-testid="campaign-card">
      <div className="flex flex-wrap items-center gap-2">
        <button className="min-w-0 flex-1 text-left font-medium hover:underline" onClick={onOpen}>{c.name}</button>
        <span className={`chip ${t.color}`} title={t.help}>{t.label}</span>
        {c.paused && <span className="chip !text-red-300"><PauseCircle size={12} className="mr-1 inline" />paused</span>}
      </div>
      {c.paused && c.pause_reason && <p className="mt-2 text-xs text-red-300">{c.pause_reason}</p>}
      <div className="mt-3 grid grid-cols-4 gap-2 text-center">
        <Stat n={c.counts.awaiting} label="need you" warn={c.counts.awaiting > 0} />
        <Stat n={c.counts.going_out} label="going out" />
        <Stat n={c.counts.published_24h} label="posted 24h" />
        <Stat n={c.counts.rejected_24h} label="blocked 24h" />
      </div>
      <p className="mt-3 text-xs text-[var(--color-mute)]">
        {c.platforms.map((p) => PLATFORMS.find((x) => x.id === p)?.name || p).join(", ")} · {c.post_times.join(", ")} ({c.timezone}) ·{" "}
        {c.last_run_at ? `last run ${timeAgo(c.last_run_at)}` : "not run yet"}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button className="btn btn-primary !py-1 text-xs" onClick={onOpen}>Open</button>
        <button
          className="btn !py-1 text-xs"
          disabled={busy || c.paused}
          onClick={() => act(() => client.post<RunReport>(`/api/autopilot/campaigns/${c.id}/run`), runSummary)}
        >
          <Radar size={13} /> {busy ? "Running…" : "Run now"}
        </button>
        <button
          className="btn !py-1 text-xs"
          disabled={busy}
          onClick={() => act(() => client.post(`/api/autopilot/campaigns/${c.id}/pause?paused=${!c.paused}`), () => (c.paused ? "Campaign resumed" : "Campaign paused"))}
        >
          {c.paused ? <><PlayCircle size={13} /> Resume</> : <><PauseCircle size={13} /> Pause</>}
        </button>
      </div>
    </li>
  );
}

function Stat({ n, label, warn = false }: { n: number; label: string; warn?: boolean }) {
  return (
    <div className="rounded-lg border border-[var(--color-line)] px-1 py-2">
      <div className={`text-lg font-semibold ${warn ? "text-amber-300" : ""}`}>{n}</div>
      <div className="text-[10.5px] text-[var(--color-mute)]">{label}</div>
    </div>
  );
}

function runSummary(r: RunReport): string {
  if (r.skipped) return `Skipped: ${r.skipped}`;
  const parts = [`${r.new_stories} new stor${r.new_stories === 1 ? "y" : "ies"}`, `${r.drafted} post${r.drafted === 1 ? "" : "s"} written`];
  if (r.awaiting) parts.push(`${r.awaiting} waiting for you`);
  if (r.scheduled) parts.push(`${r.scheduled} scheduled`);
  if (r.rejected) parts.push(`${r.rejected} blocked by checks`);
  return parts.join(", ") + (r.errors.length ? ` (${r.errors.length} problem${r.errors.length === 1 ? "" : "s"}: see History)` : "");
}

type Tab = "needs" | "out" | "research" | "keywords" | "history";

function CampaignPage({ id, onBack, onEdit }: { id: string; onBack: () => void; onEdit: (c: Campaign) => void }) {
  const { client, notify, eventSeq } = useStark();
  const [c, setC] = useState<CampaignDetail | null>(null);
  const [tab, setTab] = useState<Tab>("needs");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [halted, setHalted] = useState<string | null>(null);

  const reqId = useRef(0);
  const load = useCallback(async () => {
    const rid = ++reqId.current;
    try {
      const [res, list] = await Promise.all([
        client.get<CampaignDetail>(`/api/autopilot/campaigns/${id}`),
        client.get<ListResponse>("/api/autopilot/campaigns"),
      ]);
      if (rid !== reqId.current) return;
      setC(res);
      setHalted(list.emergency_stop ? "Emergency stop is engaged" : list.queue_paused ? "The content queue is paused (fire suppression)" : null);
    } catch (e: any) {
      notify("error", e.message);
    }
  }, [client, id, notify]);

  const seq = (eventSeq.autopilot ?? 0) + (eventSeq.content ?? 0);
  useEffect(() => {
    load();
  }, [load, seq]);

  const mine = useMemo(() => (c?.items ?? []).filter((i) => i.autopilot), [c]);
  const needs = mine.filter((i) => ["scheduled", "draft"].includes(i.status) && !i.auto_publish);
  const out = mine.filter((i) => i.status === "scheduled" && i.auto_publish);
  const done = mine.filter((i) => ["published", "rejected", "failed"].includes(i.status));

  async function act(fn: () => Promise<any>, ok: (r: any) => string) {
    setBusy(true);
    try {
      notify("success", ok(await fn()));
      setPicked(new Set());
      load();
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy(false);
    }
  }

  function approve(items: ContentItem[]) {
    return act(
      () => client.post("/api/autopilot/approve", { items: items.map((i) => ({ id: i.id, fingerprint: i.fingerprint })) }),
      (r) => `${r.approved} post${r.approved === 1 ? "" : "s"} approved` + (r.approved < items.length ? ` (${items.length - r.approved} changed: refresh and check them)` : ""),
    );
  }

  if (!c) return <Empty>Loading…</Empty>;
  const t = TRUST[c.trust_level];
  const tabs: { id: Tab; label: string; n?: number }[] = [
    { id: "needs", label: "Needs you", n: needs.length },
    { id: "out", label: "Going out", n: out.length },
    { id: "research", label: "Research", n: c.research.filter((r) => r.status === "new").length },
    { id: "keywords", label: "Keywords & SEO" },
    { id: "history", label: "History" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <button className="btn" onClick={onBack}><ChevronLeft size={14} /> Campaigns</button>
        <h2 className="min-w-0 flex-1 truncate text-lg font-semibold">{c.name}</h2>
        <button className="btn" disabled={busy || c.paused || !!halted} onClick={() => act(() => client.post<RunReport>(`/api/autopilot/campaigns/${c.id}/run`), runSummary)}>
          <Radar size={14} /> {busy ? "Working…" : "Run now"}
        </button>
        <button className="btn" disabled={busy} onClick={() => act(() => client.post(`/api/autopilot/campaigns/${c.id}/pause?paused=${!c.paused}`), () => (c.paused ? "Resumed" : "Paused"))}>
          {c.paused ? <><PlayCircle size={14} /> Resume</> : <><PauseCircle size={14} /> Pause</>}
        </button>
        <button className="btn" onClick={() => onEdit(c)}><Pencil size={14} /> Settings</button>
        {confirmDelete ? (
          <span className="inline-flex gap-1">
            <button className="btn btn-danger" onClick={() => act(() => client.del(`/api/autopilot/campaigns/${c.id}`), (r) => `Deleted; ${r.cancelled_posts} pending post(s) cancelled`).then(onBack)}>
              <Trash2 size={14} /> Yes, delete
            </button>
            <button className="btn" onClick={() => setConfirmDelete(false)}>Keep</button>
          </span>
        ) : (
          <button className="btn btn-danger" onClick={() => setConfirmDelete(true)} aria-label="Delete campaign"><Trash2 size={14} /></button>
        )}
      </div>

      {halted && (
        <div className="panel flex items-start gap-2 !border-red-400/50 p-3 text-sm" role="status">
          <PauseCircle size={16} className="mt-0.5 text-red-300" />
          <span>{halted}: Autopilot does not run and nothing is posted. Resume the queue on the Content page.</span>
        </div>
      )}
      {c.paused && (
        <div className="panel flex items-start gap-2 !border-red-400/50 p-3 text-sm" role="status">
          <PauseCircle size={16} className="mt-0.5 text-red-300" />
          <span>{c.pause_reason || "Paused."} Nothing from this campaign goes out until you resume it.</span>
        </div>
      )}

      <Section title="Trust level">
        <div className="grid gap-2 sm:grid-cols-3">
          {(Object.keys(TRUST) as TrustLevel[]).map((lvl) => {
            const locked = lvl === "auto" && !c.auto_unlocked && c.trust_level !== "auto";
            return (
              <button
                key={lvl}
                className={`rounded-lg border p-3 text-left text-xs ${c.trust_level === lvl ? "border-cyan-400/70 bg-cyan-400/10" : "border-[var(--color-line)] hover:border-cyan-400/40"} ${locked ? "opacity-50" : ""}`}
                disabled={busy || locked || c.trust_level === lvl}
                aria-pressed={c.trust_level === lvl}
                onClick={() => act(() => client.patch(`/api/autopilot/campaigns/${c.id}`, { trust_level: lvl }), () => `Trust level: ${TRUST[lvl].label}`)}
              >
                <div className={`mb-1 text-sm font-medium ${TRUST[lvl].color.replace("!", "")}`}>{TRUST[lvl].label}</div>
                <div className="text-[var(--color-mute)]">{TRUST[lvl].help}</div>
                {lvl === "veto" && <div className="mt-1 text-[var(--color-mute)]">Cancel window: {c.veto_minutes} min.</div>}
                {locked && <div className="mt-1 text-amber-300">Locked: {c.streak} of {c.auto_unlock_needs} clean posts so far.</div>}
              </button>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-[var(--color-mute)]">Now: <b className="text-[var(--color-ink)]">{t.label}</b> ({t.short}). Sensitive news (deaths, disasters, attacks, elections) always waits for you.</p>
      </Section>

      <div className="flex flex-wrap gap-1" role="tablist">
        {tabs.map((x) => (
          <button key={x.id} role="tab" aria-selected={tab === x.id} className={`btn !py-1 text-xs ${tab === x.id ? "btn-primary" : ""}`} onClick={() => setTab(x.id)}>
            {x.label}{x.n ? ` (${x.n})` : ""}
          </button>
        ))}
        <button className="btn ml-auto !py-1 text-xs" onClick={load} aria-label="Refresh"><RefreshCw size={13} /></button>
      </div>

      {tab === "needs" && (
        <Section
          title="Waiting for your approval"
          right={needs.length > 0 && (
            <div className="flex gap-2">
              <button className="btn !py-1 text-xs" disabled={busy || picked.size === 0} onClick={() => approve(needs.filter((i) => picked.has(i.id)))}>
                <Check size={13} /> Approve selected ({picked.size})
              </button>
              <button className="btn btn-primary !py-1 text-xs" disabled={busy} onClick={() => approve(needs.filter((i) => i.check?.verdict !== "fail"))}>
                <Check size={13} /> Approve all
              </button>
            </div>
          )}
        >
          {needs.length === 0 ? <Empty>Nothing waiting. New drafts appear here after each run.</Empty> : (
            <ul className="space-y-3">
              {needs.map((i) => (
                <PostRow key={i.id} item={i} busy={busy} picked={picked.has(i.id)} onPick={(v) => setPicked((s) => { const n = new Set(s); if (v) n.add(i.id); else n.delete(i.id); return n; })}
                  onVeto={() => act(() => client.post(`/api/autopilot/items/${i.id}/veto`), () => "Discarded")} vetoLabel="Discard" />
              ))}
            </ul>
          )}
        </Section>
      )}

      {tab === "out" && (
        <Section title="Going out automatically">
          {out.length === 0 ? <Empty>Nothing scheduled to go out on its own.</Empty> : (
            <ul className="space-y-3">
              {out.map((i) => (
                <PostRow key={i.id} item={i} busy={busy} onVeto={() => act(() => client.post(`/api/autopilot/items/${i.id}/veto`), () => "Cancelled: it will not be posted")} vetoLabel="Cancel this post" />
              ))}
            </ul>
          )}
          {done.length > 0 && (
            <>
              <div className="hud-label mb-2 mt-5 text-[var(--color-mute)]">Recent results</div>
              <ul className="space-y-2">
                {done.slice(0, 15).map((i) => <PostRow key={i.id} item={i} busy={busy} compact />)}
              </ul>
            </>
          )}
        </Section>
      )}

      {tab === "research" && (
        <Section title="Stories found">
          {c.research.length === 0 ? <Empty>No stories yet. Use “Run now”, or wait for the next run.</Empty> : (
            <ul className="space-y-2">
              {c.research.map((r) => (
                <li key={r.id} className="rounded-lg border border-[var(--color-line)] p-2 text-sm">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className={`chip ${r.status === "used" ? "!text-emerald-300" : r.status === "skipped" ? "!text-[var(--color-mute)]" : "!text-cyan-300"}`}>{r.status === "new" ? "candidate" : r.status}</span>
                    <span className="chip">score {Math.round(r.score)}</span>
                    <span className="text-[var(--color-mute)]">{r.source} · {timeAgo(r.published_at || r.created_at)}</span>
                  </div>
                  <a className="mt-1 inline-flex items-center gap-1 hover:underline" href={/^https?:\/\//i.test(r.url) ? r.url : undefined} target="_blank" rel="noreferrer noopener">
                    {r.title} <ExternalLink size={11} />
                  </a>
                  {r.keywords.length > 0 && <div className="mt-1 text-xs text-[var(--color-mute)]">keywords: {r.keywords.join(", ")}</div>}
                  {r.note && <div className="mt-1 text-xs text-[var(--color-mute)]">{r.note}</div>}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}

      {tab === "keywords" && (
        <Section title="Keywords and hashtags">
          <p className="mb-3 text-xs text-[var(--color-mute)]">
            Autopilot adds the best-performing hashtags that match each story (within each platform&apos;s limit) and keeps learning from likes, reposts and replies
            on connected accounts. Keywords without data yet still get tried.
          </p>
          {c.keywords_table.length === 0 ? <Empty>Add keywords in Settings.</Empty> : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-[var(--color-mute)]">
                  <tr><th className="py-1 pr-3">Keyword</th><th className="pr-3">Hashtag</th><th className="pr-3">Posts</th><th className="pr-3">Measured</th><th>Avg engagement</th></tr>
                </thead>
                <tbody>
                  {c.keywords_table.map((k) => (
                    <tr key={k.keyword} className="border-t border-[var(--color-line)]">
                      <td className="py-1.5 pr-3">{k.keyword}</td>
                      <td className="pr-3 font-mono text-xs">{k.hashtag || "–"}</td>
                      <td className="pr-3">{k.posts}</td>
                      <td className="pr-3">{k.measured}</td>
                      <td>{k.avg_engagement ?? "no data yet"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {tab === "history" && (
        <Section title="Recent runs">
          {c.history.length === 0 ? <Empty>No runs yet.</Empty> : (
            <ul className="space-y-2 text-sm">
              {c.history.map((h) => (
                <li key={h.at} className="rounded-lg border border-[var(--color-line)] p-2">
                  <div className="text-xs text-[var(--color-mute)]">{new Date(h.at).toLocaleString()}</div>
                  <div>{runSummary(h)}</div>
                  {h.errors.length > 0 && (
                    <ul className="mt-1 list-disc pl-5 text-xs text-amber-200">{h.errors.map((e) => <li key={e} className="break-anywhere">{e}</li>)}</ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Section>
      )}
    </div>
  );
}

function PostRow({ item: i, busy, picked, onPick, onVeto, vetoLabel, compact = false }: {
  item: ContentItem; busy: boolean; picked?: boolean; onPick?: (v: boolean) => void; onVeto?: () => void; vetoLabel?: string; compact?: boolean;
}) {
  const meta = i.autopilot!;
  const name = PLATFORMS.find((p) => p.id === i.platform)?.name || i.platform;
  const failing = i.check?.verdict === "fail";
  return (
    <li className="rounded-lg border border-[var(--color-line)] bg-black/20 p-3" data-testid="autopilot-post">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        {onPick && (
          <input type="checkbox" checked={!!picked} disabled={failing} onChange={(e) => onPick(e.target.checked)} aria-label={`Select ${name} post`} />
        )}
        <span className="chip">{name}</span>
        {i.simulated && <span className="chip !text-amber-300">{i.status === "published" ? "SIMULATED" : "simulated platform"}</span>}
        <span className={`chip ${meta.gate.verdict === "pass" ? "!text-emerald-300" : meta.gate.verdict === "review" ? "!text-amber-300" : "!text-red-300"}`}>
          checks {meta.gate.verdict === "pass" ? "passed" : meta.gate.verdict === "review" ? "need a look" : "blocked"}
        </span>
        {meta.fact_check && <span className={`chip ${meta.fact_check.supported ? "!text-emerald-300" : "!text-amber-300"}`}>{meta.fact_check.supported ? "fact-checked" : "fact-check: problems"}</span>}
        {i.status !== "scheduled" && <span className="chip">{i.status}</span>}
        {i.scheduled_for && i.status === "scheduled" && (
          <span className="text-[var(--color-mute)]">{i.auto_publish ? "goes out" : "planned for"} {new Date(i.scheduled_for).toLocaleString()} ({timeAgo(i.scheduled_for)})</span>
        )}
      </div>
      <p className={`break-anywhere whitespace-pre-wrap ${compact ? "text-xs text-[var(--color-mute)]" : "text-sm"}`}>{compact ? i.text.slice(0, 160) : i.text}</p>
      {!compact && (
        <div className="mt-2 text-xs text-[var(--color-mute)]">
          Source:{" "}
          <a className="text-cyan-300 hover:underline" href={/^https?:\/\//i.test(meta.source_url) ? meta.source_url : undefined} target="_blank" rel="noreferrer noopener">
            {meta.source_title}
          </a>{" "}
          ({meta.source})
          {meta.keywords.length > 0 && <> · keywords: {meta.keywords.join(", ")}</>}
        </div>
      )}
      {!compact && meta.gate.reasons.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs">
          {meta.gate.reasons.map((r, n) => <li key={n} className={r.level === "reject" ? "text-red-300" : "text-amber-200"}>{r.message}</li>)}
        </ul>
      )}
      {i.error && <p className="mt-1 text-xs text-red-300">{i.error}</p>}
      {meta.engagement && <p className="mt-1 text-xs text-[var(--color-mute)]">{Object.entries(meta.engagement).map(([k, v]) => `${v} ${k}`).join(" · ")}</p>}
      {i.external_url && /^https?:\/\//i.test(i.external_url) && (
        <a className="mt-1 inline-flex items-center gap-1 text-xs text-cyan-300 hover:underline" href={i.external_url} target="_blank" rel="noreferrer noopener">view post <ExternalLink size={11} /></a>
      )}
      {onVeto && (
        <div className="mt-2">
          <button className="btn btn-danger !py-1 text-xs" disabled={busy} onClick={onVeto}><Ban size={13} /> {vetoLabel}</button>
        </div>
      )}
    </li>
  );
}

function CampaignForm({ initial, searchConfigured, onDone }: { initial: Campaign | null; searchConfigured: boolean; onDone: (saved: Campaign | null) => void }) {
  const { client, notify } = useStark();
  const browserTz = typeof Intl !== "undefined" ? Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" : "UTC";
  const [f, setF] = useState({
    name: initial?.name ?? "",
    topics: (initial?.topics ?? []).join(", "),
    keywords: (initial?.keywords ?? []).join(", "),
    avoid: (initial?.avoid_terms ?? []).join(", "),
    audience: initial?.audience ?? "",
    tone: initial?.tone ?? "",
    platforms: initial?.platforms ?? ["bluesky", "mastodon"],
    sources: initial?.sources ?? [{ type: "hn", value: "" } as CampaignSource],
    times: (initial?.post_times ?? ["09:00", "13:00", "18:00"]).join(", "),
    timezone: initial?.timezone ?? browserTz,
    daily_cap: initial?.daily_cap ?? 3,
    min_gap: initial?.min_gap_minutes ?? 120,
    trust: (initial?.trust_level ?? "copilot") as TrustLevel,
    veto: initial?.veto_minutes ?? 120,
    link: initial?.link_policy ?? "always",
    fact: initial?.fact_check ?? true,
    every: initial?.research_every_h ?? 6,
  });
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const body: Record<string, unknown> = {
      topics: splitList(f.topics), keywords: splitList(f.keywords), avoid_terms: splitList(f.avoid), audience: f.audience, tone: f.tone,
      platforms: f.platforms, sources: f.sources.filter((s) => s.value.trim()), post_times: splitList(f.times), timezone: f.timezone,
      daily_cap: Number(f.daily_cap), min_gap_minutes: Number(f.min_gap), veto_minutes: Number(f.veto), link_policy: f.link,
      fact_check: f.fact, research_every_h: Number(f.every),
    };
    if (!initial || f.trust !== initial.trust_level) body.trust_level = f.trust;
    try {
      const saved = initial
        ? await client.patch<Campaign>(`/api/autopilot/campaigns/${initial.id}`, body)
        : await client.post<Campaign>("/api/autopilot/campaigns", { ...body, name: f.name });
      notify("success", initial ? "Campaign saved" : "Campaign created. It will run within a minute, or use Run now.");
      onDone(saved);
    } catch (err: any) {
      notify("error", err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-4">
      <div className="flex items-center gap-2">
        <button type="button" className="btn" onClick={() => onDone(null)}><X size={14} /> Cancel</button>
        <h2 className="text-lg font-semibold">{initial ? `Settings: ${initial.name}` : "New campaign"}</h2>
      </div>

      <Section title="What to post about">
        <div className="grid gap-3 md:grid-cols-2">
          {!initial && <Field label="Campaign name"><input className="input" required minLength={2} maxLength={120} value={f.name} onChange={(e) => set({ name: e.target.value })} placeholder="Open source AI news" /></Field>}
          <Field label="Topics (comma separated)"><input className="input" value={f.topics} onChange={(e) => set({ topics: e.target.value })} placeholder="AI agents, open source, developer tools" /></Field>
          <Field label="SEO keywords (comma separated)" hint="Used to score stories and as hashtags."><input className="input" value={f.keywords} onChange={(e) => set({ keywords: e.target.value })} placeholder="ai agents, open source, llm" /></Field>
          <Field label="Never post about (comma separated)"><input className="input" value={f.avoid} onChange={(e) => set({ avoid: e.target.value })} placeholder="competitor names, politics" /></Field>
          <Field label="Audience"><input className="input" maxLength={500} value={f.audience} onChange={(e) => set({ audience: e.target.value })} placeholder="developers and founders" /></Field>
          <Field label="Tone"><input className="input" maxLength={300} value={f.tone} onChange={(e) => set({ tone: e.target.value })} placeholder="clear, friendly, expert, no hype" /></Field>
        </div>
      </Section>

      <Section title="Where to find stories">
        <ul className="space-y-2">
          {f.sources.map((s, n) => (
            <li key={n} className="flex flex-wrap gap-2">
              <select className="input !w-auto" value={s.type} aria-label="Source type" onChange={(e) => set({ sources: f.sources.map((x, m) => (m === n ? { ...x, type: e.target.value as CampaignSource["type"] } : x)) })}>
                {(Object.keys(SOURCE_LABEL) as CampaignSource["type"][]).map((t) => <option key={t} value={t}>{SOURCE_LABEL[t].label}</option>)}
              </select>
              <input className="input min-w-0 flex-1" value={s.value} aria-label="Source" placeholder={SOURCE_LABEL[s.type].placeholder}
                onChange={(e) => set({ sources: f.sources.map((x, m) => (m === n ? { ...x, value: e.target.value } : x)) })} />
              <button type="button" className="btn" aria-label="Remove source" onClick={() => set({ sources: f.sources.filter((_, m) => m !== n) })}><X size={14} /></button>
            </li>
          ))}
        </ul>
        <button type="button" className="btn mt-2 !py-1 text-xs" disabled={f.sources.length >= 20} onClick={() => set({ sources: [...f.sources, { type: "rss", value: "" }] })}><Plus size={13} /> Add source</button>
        {!searchConfigured && f.sources.some((s) => s.type === "search") && (
          <p className="mt-2 text-xs text-amber-300">Web news search needs a free Tavily or Brave key in .env; the other sources work without keys.</p>
        )}
      </Section>

      <Section title="Where and when">
        <div className="mb-3 flex flex-wrap gap-3">
          {PLATFORMS.map((p) => (
            <label key={p.id} className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={f.platforms.includes(p.id)} onChange={(e) => set({ platforms: e.target.checked ? [...f.platforms, p.id] : f.platforms.filter((x) => x !== p.id) })} />
              {p.name}
            </label>
          ))}
        </div>
        <p className="mb-3 text-xs text-[var(--color-mute)]">Connected platforms post for real (connect them in Content). Platforms you have not connected are drafted and published as labelled simulations.</p>
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Posting times" hint="24-hour, comma separated"><input className="input" value={f.times} onChange={(e) => set({ times: e.target.value })} /></Field>
          <Field label="Time zone"><input className="input" value={f.timezone} onChange={(e) => set({ timezone: e.target.value })} /></Field>
          <Field label="Look for stories every (hours)"><input className="input" type="number" min={1} max={48} value={f.every} onChange={(e) => set({ every: Number(e.target.value) })} /></Field>
          <Field label="Max posts per platform per day"><input className="input" type="number" min={1} max={10} value={f.daily_cap} onChange={(e) => set({ daily_cap: Number(e.target.value) })} /></Field>
          <Field label="Min. minutes between posts"><input className="input" type="number" min={15} max={1440} value={f.min_gap} onChange={(e) => set({ min_gap: Number(e.target.value) })} /></Field>
          <Field label="Source link in posts">
            <select className="input" value={f.link} onChange={(e) => set({ link: e.target.value as "always" | "never" })}>
              <option value="always">Always add the source link</option>
              <option value="never">No links</option>
            </select>
          </Field>
        </div>
      </Section>

      <Section title="How much to trust it">
        <div className="grid gap-2 sm:grid-cols-3">
          {(Object.keys(TRUST) as TrustLevel[]).map((lvl) => {
            const locked = lvl === "auto" && !(initial?.auto_unlocked || initial?.trust_level === "auto");
            return (
              <label key={lvl} className={`rounded-lg border p-3 text-xs ${f.trust === lvl ? "border-cyan-400/70 bg-cyan-400/10" : "border-[var(--color-line)]"} ${locked ? "opacity-50" : ""}`}>
                <input type="radio" name="trust" className="mr-1.5" checked={f.trust === lvl} disabled={locked} onChange={() => set({ trust: lvl })} />
                <b className="text-sm">{TRUST[lvl].label}</b>
                <div className="mt-1 text-[var(--color-mute)]">{TRUST[lvl].help}</div>
                {locked && <div className="mt-1 text-amber-300">Unlocks after {initial?.auto_unlock_needs ?? 10} clean posts.</div>}
              </label>
            );
          })}
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <Field label="Minutes you have to cancel (veto / auto)"><input className="input" type="number" min={10} max={1440} value={f.veto} onChange={(e) => set({ veto: Number(e.target.value) })} /></Field>
          <label className="flex items-start gap-2 pt-5 text-sm">
            <input type="checkbox" className="mt-1" checked={f.fact} onChange={(e) => set({ fact: e.target.checked })} />
            <span>Fact-check every post against its source (uses one extra free AI request per story; recommended)</span>
          </label>
        </div>
      </Section>

      <div className="flex gap-2">
        <button className="btn btn-primary" disabled={busy || f.platforms.length === 0}><Check size={14} /> {busy ? "Saving…" : initial ? "Save" : "Create campaign"}</button>
        <button type="button" className="btn" onClick={() => onDone(null)}>Cancel</button>
      </div>
    </form>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block min-w-0">
      <span className="hud-label mb-1 block text-[var(--color-mute)]">{label}</span>
      {children}
      {hint && <span className="mt-0.5 block text-[11px] text-[var(--color-mute)]">{hint}</span>}
    </label>
  );
}
