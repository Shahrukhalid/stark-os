/** Mirrors services/api/stark/core/addressing.py so voice commands can switch agents instantly. */

export const ALIASES: Record<string, string[]> = {
  jarvis: ["jarvis", "j.a.r.v.i.s.", "j.a.r.v.i.s", "j a r v i s"],
  friday: ["friday", "f.r.i.d.a.y.", "f.r.i.d.a.y"],
  edith: ["edith", "e.d.i.t.h.", "e.d.i.t.h"],
  ultron: ["ultron"],
  jocasta: ["jocasta", "jocaster"],
  dum_e: ["dum-e", "dum-e.", "d.u.m.-e.", "d.u.m.-e", "dumb-e", "dummy", "dum e", "dumbie"],
  u: ["u"],
};

const PREFIX = /^\s*(?:hey|ok|okay|hi|yo)?\s*,?\s*/i;

export function parseAddress(text: string): { agent: string | null; rest: string } {
  const stripped = text.replace(PREFIX, "");
  const lower = stripped.toLowerCase();
  let best: { agent: string; len: number } | null = null;
  for (const [agent, names] of Object.entries(ALIASES)) {
    for (const name of names) {
      if (!lower.startsWith(name)) continue;
      const rest = stripped.slice(name.length);
      if (rest && /^[a-z0-9]/i.test(rest)) continue;
      if (agent === "u" && !/^\s*[,:]/.test(rest)) continue;
      if (!best || name.length > best.len) best = { agent, len: name.length };
    }
  }
  if (!best) return { agent: null, rest: text.trim() };
  const remaining = stripped.slice(best.len).replace(/^[\s,:;.!-]+/, "").trim();
  return { agent: best.agent, rest: remaining || text.trim() };
}

/** Wake-word check for always-listening mode: "hey jarvis", "friday", ... at the start of an utterance. */
export function detectWake(text: string): string | null {
  const { agent } = parseAddress(text);
  return agent;
}
