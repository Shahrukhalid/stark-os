"use client";

import { Download, ExternalLink, Heart, MessageCircle, RefreshCw, Repeat2, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { bestSlots, daily, heatmap, toCsv } from "@/lib/analytics";
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
  const top = useMemo(() => [...posts].filter((p) => p.score != null).sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 6), [posts]);

  function exportCsv() {
    const blob = new Blob([toCsv(posts)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "stark-analytics.csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
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
    </div>
  );
}
