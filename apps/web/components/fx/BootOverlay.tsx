"use client";

import { useEffect, useState } from "react";

const LINES = (label: string) => [
  `> mount module ${label.toUpperCase().replace(/\s+/g, "_")}`,
  "> sync agent mesh ········ OK",
  "> verify permissions ····· OK",
  "> stream telemetry ······· LIVE",
];

/** A short boot-up sequence shown over a tab when it opens. Purely visual: it never blocks clicks. */
export function BootOverlay({ label, run }: { label: string; run: number }) {
  const [shown, setShown] = useState(0);
  const [done, setDone] = useState(false);

  useEffect(() => {
    setShown(0);
    setDone(false);
    const timers = [0, 1, 2, 3].map((i) => setTimeout(() => setShown(i + 1), 90 + i * 110));
    timers.push(setTimeout(() => setDone(true), 820));
    return () => timers.forEach(clearTimeout);
  }, [run]);

  if (done) return null;
  return (
    <div aria-hidden className="boot-overlay pointer-events-none absolute inset-0 z-20 overflow-hidden rounded-xl">
      <div className="boot-sweep" />
      <div className="absolute left-4 top-4 space-y-1 font-mono text-[11px] text-cyan-300/90 md:left-6 md:top-6">
        {LINES(label)
          .slice(0, shown)
          .map((l) => (
            <div key={l} className="boot-line">
              {l}
            </div>
          ))}
        <div className="boot-bar mt-2 h-[2px] w-48 overflow-hidden rounded bg-cyan-400/10">
          <div className="h-full bg-gradient-to-r from-cyan-400 via-violet-400 to-fuchsia-400" style={{ width: `${shown * 25}%`, transition: "width .1s linear" }} />
        </div>
      </div>
    </div>
  );
}
