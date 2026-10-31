"use client";

import { CalendarDays, ChevronLeft, ChevronRight, GripVertical, Sparkles, WandSparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { bestSlots, nextSlots } from "@/lib/analytics";
import { useStark } from "@/lib/store";
import type { AnalyticsReport, ContentItem } from "@/lib/types";
import { PlanEditor } from "./PlanEditor";
import { Section } from "./ui";

const PLATFORM_COLOR: Record<string, string> = { bluesky: "#38bdf8", mastodon: "#a78bfa", x: "#e5e7eb", linkedin: "#60a5fa", instagram: "#f472b6", tiktok: "#2dd4bf", youtube: "#f87171", threads: "#d4d4d8" };
const DAY = 86400000;

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}
function sameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
function key(d: Date) {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

interface Entry {
  id: string;
  when: Date;
  item?: ContentItem;
  text: string;
  platform: string;
  status: string;
}

/** Month / week calendar of scheduled and published posts. Drag a post onto another day to reschedule it. */
export function CalendarView() {
  const { client, notify, eventSeq } = useStark();
  const [items, setItems] = useState<ContentItem[]>([]);
  const [report, setReport] = useState<AnalyticsReport | null>(null);
  const [mode, setMode] = useState<"month" | "week">("month");
  const [cursor, setCursor] = useState(() => startOfDay(new Date()));
  const [dragId, setDragId] = useState<string | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    client.get<{ items: ContentItem[] }>("/api/social/queue?limit=500").then((q) => setItems(q.items)).catch(() => {});
    client.get<AnalyticsReport>("/api/social/analytics").then(setReport).catch(() => {});
  }, [client]);
  useEffect(load, [load, eventSeq.content]);

  const slots = useMemo(() => bestSlots(report?.posts || []), [report]);
  const bestHour = slots[0]?.hour ?? 10;

  const entries = useMemo(() => {
    const out: Entry[] = [];
    for (const i of items) if (i.status === "scheduled" && i.scheduled_for) out.push({ id: i.id, when: new Date(i.scheduled_for), item: i, text: i.text, platform: i.platform, status: i.status });
    for (const p of report?.posts || []) out.push({ id: p.id, when: new Date(p.published_at), text: p.text, platform: p.platform, status: "published" });
    return out.sort((a, b) => a.when.getTime() - b.when.getTime());
  }, [items, report]);
  const byDay = useMemo(() => {
    const m = new Map<string, Entry[]>();
    for (const e of entries) m.set(key(e.when), [...(m.get(key(e.when)) || []), e]);
    return m;
  }, [entries]);
  const drafts = items.filter((i) => i.status === "draft" || i.status === "failed");

  const days = useMemo(() => {
    if (mode === "week") {
      const s = new Date(cursor.getTime() - ((cursor.getDay() + 6) % 7) * DAY);
      return Array.from({ length: 7 }, (_, i) => new Date(s.getFullYear(), s.getMonth(), s.getDate() + i));
    }
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const s = new Date(first.getFullYear(), first.getMonth(), 1 - ((first.getDay() + 6) % 7));
    return Array.from({ length: 42 }, (_, i) => new Date(s.getFullYear(), s.getMonth(), s.getDate() + i));
  }, [cursor, mode]);

  const move = (n: number) =>
    setCursor((c) => (mode === "week" ? new Date(c.getFullYear(), c.getMonth(), c.getDate() + 7 * n) : new Date(c.getFullYear(), c.getMonth() + n, 1)));

  async function dropOn(day: Date) {
    const it = items.find((i) => i.id === dragId);
    setDragId(null);
    setOver(null);
    if (!it) return;
    const prev = it.scheduled_for ? new Date(it.scheduled_for) : null;
    const when = new Date(day.getFullYear(), day.getMonth(), day.getDate(), prev ? prev.getHours() : bestHour, prev ? prev.getMinutes() : 0);
    if (when.getTime() <= Date.now()) {
      notify("warn", "Pick a day in the future.");
      return;
    }
    setBusy(true);
    try {
      // Keeps the post's auto-publish approval only if it already had one for this exact text.
      await client.post(`/api/social/items/${it.id}/schedule`, { fingerprint: it.fingerprint, when: when.toISOString(), auto: it.auto_publish });
      notify("success", `Scheduled for ${when.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`);
      load();
    } catch (e: any) {
      notify("error", e.message);
    } finally {
      setBusy(false);
    }
  }

  /** Puts every passing draft on its own free day at the best hour. Auto-publish stays off: you still approve each one. */
  async function autoSchedule() {
    const ready = drafts.filter((i) => i.check?.verdict !== "fail");
    if (!ready.length) return notify("info", "No drafts ready to schedule.");
    const taken = new Set(entries.filter((e) => e.status === "scheduled").map((e) => e.when.toDateString()));
    const when = nextSlots(slots, ready.length, taken);
    setBusy(true);
    let ok = 0;
    for (let n = 0; n < when.length; n++) {
      try {
        await client.post(`/api/social/items/${ready[n].id}/schedule`, { fingerprint: ready[n].fingerprint, when: when[n].toISOString(), auto: false });
        ok++;
      } catch (e: any) {
        notify("error", e.message);
      }
    }
    setBusy(false);
    notify("success", `${ok} draft(s) placed on the calendar. Approve each one in Content to let it go out on its own.`);
    load();
  }

  const today = startOfDay(new Date());
  const title = mode === "month" ? cursor.toLocaleDateString([], { month: "long", year: "numeric" }) : `Week of ${days[0].toLocaleDateString([], { day: "numeric", month: "short" })}`;

  const Chip = ({ e }: { e: Entry }) => {
    const color = PLATFORM_COLOR[e.platform] || "#22d3ee";
    const draggable = e.status === "scheduled" && !!e.item;
    return (
      <div
        draggable={draggable}
        onDragStart={() => setDragId(e.id)}
        onDragEnd={() => setDragId(null)}
        title={`${e.platform} · ${e.status} · ${e.when.toLocaleString()}\n${e.text}`}
        className={`group flex items-center gap-1 truncate rounded-md border px-1.5 py-0.5 text-[11px] transition ${draggable ? "cursor-grab active:cursor-grabbing" : "opacity-80"} ${dragId === e.id ? "opacity-40" : ""}`}
        style={{ borderColor: `${color}55`, background: `${color}14` }}
      >
        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color, boxShadow: `0 0 6px ${color}` }} />
        <span className="shrink-0 font-mono text-[10px] text-[var(--color-mute)]">{e.when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hourCycle: "h23" })}</span>
        <span className="truncate">{e.status === "published" ? "✓ " : e.item?.auto_publish ? "⚡ " : ""}{e.text}</span>
      </div>
    );
  };

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <section className="panel p-4">
        <div className="flex flex-wrap items-center gap-2">
          <CalendarDays size={18} className="text-cyan-300" />
          <h1 className="holo-text mr-2 text-lg font-semibold">{title}</h1>
          <button className="btn !px-2 !py-1" onClick={() => move(-1)} aria-label="Previous">
            <ChevronLeft size={14} />
          </button>
          <button className="btn !py-1 text-xs" onClick={() => setCursor(startOfDay(new Date()))}>
            Today
          </button>
          <button className="btn !px-2 !py-1" onClick={() => move(1)} aria-label="Next">
            <ChevronRight size={14} />
          </button>
          <button className="btn ml-auto !py-1 text-xs" onClick={autoSchedule} disabled={busy || !drafts.length} title="Give every ready draft its own day at your best time">
            <WandSparkles size={13} /> Auto-schedule drafts
          </button>
          <div className="flex rounded-lg border border-[var(--color-line-strong)] p-0.5 text-xs" role="tablist">
            {(["month", "week"] as const).map((m) => (
              <button key={m} role="tab" aria-selected={mode === m} className={`rounded-md px-3 py-1 capitalize ${mode === m ? "bg-cyan-400/15 text-cyan-200" : "text-[var(--color-mute)]"}`} onClick={() => setMode(m)}>
                {m}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-[var(--color-mute)]">
          Drag a scheduled post, or a draft from the list, onto a day to (re)schedule it. ⚡ = goes out on its own; ✓ = published. {busy && <span className="text-cyan-300">Saving…</span>}
        </p>
      </section>

      <div className="grid gap-4 [&>*]:min-w-0 xl:grid-cols-[1fr_280px]">
        <section className="panel overflow-x-auto p-3">
          <div className="grid min-w-[640px] grid-cols-7 gap-1.5">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
              <div key={d} className="hud-label px-1 pb-1 text-[var(--color-mute)]">
                {d}
              </div>
            ))}
            {days.map((d) => {
              const k = key(d);
              const list = byDay.get(k) || [];
              const outside = mode === "month" && d.getMonth() !== cursor.getMonth();
              const isToday = sameDay(d, today);
              const past = d < today;
              return (
                <div
                  key={k}
                  onDragOver={(e) => {
                    if (!dragId || past) return;
                    e.preventDefault();
                    setOver(k);
                  }}
                  onDragLeave={() => setOver((o) => (o === k ? null : o))}
                  onDrop={(e) => {
                    e.preventDefault();
                    dropOn(d);
                  }}
                  className={`flex flex-col gap-1 rounded-lg border p-1.5 transition ${mode === "week" ? "min-h-[360px]" : "min-h-[104px]"} ${
                    over === k ? "border-cyan-300 bg-cyan-400/10 shadow-[0_0_24px_-6px_var(--color-cyan)]" : isToday ? "border-cyan-400/50 bg-cyan-400/5" : "border-[var(--color-line)]"
                  } ${outside || past ? "opacity-50" : ""}`}
                >
                  <div className={`flex items-center justify-between text-[11px] ${isToday ? "font-semibold text-cyan-300" : "text-[var(--color-mute)]"}`}>
                    <span>{d.getDate()}</span>
                    {isToday && <span className="h-1.5 w-1.5 rounded-full bg-cyan-300 anim-pulse" />}
                  </div>
                  {list.slice(0, mode === "week" ? 12 : 3).map((e) => (
                    <Chip key={`${e.status}-${e.id}`} e={e} />
                  ))}
                  {list.length > (mode === "week" ? 12 : 3) && <div className="text-[10px] text-[var(--color-mute)]">+{list.length - (mode === "week" ? 12 : 3)} more</div>}
                </div>
              );
            })}
          </div>
        </section>

        <div className="space-y-4">
          <Section title={`Drafts · ${drafts.length}`}>
            {drafts.length === 0 ? (
              <p className="text-xs text-[var(--color-mute)]">No drafts waiting. Ask E.D.I.T.H. to write some.</p>
            ) : (
              <ul className="max-h-[420px] space-y-1.5 overflow-y-auto">
                {drafts.map((i) => {
                  const failing = i.check?.verdict === "fail";
                  return (
                    <li
                      key={i.id}
                      draggable={!failing}
                      onDragStart={() => setDragId(i.id)}
                      onDragEnd={() => setDragId(null)}
                      className={`flex items-start gap-1.5 rounded-lg border border-[var(--color-line)] p-2 text-xs ${failing ? "opacity-60" : "cursor-grab hover:border-cyan-400/40"}`}
                      title={failing ? "Fix the problems the check found (in Content) before scheduling." : "Drag onto a day"}
                    >
                      <GripVertical size={12} className="mt-0.5 shrink-0 text-[var(--color-mute)]" />
                      <span className="min-w-0">
                        <span className="block text-[10px] uppercase tracking-wider" style={{ color: PLATFORM_COLOR[i.platform] || "#22d3ee" }}>
                          {i.platform} {failing && "· needs fixes"}
                        </span>
                        <span className="line-clamp-2">{i.text}</span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Section>
          <PlanEditor items={items} />
          <Section title="Best times to post">
            {slots.length ? (
              <ul className="space-y-1.5 text-xs">
                {slots.slice(0, 4).map((s, n) => (
                  <li key={`${s.weekday}-${s.hour}`} className="flex items-center gap-2">
                    <Sparkles size={12} className={n === 0 ? "text-amber-300" : "text-cyan-300"} />
                    <span className="font-medium">{s.label}</span>
                    <span className="ml-auto text-[var(--color-mute)]">avg {s.avg.toFixed(1)} · {s.count} post(s)</span>
                  </li>
                ))}
                <li className="pt-1 text-[11px] text-[var(--color-mute)]">Drafts dropped on a day are set to {String(bestHour).padStart(2, "0")}:00, your best hour so far.</li>
              </ul>
            ) : (
              <p className="text-xs text-[var(--color-mute)]">Appears after a few real posts on Bluesky or Mastodon have engagement. Until then drafts are set to 10:00.</p>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}
