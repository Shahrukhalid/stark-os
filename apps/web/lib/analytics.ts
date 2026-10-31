import type { PublishedPost } from "./types";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Monday-first weekday (0 = Monday) in the viewer's time zone. */
export function weekday(d: Date): number {
  return (d.getDay() + 6) % 7;
}

function measured(posts: PublishedPost[]) {
  return posts.filter((p) => p.score != null && p.engagement);
}

/** 7 × 24 grid of average engagement per post (null where nothing was posted), in local time. */
export function heatmap(posts: PublishedPost[]): { avg: (number | null)[][]; count: number[][]; max: number } {
  const sum = Array.from({ length: 7 }, () => Array<number>(24).fill(0));
  const count = Array.from({ length: 7 }, () => Array<number>(24).fill(0));
  for (const p of measured(posts)) {
    const d = new Date(p.published_at);
    sum[weekday(d)][d.getHours()] += p.score!;
    count[weekday(d)][d.getHours()] += 1;
  }
  let max = 0;
  const avg = sum.map((row, w) =>
    row.map((s, h) => {
      if (!count[w][h]) return null;
      const v = s / count[w][h];
      max = Math.max(max, v);
      return v;
    }),
  );
  return { avg, count, max };
}

export interface Slot {
  weekday: number;
  hour: number;
  avg: number;
  count: number;
  label: string;
}

/** Best weekday + hour slots, best first. Needs at least one measured post in a slot. */
export function bestSlots(posts: PublishedPost[]): Slot[] {
  const { avg, count } = heatmap(posts);
  const out: Slot[] = [];
  avg.forEach((row, w) =>
    row.forEach((v, h) => {
      if (v != null) out.push({ weekday: w, hour: h, avg: v, count: count[w][h], label: `${WEEKDAYS[w]} ${String(h).padStart(2, "0")}:00` });
    }),
  );
  return out.sort((a, b) => b.avg - a.avg || b.count - a.count);
}

export interface DayPoint {
  date: Date;
  posts: number;
  likes: number;
  reposts: number;
  replies: number;
}

/** One point per day for the last `days` days (local time), oldest first. */
export function daily(posts: PublishedPost[], days = 30, now = new Date()): DayPoint[] {
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const out: DayPoint[] = Array.from({ length: days }, (_, i) => ({
    date: new Date(end.getFullYear(), end.getMonth(), end.getDate() - (days - 1 - i)),
    posts: 0,
    likes: 0,
    reposts: 0,
    replies: 0,
  }));
  for (const p of posts) {
    const d = new Date(p.published_at);
    const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const idx = Math.round((day.getTime() - out[0].date.getTime()) / 86400000);
    if (idx < 0 || idx >= days) continue;
    out[idx].posts += 1;
    out[idx].likes += p.engagement?.likes || 0;
    out[idx].reposts += p.engagement?.reposts || 0;
    out[idx].replies += p.engagement?.replies || 0;
  }
  return out;
}

/** Posts as CSV (for spreadsheets). */
export function toCsv(posts: PublishedPost[]): string {
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const rows = [["published_at", "platform", "campaign", "likes", "reposts", "replies", "quotes", "score", "simulated", "url", "text"]];
  for (const p of posts)
    rows.push([p.published_at, p.platform, p.campaign, p.engagement?.likes ?? "", p.engagement?.reposts ?? "", p.engagement?.replies ?? "", p.engagement?.quotes ?? "", p.score ?? "", p.simulated, p.url ?? "", p.text].map(String));
  return rows.map((r) => r.map(esc).join(",")).join("\n");
}

export interface Experiment {
  name: string;
  variants: PublishedPost[];
  winner: PublishedPost | null;
  lift: number | null;
}

/** A/B hook tests: published posts whose campaign starts with "ab:". The winner needs every variant measured. */
export function experiments(posts: PublishedPost[]): Experiment[] {
  const groups = new Map<string, PublishedPost[]>();
  for (const p of posts) if (p.campaign?.startsWith("ab:")) groups.set(p.campaign, [...(groups.get(p.campaign) || []), p]);
  return [...groups.entries()].map(([name, variants]) => {
    const all = variants.length >= 2 && variants.every((v) => v.score != null);
    const sorted = [...variants].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
    const winner = all && sorted[0].score! > sorted[1].score! ? sorted[0] : null;
    const lift = winner && sorted[1].score ? Math.round((100 * (winner.score! - sorted[1].score!)) / sorted[1].score!) : null;
    return { name: name.slice(3), variants: sorted, winner, lift };
  });
}

/**
 * The next `count` free posting times: the best weekday/hour slots first (default 10:00 every day when nothing is
 * measured yet), at most one post per day, never in the past or within an hour from now.
 */
export function nextSlots(slots: Slot[], count: number, takenDays: Set<string>, now = new Date(), days = 21): Date[] {
  const hours = new Map<number, number[]>(); // weekday -> best hours
  for (const s of slots) hours.set(s.weekday, [...(hours.get(s.weekday) || []), s.hour]);
  const fallback = slots.length ? slots[0].hour : 10;
  const out: Date[] = [];
  for (let i = 0; i < days && out.length < count; i++) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i);
    const key = d.toDateString();
    if (takenDays.has(key)) continue;
    const h = (hours.get(weekday(d)) || [fallback])[0];
    const when = new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, 0);
    if (when.getTime() < now.getTime() + 3600_000) continue;
    out.push(when);
    takenDays.add(key);
  }
  return out;
}
