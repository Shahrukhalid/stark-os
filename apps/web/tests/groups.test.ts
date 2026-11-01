import { describe, expect, it } from "vitest";
import { groupBy } from "../lib/analytics";
import type { PublishedPost } from "../lib/types";

const p = (campaign: string, brand: string, likes: number | null, simulated = false): PublishedPost => ({
  id: Math.random().toString(), platform: "bluesky", kind: "post", text: "x", url: null, campaign, brand, simulated,
  published_at: new Date().toISOString(), engagement: likes == null ? null : { likes, reposts: 1, replies: 1 },
  score: likes == null ? null : likes + 4,
});

describe("groupBy", () => {
  it("adds up real engagement per campaign, best first, and skips simulated posts", () => {
    const rows = groupBy([p("launch", "Acme", 10), p("launch", "Acme", 20), p("", "Beta", 2), p("launch", "Acme", 99, true), p("tips", "", null)], "campaign");
    expect(rows.map((r) => r.name)).toEqual(["launch", "(none)", "tips"]);
    expect(rows[0]).toMatchObject({ posts: 2, measured: 2, likes: 30, reposts: 2, replies: 2, avg: 19 });
    expect(rows[2].avg).toBeNull();
  });
  it("groups by brand", () => {
    expect(groupBy([p("a", "Acme", 1), p("b", "Acme", 3)], "brand")).toEqual([
      { name: "Acme", posts: 2, measured: 2, likes: 4, reposts: 2, replies: 2, avg: 6 },
    ]);
  });
});
