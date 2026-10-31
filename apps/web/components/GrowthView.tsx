"use client";

import { ExternalLink, Flame, Hash, Package, RefreshCw, Sparkles, TrendingUp, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useStark } from "@/lib/store";
import type { GrowthReport } from "@/lib/types";
import { Empty, Section } from "./ui";

const COLORS: Record<string, string> = { bluesky: "#38bdf8", mastodon: "#a78bfa" };

function FollowerChart({ series }: { series: GrowthReport["series"] }) {
  const W = 640;
  const H = 180;
  const all = Object.values(series).flat();
  if (all.length < 2) return <Empty>Follower history starts today; the chart fills in over the next days.</Empty>;
  const days = [...new Set(all.map((p) => p.day))].sort();
  const max = Math.max(...all.map((p) => p.followers));
  const min = Math.min(...all.map((p) => p.followers));
  const x = (d: string) => 30 + ((W - 40) * days.indexOf(d)) / Math.max(1, days.length - 1);
  const y = (v: number) => H - 20 - ((H - 40) * (v - min)) / Math.max(1, max - min);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Followers over time">
      {Object.entries(series).map(([platform, pts]) => {
        const d = pts.map((p, i) => `${i ? "L" : "M"}${x(p.day)},${y(p.followers)}`).join(" ");
        return (
          <g key={platform}>
            <path d={`${d} L${x(pts.at(-1)!.day)},${H - 20} L${x(pts[0].day)},${H - 20} Z`} fill={COLORS[platform] || "#22d3ee"} opacity={0.08} />
            <path d={d} fill="none" stroke={COLORS[platform] || "#22d3ee"} strokeWidth={2.2} strokeLinejoin="round" style={{ strokeDasharray: 2000, animation: "stark-draw 1.2s ease-out both" }} />
          </g>
        );
      })}
      <text x={30} y={H - 4} fontSize="10" fill="var(--color-mute)">{days[0]}</text>
      <text x={W - 10} y={H - 4} fontSize="10" fill="var(--color-mute)" textAnchor="end">{days.at(-1)}</text>
      <text x={4} y={14} fontSize="10" fill="var(--color-mute)">{max}</text>
    </svg>
  );
}

/** 53 weeks × 7 days, like a contributions graph: how many posts went out each day. */
function Consistency({ posted }: { posted: Record<string, number> }) {
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 364 - ((today.getDay() + 6) % 7));
  const cells = useMemo(() => {
    const out: { d: Date; n: number }[] = [];
    for (let i = 0; i < 371; i++) {
      const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
      if (d > today) break;
      const key = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())).toISOString().slice(0, 10);
      out.push({ d, n: posted[key] || 0 });
    }
    return out;
  }, [posted]); // eslint-disable-line react-hooks/exhaustive-deps
  const max = Math.max(1, ...cells.map((c) => c.n));
  return (
    <div className="overflow-x-auto">
      <div className="grid w-max grid-flow-col gap-[3px]" style={{ gridTemplateRows: "repeat(7, 11px)" }}>
        {cells.map((c) => (
          <span
            key={c.d.toDateString()}
            title={`${c.d.toLocaleDateString()}: ${c.n} post(s)`}
            className="h-[11px] w-[11px] rounded-[2px]"
            style={{ background: c.n ? `rgba(52, 211, 153, ${0.25 + 0.75 * (c.n / max)})` : "var(--color-line)" }}
          />
        ))}
      </div>
    </div>
  );
}

/** Followers, posting consistency, top fans, rising hashtags, competitor outliers and Bluesky starter packs. */
export function GrowthView({ talkTo }: { talkTo: (agentId: string, text?: string) => void }) {
  const { client, notify } = useStark();
  const [g, setG] = useState<GrowthReport | null>(null);
  const [fans, setFans] = useState<{ platform: string; account: string; score: number; kinds: Record<string, number> }[]>([]);
  const [trends, setTrends] = useState<{ hashtags: { tag: string; count: number; before: number; growth: number }[]; outliers: { account: string; text: string; url: string | null; times_average: number }[] }>({ hashtags: [], outliers: [] });
  const [pack, setPack] = useState({ name: "", description: "", handles: "" });
  const [packOut, setPackOut] = useState<{ url: string; added: number; not_found: string[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    client.get<GrowthReport>("/api/growth").then(setG).catch(() => {});
    client.get("/api/growth/fans").then((r: any) => setFans(r.fans)).catch(() => {});
    client.get("/api/growth/trends").then(setTrends).catch(() => {});
  }, [client]);
  useEffect(load, [load]);

  async function refresh() {
    setBusy(true);
    try {
      const r = await client.post<{ saved: number }>("/api/growth/snapshot");
      notify(r.saved ? "success" : "warn", r.saved ? "Follower counts updated." : "Connect Bluesky or Mastodon in Content to track followers.");
      load();
    } finally {
      setBusy(false);
    }
  }

  async function makePack(e: React.FormEvent) {
    e.preventDefault();
    try {
      setPackOut(await client.post("/api/bluesky/starter-pack", { name: pack.name, description: pack.description, handles: pack.handles.split(/[\s,]+/).filter(Boolean) }));
      notify("success", "Starter pack created on Bluesky.");
    } catch (err: any) {
      notify("error", err.message);
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="panel flex flex-wrap items-center gap-3 p-4">
        <div>
          <div className="hud-label text-cyan-300">Audience</div>
          <h1 className="holo-text text-xl font-semibold">Growth</h1>
          <p className="text-xs text-[var(--color-mute)]">Followers over time, how consistently you post, who loves your content, and ideas that are working right now.</p>
        </div>
        <button className="btn ml-auto text-xs" onClick={refresh} disabled={busy}>
          <RefreshCw size={13} className={busy ? "anim-spin-fast" : ""} /> Update now
        </button>
      </section>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Object.entries(g?.summary ?? {}).map(([p, s]) => (
          <div key={p} className="panel p-4">
            <div className="hud-label capitalize text-[var(--color-mute)]">{p} followers</div>
            <div className="stat-glow mt-1 font-mono text-3xl font-semibold" style={{ color: COLORS[p] }}>
              {s.followers.toLocaleString()}
            </div>
            <div className={`text-xs ${s.change_7d >= 0 ? "text-emerald-300" : "text-red-300"}`}>
              {s.change_7d >= 0 ? "+" : ""}
              {s.change_7d} this week
            </div>
          </div>
        ))}
        <div className="panel p-4">
          <div className="hud-label text-[var(--color-mute)]">Posting streak</div>
          <div className="stat-glow mt-1 flex items-center gap-1 font-mono text-3xl font-semibold text-amber-300">
            <Flame size={22} /> {g?.streak ?? 0}
          </div>
          <div className="text-xs text-[var(--color-mute)]">day(s) in a row</div>
        </div>
        <div className="panel p-4">
          <div className="hud-label text-[var(--color-mute)]">Active days</div>
          <div className="stat-glow mt-1 font-mono text-3xl font-semibold text-emerald-300">{g?.active_days_30 ?? 0}/30</div>
          <div className="text-xs text-[var(--color-mute)]">days with a post this month</div>
        </div>
      </div>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1.4fr_1fr]">
        <Section title="Followers" right={<TrendingUp size={15} className="text-cyan-300" />}>
          {g && Object.keys(g.series).length ? <FollowerChart series={g.series} /> : <Empty>Connect Bluesky or Mastodon, then press Update now.</Empty>}
        </Section>
        <Section title="Top fans" right={<Users size={15} className="text-fuchsia-300" />}>
          {fans.length === 0 ? (
            <Empty>People who like, repost and reply most appear here.</Empty>
          ) : (
            <ol className="space-y-1.5 text-sm">
              {fans.slice(0, 10).map((f, i) => (
                <li key={f.platform + f.account} className="flex items-center gap-2">
                  <span className="w-5 font-mono text-[var(--color-mute)]">{i + 1}</span>
                  <span className="min-w-0 flex-1 truncate font-medium">{f.account}</span>
                  <span className="text-xs text-[var(--color-mute)]">{Object.entries(f.kinds).map(([k, n]) => `${n} ${k}`).join(" · ")}</span>
                </li>
              ))}
            </ol>
          )}
          {fans.length > 0 && (
            <button className="btn mt-3 !py-1 text-xs" onClick={() => talkTo("friday", `Friday, write a short, warm thank-you post for our most engaged followers this week (${fans.slice(0, 5).map((f) => f.account).join(", ")}). Ask before mentioning anyone by name.`)}>
              <Sparkles size={12} /> Thank them
            </button>
          )}
        </Section>
      </div>

      <Section title="Posting consistency · last 12 months">
        {g ? <Consistency posted={g.posted_days} /> : null}
      </Section>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-2">
        <Section title="Rising hashtags (from Listening)" right={<Hash size={15} className="text-violet-300" />}>
          {trends.hashtags.length === 0 ? (
            <Empty>Follow a few keywords or hashtags in Listening to see what is rising.</Empty>
          ) : (
            <div className="flex flex-wrap gap-2">
              {trends.hashtags.map((t) => (
                <button key={t.tag} className="chip !text-[var(--color-ink)]" title={`${t.count} this week, ${t.before} the week before`} onClick={() => talkTo("edith", `EDITH, write a post that genuinely fits the trending hashtag #${t.tag} for our brand. Skip it if it doesn't fit.`)}>
                  #{t.tag} <span className={t.growth > 0 ? "text-emerald-300" : "text-[var(--color-mute)]"}>{t.growth > 0 ? `+${t.growth}` : t.count}</span>
                </button>
              ))}
            </div>
          )}
        </Section>
        <Section title="Competitor outliers · proven ideas" right={<Sparkles size={15} className="text-amber-300" />}>
          {trends.outliers.length === 0 ? (
            <Empty>Posts that did 3× better than a competitor&apos;s average appear here (follow competitors in Listening).</Empty>
          ) : (
            <ul className="space-y-2 text-xs">
              {trends.outliers.slice(0, 6).map((o, i) => (
                <li key={i} className="rounded-lg border border-[var(--color-line)] p-2">
                  <div className="mb-1 flex items-center gap-2">
                    <span className="font-semibold">@{o.account}</span>
                    <span className="chip !border-amber-300/50 !text-amber-300">{o.times_average}× their average</span>
                    {o.url && (
                      <a href={o.url} target="_blank" rel="noreferrer noopener" className="ml-auto text-[var(--color-mute)] hover:text-cyan-300" aria-label="Open post">
                        <ExternalLink size={12} />
                      </a>
                    )}
                  </div>
                  <p className="line-clamp-2">{o.text}</p>
                  <button className="mt-1 text-cyan-300 hover:underline" onClick={() => talkTo("edith", `EDITH, this competitor post did ${o.times_average}× better than usual:\n\n"${o.text}"\n\nWrite our own original take in our brand voice. Learn from the angle and hook, never copy the wording.`)}>
                    Use the idea
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>

      <Section title="Bluesky starter pack" right={<Package size={15} className="text-sky-300" />}>
        <p className="mb-2 text-xs text-[var(--color-mute)]">A shareable list of up to 150 accounts that people can follow in one click: a great way to grow a community around your topic. Include yourself and people you recommend. It is created publicly on your Bluesky account.</p>
        <form onSubmit={makePack} className="grid gap-2 lg:grid-cols-[1fr_1fr]">
          <input className="input" aria-label="Starter pack name" placeholder="Name, e.g. Open-source AI builders" maxLength={50} value={pack.name} onChange={(e) => setPack({ ...pack, name: e.target.value })} />
          <input className="input" aria-label="Starter pack description" placeholder="One line about who is in it" maxLength={300} value={pack.description} onChange={(e) => setPack({ ...pack, description: e.target.value })} />
          <textarea className="input min-h-[70px] lg:col-span-2" aria-label="Handles" placeholder="handle.bsky.social, another.bsky.social …" value={pack.handles} onChange={(e) => setPack({ ...pack, handles: e.target.value })} />
          <button className="btn btn-primary w-fit" disabled={!pack.name.trim() || !pack.handles.trim()}>
            <Package size={14} /> Create starter pack
          </button>
        </form>
        {packOut && (
          <p className="mt-2 text-xs">
            <a className="text-cyan-300 underline" href={packOut.url} target="_blank" rel="noreferrer noopener">
              Open your starter pack
            </a>{" "}
            · {packOut.added} account(s) added{packOut.not_found.length ? ` · not found: ${packOut.not_found.join(", ")}` : ""}
          </p>
        )}
      </Section>
    </div>
  );
}
