"use client";

import { useEffect, useRef, useState } from "react";
import { ParticleAvatar, type AvatarShape, type AvatarState, type AvatarTheme } from "@/lib/particles";
import type { Agent } from "@/lib/types";

const SHAPES: AvatarShape[] = ["core", "female", "male"];
const THEMES: Record<string, Omit<AvatarTheme, "color">> = {
  vision: { accent: "#fde68a", energy: "grid" }, // ordered, synthetic shimmer with golden sparks
  wanda: { accent: "#fda4af", energy: "flow" }, // wisps that rise like smoke
};

function defaultShape(id: string): AvatarShape {
  return id === "wanda" ? "female" : id === "vision" ? "male" : "core";
}

function readShape(id: string): AvatarShape {
  try {
    const v = window.localStorage.getItem(`stark.presence.${id}`) as AvatarShape | null;
    return v && SHAPES.includes(v) ? v : defaultShape(id);
  } catch {
    return defaultShape(id);
  }
}

/** The assistant's particle presence, with a Core / Female / Male switch remembered per assistant. */
export function ParticlePresence({ agent, state }: { agent?: Agent; state: AvatarState }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const scene = useRef<ParticleAvatar | null>(null);
  const id = agent?.id || "core";
  const [shape, setShape] = useState<AvatarShape>("core");

  useEffect(() => {
    if (!canvas.current) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const s = new ParticleAvatar(canvas.current, { color: "#22d3ee", accent: "#fde68a", energy: "flow" }, reduced);
    scene.current = s;
    s.start();
    return () => s.stop();
  }, []);

  useEffect(() => {
    const color = agent?.color || "#22d3ee";
    scene.current?.setTheme({ color, ...(THEMES[id] || { accent: "#e2e8f0", energy: "flow" }) });
    const next = readShape(id);
    setShape(next);
    scene.current?.setShape(next);
  }, [id, agent?.color]);

  useEffect(() => {
    scene.current?.setState(state);
  }, [state]);

  const choose = (s: AvatarShape) => {
    setShape(s);
    scene.current?.setShape(s);
    try {
      window.localStorage.setItem(`stark.presence.${id}`, s);
    } catch {
      /* private window */
    }
  };

  return (
    <div className="flex flex-col items-center">
      <canvas
        ref={canvas}
        className="aspect-[6/7] w-full max-w-[300px]"
        role="img"
        aria-label={`${agent?.name || "Assistant"} is ${state}`}
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          scene.current?.setPointer((e.clientX - r.left) / r.width - 0.5, (e.clientY - r.top) / r.height - 0.5);
        }}
        onPointerLeave={() => scene.current?.setPointer(0, 0)}
      />
      <div className="mt-2 flex rounded-full border border-white/10 bg-white/5 p-1 text-[11px] font-semibold tracking-[0.25em]" role="radiogroup" aria-label="Presence">
        {SHAPES.map((s) => (
          <button
            key={s}
            type="button"
            role="radio"
            aria-checked={shape === s}
            onClick={() => choose(s)}
            className={`rounded-full px-4 py-1.5 transition ${shape === s ? "bg-white/10 text-white" : "text-[var(--color-mute)] hover:text-white"}`}
            style={shape === s ? { boxShadow: `inset 0 0 0 1px ${agent?.color || "#22d3ee"}88` } : undefined}
          >
            {s.toUpperCase()}
          </button>
        ))}
      </div>
    </div>
  );
}
