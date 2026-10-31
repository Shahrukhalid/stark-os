import type { PublishedPost } from "./types";

export interface Features {
  length: "short" | "medium" | "long";
  hashtags: "none" | "few" | "many";
  question: boolean;
  link: boolean;
  emoji: boolean;
}

export interface ScoreResult {
  score: number; // 0-100, 50 = your average
  basis: "history" | "guidance";
  tips: string[];
  measured: number;
}

const EMOJI = /\p{Extended_Pictographic}/u;

export function features(text: string): Features {
  const len = text.trim().length;
  const tags = (text.match(/(^|\s)#\w+/g) || []).length;
  return {
    length: len < 80 ? "short" : len <= 220 ? "medium" : "long",
    hashtags: tags === 0 ? "none" : tags <= 2 ? "few" : "many",
    question: /\?\s*$|\?\s/.test(text),
    link: /https?:\/\//.test(text),
    emoji: EMOJI.test(text),
  };
}

const LABEL: Record<string, string> = {
  "length:short": "short posts (under 80 characters)",
  "length:medium": "medium posts (80-220 characters)",
  "length:long": "long posts (over 220 characters)",
  "hashtags:none": "no hashtags",
  "hashtags:few": "1-2 hashtags",
  "hashtags:many": "3 or more hashtags",
  "question:true": "ending with a question",
  "question:false": "no question",
  "link:true": "a link",
  "link:false": "no link",
  "emoji:true": "an emoji",
  "emoji:false": "no emoji",
};

/**
 * Predicts how a draft will do compared with your own average, from what your measured posts with the same
 * traits earned. With fewer than 5 measured posts it falls back to general guidance and says so.
 */
export function scoreDraft(text: string, history: PublishedPost[]): ScoreResult {
  const f = features(text);
  const measured = history.filter((p) => p.score != null);
  if (!text.trim()) return { score: 0, basis: "guidance", tips: ["Write something first."], measured: measured.length };
  if (measured.length < 5) {
    let s = 50;
    const tips: string[] = [];
    if (f.length === "medium") s += 10;
    else tips.push(f.length === "short" ? "Add a little context: 80-220 characters usually do best." : "Shorter is usually better: try to stay under 220 characters.");
    if (f.hashtags === "few") s += 8;
    else tips.push(f.hashtags === "none" ? "Add one or two relevant hashtags so people can find it." : "Use at most two hashtags; more looks like spam.");
    if (f.question) s += 8;
    else tips.push("Ending with a question invites replies.");
    if (f.emoji) s += 4;
    return { score: Math.max(0, Math.min(100, s)), basis: "guidance", tips: tips.slice(0, 3), measured: measured.length };
  }
  const avg = measured.reduce((a, p) => a + (p.score ?? 0), 0) / measured.length || 1;
  let ratio = 1;
  const effects: { key: string; r: number; n: number }[] = [];
  for (const [k, v] of Object.entries(f)) {
    const same = measured.filter((p) => String((features(p.text) as any)[k]) === String(v));
    if (same.length < 2) continue;
    const r = same.reduce((a, p) => a + (p.score ?? 0), 0) / same.length / avg;
    ratio *= Math.max(0.6, Math.min(1.6, r));
    effects.push({ key: `${k}:${v}`, r, n: same.length });
  }
  const tips: string[] = [];
  for (const [k] of Object.entries(f)) {
    // the best-performing alternative for this trait, if it clearly beats what the draft has
    const options = Object.keys(LABEL).filter((x) => x.startsWith(`${k}:`));
    let best: { key: string; r: number } | null = null;
    for (const o of options) {
      const val = o.split(":")[1];
      const same = measured.filter((p) => String((features(p.text) as any)[k]) === val);
      if (same.length < 2) continue;
      const r = same.reduce((a, p) => a + (p.score ?? 0), 0) / same.length / avg;
      if (!best || r > best.r) best = { key: o, r };
    }
    const mine = effects.find((e) => e.key.startsWith(`${k}:`));
    if (best && mine && best.key !== mine.key && best.r > mine.r * 1.25) tips.push(`Your posts with ${LABEL[best.key]} earn ${Math.round(best.r * 100)}% of your average engagement; this draft has ${LABEL[mine.key]}.`);
  }
  return { score: Math.round(Math.max(0, Math.min(100, 50 * ratio))), basis: "history", tips: tips.slice(0, 3), measured: measured.length };
}

/** The next free posting-plan slot (weekday 0 = Monday, "HH:MM" local time) not already taken. */
export function nextPlanSlot(slots: { weekday: number; time: string }[], taken: Date[], now = new Date(), days = 28): Date | null {
  const busy = new Set(taken.map((d) => `${d.toDateString()} ${d.getHours()}:${d.getMinutes()}`));
  for (let i = 0; i < days; i++) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i);
    const wd = (day.getDay() + 6) % 7;
    for (const s of [...slots].filter((x) => x.weekday === wd).sort((a, b) => a.time.localeCompare(b.time))) {
      const [h, m] = s.time.split(":").map(Number);
      const when = new Date(day.getFullYear(), day.getMonth(), day.getDate(), h, m);
      if (when.getTime() > now.getTime() + 5 * 60_000 && !busy.has(`${when.toDateString()} ${h}:${m}`)) return when;
    }
  }
  return null;
}
