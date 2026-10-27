"use client";

import { useEffect } from "react";
import { applyTheme, readTheme } from "@/lib/theme";

/** Keeps the app-wide theme in step with the device setting while "System" is selected. */
export function ThemeSync() {
  useEffect(() => {
    applyTheme(readTheme());
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
      if (readTheme() === "system") applyTheme("system");
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return null;
}
