"use client";

import { Download, ExternalLink, FileText, FlaskConical, Heart, Recycle, Trophy, MessageCircle, RefreshCw, Repeat2, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { bestSlots, daily, experiments, heatmap, toCsv } from "@/lib/analytics";
import { useStark } from "@/lib/store";
import type { AnalyticsReport } from "@/lib/types";
import { Empty, Section, timeAgo } from "./ui";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const STATUS_COLOR: Record<string, string> = { draft: "#7d8d99", scheduled: "#22d3ee", published: "#34d399", failed: "#f87171", rejected: "#a78bfa", publishing: "#fbbf24" };

function useCountUp(target: number, ms = 900) {
  const [v, setV] = useState(0);
  useEffect(() => {
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      setV(Math.round(target * (1 - Math.pow(1 - k, 3))));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

function Kpi({ label, value, icon: Icon, color }: { label: string; value: number; icon: React.ElementType; color: string }) {
  const v = useCountUp(value);
  return (
    <div className="panel p-4">
      <div className="flex items-center gap-2">
        <Icon size={16} style={{ color }} />
        <span className="hud-label text-[var(--color-mute)]">{label}</span>
      </div>
      <div className="stat-glow mt-2 font-mono text-3xl font-semibold" style={{ color }}>
        {v.toLocaleString()}
      </div>
    </div>
  );
}

/** Engagement over the last 30 days: stacked bars per day, drawn to grow in. */
function Trend({ points }: { points: ReturnType<typeof daily> }) {
  const W = 720;
  const H = 200;
  const pad = 24;
  const max = Math.max(1, ...points.map((p) => p.likes + p.reposts + p.replies));
  const bw = (W - pad * 2) / points.length;
  const [hover, setHover] = useState<number | null>(null);
  const h = hover != null ? points[hover] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H + 26}`} className="w-full" role="img" aria-label="Engagement per day for the last 30 days">
        <defs>
          <linearGradient id="bar-l" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#f472b6" />
            <stop offset="100%" stopColor="#a78bfa" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={pad} x2={W - pad} y1={H - (H - 10) * f} y2={H - (H - 10) * f} stroke="var(--color-line)" strokeDasharray="2 4" />
        ))}
        {points.map((p, i) => {
          const segs = [
            { v: p.likes, c: "url(#bar-l)" },
            { v: p.reposts, c: "#22d3ee" },
            { v: p.replies, c: "#34d399" },
          ];
          let y = H;
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={pad + i * bw} y={0} width={bw} height={H} fill="transparent" />
              {segs.map((s, k) => {
                const hh = ((H - 10) * s.v) / max;
                y -= hh;
                return hh > 0 ? (
                  <rect key={k} x={pad + i * bw + 2} y={y} width={Math.max(2, bw - 4)} height={hh} rx={2} fill={s.c} opacity={hover == null || hover === i ? 1 : 0.45} style={{ transformOrigin: `0 ${H}px`, animation: `stark-rise .6s ${i * 0.015}s both` }} />
                ) : null;
              })}
              {p.posts > 0 && <circle cx={pad + i * bw + bw / 2} cy={H + 8} r={2.5} fill="var(--color-cyan)" />}
              {i % 5 === 0 && (
                <text x={pad + i * bw + bw / 2} y={H + 22} fontSize="10" textAnchor="middle" fill="var(--color-mute)">
                  {p.date.toLocaleDateString([], { day: "numeric", month: "short" })}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {h && (
        <div className="pointer-events-none absolute right-2 top-0 rounded-lg border border-[var(--color-line-strong)] bg-[var(--color-panel)] px-3 py-2 text-xs shadow-lg">
          <div className="font-semibold">{h.date.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })}</div>
          <div className="text-[var(--color-mute)]">
            {h.posts} post(s) · {h.likes} likes · {h.reposts} reposts · {h.replies} replies
          </div>
        </div>
      )}
      <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-[var(--color-mute)]">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-fuchsia-400" />Likes</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-cyan-400" />Reposts</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-emerald-400" />Replies</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-full bg-cyan-300" />Posted that day</span>
      </div>
    </div>
  );
}

/** Real engagement from Bluesky and Mastodon: totals, trend, best time to post and top posts. */
export function AnalyticsView() {
  const { client, notify, eventSeq } = useStark();
  const [r, setR] = useState<AnalyticsReport | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    (refresh = false) => {
      setLoading(true);
      client
        .get<AnalyticsReport>(`/api/social/analytics${refresh ? "?refresh=true" : ""}`)
        .then(setR)
        .catch((e) => notify("error", e.message))
        .finally(() => setLoading(false));
    },
    [client, notify],
  );
  useEffect(() => load(), [load, eventSeq.content]);

  const posts = useMemo(() => r?.posts ?? [], [r]);
  const points = useMemo(() => daily(posts, 30), [posts]);
  const heat = useMemo(() => heatmap(posts), [posts]);
  const slots = useMemo(() => bestSlots(posts), [posts]);
  const tests = useMemo(() => experiments(posts), [posts]);
  const top = useMemo(() => [...posts].filter((p) => p.score != null).sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 6), [posts]);

  function exportCsv() {
    const blob = new Blob([toCsv(posts)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "stark-analytics.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  /** A self-contained HTML report to send to a client or a boss (open it and print to PDF if needed). */
  function exportReport() {
    const esc = (t: unknown) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
    const kpi = [["Published posts", posts.length], ["Likes", totals.likes], ["Reposts", totals.reposts + (totals.quotes || 0)], ["Replies", totals.replies]];
    const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Social media report</title><style>body{font:15px/1.5 system-ui,sans-serif;max-width:860px;margin:32px auto;padding:0 16px;color:#17212b}h1{margin:0}small{color:#64748b}.k{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}.k div{border:1px solid #cbd5e1;border-radius:10px;padding:12px}.k b{display:block;font-size:26px;color:#0e7490}table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #e2e8f0;padding:6px;text-align:left;vertical-align:top}</style></head><body>
<h1>Social media report</h1><small>Generated ${esc(new Date().toLocaleString())} · real engagement from Bluesky and Mastodon</small>
<div class="k">${kpi.map(([l, v]) => `<div><b>${esc(v)}</b>${esc(l)}</div>`).join("")}</div>
${slots[0] ? `<p><b>Best time to post so far:</b> ${esc(slots[0].label)} (your time zone)</p>` : ""}
<h2>Top posts</h2><table><tr><th>#</th><th>Post</th><th>Platform</th><th>♥</th><th>⟲</th><th>💬</th></tr>${top.map((p, i) => `<tr><td>${i + 1}</td><td>${esc(p.text)}</td><td>${esc(p.platform)}</td><td>${p.engagement?.likes ?? 0}</td><td>${p.engagement?.reposts ?? 0}</td><td>${p.engagement?.replies ?? 0}</td></tr>`).join("")}</table>
<h2>Last 30 days</h2><table><tr><th>Day</th><th>Posts</th><th>Likes</th><th>Reposts</th><th>Replies</th></tr>${points.filter((d) => d.posts || d.likes).map((d) => `<tr><td>${esc(d.date.toLocaleDateString())}</td><td>${d.posts}</td><td>${d.likes}</td><td>${d.reposts}</td><td>${d.replies}</td></tr>`).join("")}</table>
</body></html>`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
    a.download = `social-report-${new Date().toISOString().slice(0, 10)}.html`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  async function toggleEvergreen(id: string, on: boolean) {
    try {
      await client.post(`/api/social/items/${id}/evergreen`, { days: on ? 30 : null });
      notify("success", on ? "This post will come back as a draft every 30 days." : "Recycling off.");
      load(true);
    } catch (e: any) {
      notify("error", e.message);
    }
  }

  const totals = r?.totals ?? { likes: 0, reposts: 0, replies: 0, quotes: 0 };
  const statuses = ["draft", "scheduled", "published", "failed", "rejected"];

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="panel flex flex-wrap items-center gap-3 p-4">
        <div>
          <div className="hud-label text-cyan-300">Performance</div>
          <h1 className="holo-text text-xl font-semibold">Analytics</h1>
          <p className="text-xs text-[var(--color-mute)]">
            Real numbers from your connected Bluesky and Mastodon accounts. Simulated posts never get made-up engagement.
            {r && ` Updated ${timeAgo(r.fetched_at)}.`}
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <button className="btn text-xs" onClick={() => load(true)} disabled={loading}>
            <RefreshCw size={13} className={loading ? "anim-spin-fast" : ""} /> Refresh
          </button>
          <button className="btn text-xs" onClick={exportCsv} disabled={!posts.length}>
            <Download size={13} /> CSV
          </button>
          <button className="btn text-xs" onClick={exportReport} disabled={!posts.length}>
            <FileText size={13} /> Report
          </button>
        </div>
      </section>

      {r?.errors?.length ? <div className="panel !border-amber-300/40 p-3 text-xs text-amber-200">Could not read some numbers: {r.errors.join("; ")}</div> : null}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="Published posts" value={posts.length} icon={TrendingUp} color="#22d3ee" />
        <Kpi label="Likes" value={totals.likes} icon={Heart} color="#f472b6" />
        <Kpi label="Reposts" value={totals.reposts + (totals.quotes || 0)} icon={Repeat2} color="#a78bfa" />
        <Kpi label="Replies" value={totals.replies} icon={MessageCircle} color="#34d399" />
      </div>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1.4fr_1fr]">
        <Section title="Engagement · last 30 days">{posts.length ? <Trend points={points} /> : <Empty>No published posts yet.</Empty>}</Section>
        <Section title="Content pipeline">
          <div className="space-y-3">
            {Object.entries(r?.counts ?? {}).map(([platform, c]) => {
              const total = Object.values(c).reduce((a, b) => a + b, 0) || 1;
              return (
                <div key={platform}>
                  <div className="mb-1 flex justify-between text-xs">
                    <span className="font-medium capitalize">{platform}</span>
                    <span className="text-[var(--color-mute)]">{total} item(s)</span>
                  </div>
                  <div className="flex h-2.5 overflow-hidden rounded-full bg-black/20">
                    {statuses.map((s) =>
                      c[s] ? <div key={s} title={`${s}: ${c[s]}`} style={{ width: `${(100 * c[s]) / total}%`, background: STATUS_COLOR[s], transition: "width .8s" }} /> : null,
                    )}
                  </div>
                </div>
              );
            })}
            {!Object.keys(r?.counts ?? {}).length && <Empty>Nothing in the queue yet.</Empty>}
            <div className="flex flex-wrap gap-3 pt-1 text-[11px] text-[var(--color-mute)]">
              {statuses.map((s) => (
                <span key={s} className="capitalize">
                  <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[s] }} />
                  {s}
                </span>
              ))}
            </div>
          </div>
        </Section>
      </div>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1.4fr_1fr]">
        <Section title="Best time to post · your time zone">
          {heat.max === 0 ? (
            <Empty>Needs a few real posts with engagement. Connect Bluesky or Mastodon in Content and publish.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <div className="grid min-w-[560px] gap-[3px]" style={{ gridTemplateColumns: "34px repeat(24, 1fr)" }}>
                <span />
                {Array.from({ length: 24 }, (_, hr) => (
                  <span key={hr} className="text-center text-[9px] text-[var(--color-mute)]">
                    {hr % 3 === 0 ? hr : ""}
                  </span>
                ))}
                {heat.avg.map((row, w) => (
                  <div key={w} className="contents">
                    <span className="text-[10px] text-[var(--color-mute)]">{WEEKDAYS[w]}</span>
                    {row.map((v, hr) => (
                      <span
                        key={hr}
                        title={v == null ? `${WEEKDAYS[w]} ${hr}:00 · no posts` : `${WEEKDAYS[w]} ${hr}:00 · avg score ${v.toFixed(1)} over ${heat.count[w][hr]} post(s)`}
                        className="aspect-square rounded-[3px]"
                        style={{ background: v == null ? "var(--color-line)" : `rgba(34, 211, 238, ${0.2 + 0.8 * (v / heat.max)})`, boxShadow: v != null && v === heat.max ? "0 0 10px #22d3ee" : undefined }}
                      />
                    ))}
                  </div>
                ))}
              </div>
              {slots[0] && (
                <p className="mt-3 text-xs">
                  Best slot so far: <span className="font-semibold text-cyan-300">{slots[0].label}</span>
                  <span className="text-[var(--color-mute)]"> (score = likes + 2 × reposts, replies and quotes)</span>
                </p>
              )}
            </div>
          )}
        </Section>
        <Section title="Top posts">
          {top.length === 0 ? (
            <Empty>No measured posts yet.</Empty>
          ) : (
            <ol className="space-y-2">
              {top.map((p, i) => (
                <li key={p.id} className="flex gap-2 rounded-lg border border-[var(--color-line)] p-2 text-xs">
                  <span className="font-mono text-lg font-semibold text-cyan-300/80">{i + 1}</span>
                  <span className="min-w-0 flex-1">
                    <span className="line-clamp-2">{p.text}</span>
                    <span className="mt-1 flex flex-wrap gap-2 text-[var(--color-mute)]">
                      <span className="capitalize">{p.platform}</span>
                      <span>♥ {p.engagement?.likes ?? 0}</span>
                      <span>⟲ {p.engagement?.reposts ?? 0}</span>
                      <span>💬 {p.engagement?.replies ?? 0}</span>
                      <span>{timeAgo(p.published_at)}</span>
                    </span>
                  </span>
                  <button
                    className={`shrink-0 ${p.evergreen_days ? "text-emerald-300" : "text-[var(--color-mute)] hover:text-emerald-300"}`}
                    onClick={() => toggleEvergreen(p.id, !p.evergreen_days)}
                    aria-pressed={!!p.evergreen_days}
                    aria-label={p.evergreen_days ? "Stop recycling this post" : "Recycle this post every 30 days"}
                    title={p.evergreen_days ? `Evergreen: back as a draft every ${p.evergreen_days} days` : "Make evergreen: back as a draft every 30 days"}
                  >
                    <Recycle size={13} />
                  </button>
                  {p.url && (
                    <a href={p.url} target="_blank" rel="noreferrer noopener" className="shrink-0 text-[var(--color-mute)] hover:text-cyan-300" aria-label="Open post">
                      <ExternalLink size={13} />
                    </a>
                  )}
                </li>
              ))}
            </ol>
          )}
        </Section>
      </div>

      <Section title="Experiments · A/B hook tests" right={<FlaskConical size={15} className="text-violet-300" />}>
        {tests.length === 0 ? (
          <Empty>No A/B tests yet. Start one in Studio: two versions of a post with different hooks.</Empty>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {tests.map((t) => {
              const max = Math.max(1, ...t.variants.map((v) => v.score ?? 0));
              return (
                <div key={t.name} className="rounded-lg border border-[var(--color-line)] p-3">
                  <div className="mb-2 flex items-center gap-2 text-sm">
                    <span className="font-semibold">{t.name}</span>
                    {t.winner ? (
                      <span className="chip ml-auto !border-emerald-400/50 !text-emerald-300">
                        <Trophy size={11} /> winner{t.lift != null ? ` +${t.lift}%` : ""}
                      </span>
                    ) : (
                      <span className="chip ml-auto">{t.variants.length < 2 ? "waiting for the second post" : "measuring…"}</span>
                    )}
                  </div>
                  <ul className="space-y-2">
                    {t.variants.map((v, i) => (
                      <li key={v.id} className="text-xs">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[var(--color-mute)]">{String.fromCharCode(65 + i)}</span>
                          <span className="line-clamp-1 min-w-0 flex-1">{v.text}</span>
                          <span className="font-mono">{v.score ?? "–"}</span>
                        </div>
                        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-black/20">
                          <div className="h-full rounded-full" style={{ width: `${(100 * (v.score ?? 0)) / max}%`, background: t.winner?.id === v.id ? "#34d399" : "#a78bfa", transition: "width .8s" }} />
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        )}
      </Section>
    </div>
  );
}
