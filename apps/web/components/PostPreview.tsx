"use client";

import { Heart, MessageCircle, Repeat2, Share, ThumbsUp } from "lucide-react";

const STYLE: Record<string, { name: string; accent: string; radius: string; handle: (h: string) => string }> = {
  bluesky: { name: "Bluesky", accent: "#1185fe", radius: "12px", handle: (h) => `@${h}.bsky.social` },
  mastodon: { name: "Mastodon", accent: "#6364ff", radius: "8px", handle: (h) => `@${h}@mastodon.social` },
  x: { name: "X", accent: "#e7e9ea", radius: "16px", handle: (h) => `@${h}` },
  threads: { name: "Threads", accent: "#a1a1aa", radius: "18px", handle: (h) => h },
  linkedin: { name: "LinkedIn", accent: "#0a66c2", radius: "8px", handle: () => "Your name · 1st" },
  instagram: { name: "Instagram", accent: "#e1306c", radius: "10px", handle: (h) => h },
  facebook: { name: "Facebook", accent: "#1877f2", radius: "8px", handle: () => "Your page" },
  tiktok: { name: "TikTok", accent: "#25f4ee", radius: "10px", handle: (h) => `@${h}` },
  youtube: { name: "YouTube", accent: "#ff0033", radius: "10px", handle: () => "Your channel" },
};

function Rich({ text, accent }: { text: string; accent: string }) {
  const parts = text.split(/(https?:\/\/\S+|#\w+|@[\w.]+)/g);
  return (
    <>
      {parts.map((p, i) =>
        /^(https?:\/\/|#|@)/.test(p) ? (
          <span key={i} style={{ color: accent }}>
            {p.startsWith("http") && p.length > 32 ? `${p.slice(0, 30)}…` : p}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

/** An approximate preview of how the post will look on a platform: layout, text cut-off and counters. */
export function PostPreview({ platform, text, thread = [], limit, name = "yourbrand" }: { platform: string; text: string; thread?: string[]; limit?: number; name?: string }) {
  const st = STYLE[platform] || STYLE.bluesky;
  const parts = [text, ...thread].filter((t) => t.trim());
  const cut = platform === "linkedin" ? 210 : platform === "instagram" ? 125 : platform === "facebook" ? 480 : null;
  return (
    <div className="space-y-2">
      {(parts.length ? parts : [""]).map((t, i) => {
        const over = limit != null && t.length > limit;
        const shown = cut && t.length > cut && i === 0 ? t.slice(0, cut) : t;
        return (
          <div key={i} className="border border-[var(--color-line)] bg-[var(--color-panel)] p-3 text-sm" style={{ borderRadius: st.radius }}>
            <div className="mb-1.5 flex items-center gap-2">
              <span className="h-8 w-8 shrink-0 rounded-full" style={{ background: `linear-gradient(135deg, ${st.accent}, #a78bfa)` }} />
              <span className="min-w-0 leading-tight">
                <span className="block font-semibold">Your Brand</span>
                <span className="block truncate text-xs text-[var(--color-mute)]">{st.handle(name)} · now</span>
              </span>
              <span className="ml-auto text-[10px] uppercase tracking-wider" style={{ color: st.accent }}>
                {st.name}
                {parts.length > 1 ? ` · ${i + 1}/${parts.length}` : ""}
              </span>
            </div>
            <p className={`break-anywhere whitespace-pre-wrap ${t ? "" : "italic text-[var(--color-mute)]"}`}>
              {t ? <Rich text={shown} accent={st.accent} /> : "Your post appears here…"}
              {cut && t.length > cut && i === 0 && <span className="text-[var(--color-mute)]">… see more</span>}
            </p>
            <div className="mt-2 flex items-center gap-5 text-[var(--color-mute)]">
              {platform === "linkedin" ? <ThumbsUp size={14} /> : <MessageCircle size={14} />}
              <Repeat2 size={14} />
              <Heart size={14} />
              <Share size={14} />
              {limit != null && (
                <span className={`ml-auto font-mono text-[11px] ${over ? "text-red-300" : ""}`}>
                  {t.length}/{limit}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
