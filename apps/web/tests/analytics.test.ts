import { describe, expect, it } from "vitest";
import { bestSlots, daily, heatmap, toCsv } from "../lib/analytics";
import type { PublishedPost } from "../lib/types";

const post = (at: Date, likes: number | null, extra: Partial<PublishedPost> = {}): PublishedPost => ({
  id: `p${at.getTime()}`, platform: "bluesky", kind: "post", text: "hi, \"there\"", url: null, campaign: "", simulated: likes == null,
  published_at: at.toISOString(), engagement: likes == null ? null : { likes, reposts: 1, replies: 0 }, score: likes == null ? null : likes + 2, ...extra,
});

describe("analytics", () => {
  const mon9 = new Date(2026, 9, 26, 9, 15); // Monday
  const mon9b = new Date(2026, 9, 19, 9, 40);
  const fri18 = new Date(2026, 9, 30, 18, 5);

  it("ranks weekday/hour slots by average engagement and ignores unmeasured posts", () => {
    const slots = bestSlots([post(mon9, 10), post(mon9b, 2), post(fri18, 20), post(fri18, null)]);
    expect(slots.map((s) => s.label)).toEqual(["Fri 18:00", "Mon 09:00"]);
    expect(slots[1]).toMatchObject({ avg: 8, count: 2 });
    expect(heatmap([post(fri18, null)]).max).toBe(0);
  });

  it("buckets posts into local days and exports csv", () => {
    const pts = daily([post(mon9, 10), post(fri18, 4)], 7, new Date(2026, 9, 31, 12));
    expect(pts).toHaveLength(7);
    expect(pts.at(-2)).toMatchObject({ posts: 1, likes: 4 });
    expect(pts.find((p) => p.date.getDate() === 26)).toMatchObject({ posts: 1, likes: 10, reposts: 1 });
    expect(toCsv([post(mon9, 1)]).split("\n")[1]).toContain('"hi, ""there"""');
  });
});

describe("experiments and auto-scheduling", () => {
  it("picks an A/B winner only when every variant is measured", async () => {
    const { experiments } = await import("../lib/analytics");
    const mk = (id: string, score: number | null) => ({ id, platform: "bluesky", kind: "post", text: id, url: null, campaign: "ab:launch", simulated: false, published_at: new Date().toISOString(), engagement: null, score });
    expect(experiments([mk("a", 10), mk("b", 15)])[0]).toMatchObject({ name: "launch", lift: 50, winner: { id: "b" } });
    expect(experiments([mk("a", 10), mk("b", null)])[0].winner).toBeNull();
  });

  it("fills free days at the best hour, one post per day, never in the past", async () => {
    const { nextSlots } = await import("../lib/analytics");
    const now = new Date(2026, 9, 26, 12, 0); // Monday noon
    const taken = new Set([new Date(2026, 9, 27).toDateString()]); // Tuesday already has a post
    const out = nextSlots([{ weekday: 0, hour: 9, avg: 5, count: 2, label: "" }], 3, taken, now);
    expect(out.map((d) => [d.getDate(), d.getHours()])).toEqual([[28, 9], [29, 9], [30, 9]]); // Monday 9:00 has passed
  });
});
