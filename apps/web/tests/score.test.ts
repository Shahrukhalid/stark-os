import { describe, expect, it } from "vitest";
import { features, nextPlanSlot, scoreDraft } from "../lib/score";
import type { PublishedPost } from "../lib/types";

const p = (text: string, score: number): PublishedPost => ({ id: text, platform: "bluesky", kind: "post", text, url: null, campaign: "", simulated: false, published_at: new Date().toISOString(), engagement: { likes: score, reposts: 0, replies: 0 }, score });

describe("draft score", () => {
  it("reads post traits", () => {
    expect(features("What do you think? #ai #ml https://x.example 🚀")).toEqual({ length: "short", hashtags: "few", question: true, link: true, emoji: true });
  });
  it("uses general guidance without history and your own results with it", () => {
    const g = scoreDraft("Short", []);
    expect(g.basis).toBe("guidance");
    expect(g.tips.length).toBeGreaterThan(0);
    const hist = [p("Which do you prefer?", 30), p("Thoughts on this?", 28), p("We shipped it.", 5), p("Release notes out.", 4), p("Another update.", 6)];
    const q = scoreDraft("Would you use this?", hist);
    const s = scoreDraft("New update is live.", hist);
    expect(q.basis).toBe("history");
    expect(q.score).toBeGreaterThan(s.score);
    expect(s.tips.join(" ")).toMatch(/ending with a question/);
  });
});

describe("posting plan slots", () => {
  it("returns the next free slot, skipping taken ones", () => {
    const now = new Date(2026, 9, 26, 12, 0); // Monday noon
    const slots = [{ weekday: 0, time: "09:00" }, { weekday: 0, time: "18:00" }, { weekday: 2, time: "10:00" }];
    expect(nextPlanSlot(slots, [], now)).toEqual(new Date(2026, 9, 26, 18, 0));
    expect(nextPlanSlot(slots, [new Date(2026, 9, 26, 18, 0)], now)).toEqual(new Date(2026, 9, 28, 10, 0));
    expect(nextPlanSlot([], [], now)).toBeNull();
  });
});

describe("carousel slides", () => {
  it("splits on blank lines and long paragraphs, max 10 slides", async () => {
    const { slides } = await import("../lib/cards");
    expect(slides("One.\n\nTwo.")).toEqual(["One.", "Two."]);
    const long = Array.from({ length: 12 }, (_, i) => `Sentence number ${i} is here.`).join(" ");
    const out = slides(long, 80);
    expect(out.length).toBeGreaterThan(2);
    expect(out.every((s) => s.length <= 80)).toBe(true);
    expect(slides(Array.from({ length: 15 }, (_, i) => `S${i}`).join("\n\n"))).toHaveLength(10);
  });
});
