"use client";

import { useEffect, useState } from "react";

/** Visual effects level: "max" = particles, scanlines and boot sequences; "calm" = animations only; "off" = none. */
export type FxLevel = "max" | "calm" | "off";

export const FX_KEY = "stark-fx";
const EVENT = "stark-fx-change";

export function readFx(): FxLevel {
  try {
    const v = localStorage.getItem(FX_KEY);
    if (v === "max" || v === "calm" || v === "off") return v;
  } catch {
    /* storage blocked */
  }
  if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return "off";
  return "max";
}

export function applyFx(level: FxLevel) {
  document.documentElement.dataset.fx = level;
}

export function saveFx(level: FxLevel) {
  try {
    localStorage.setItem(FX_KEY, level);
  } catch {
    /* the choice still applies for this session */
  }
  applyFx(level);
  window.dispatchEvent(new CustomEvent(EVENT, { detail: level }));
}

/** Current effects level, kept in sync across components. */
export function useFx(): FxLevel {
  const [fx, setFx] = useState<FxLevel>("calm");
  useEffect(() => {
    const cur = readFx();
    setFx(cur);
    applyFx(cur);
    const on = (e: Event) => setFx((e as CustomEvent<FxLevel>).detail);
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  return fx;
}
