"use client";

import { useEffect, useState } from "react";

/** Types text out character by character, like a model streaming its answer. */
export function Typewriter({ text, speed = 14, className = "" }: { text: string; speed?: number; className?: string }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    if (!text) return;
    const step = Math.max(1, Math.ceil(text.length / 120));
    const t = setInterval(() => setN((v) => (v >= text.length ? (clearInterval(t), v) : v + step)), speed);
    return () => clearInterval(t);
  }, [text, speed]);
  const typing = n < text.length;
  return (
    <span className={className}>
      {text.slice(0, n)}
      {typing && <span className="caret" />}
    </span>
  );
}
