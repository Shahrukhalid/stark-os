export type ThemePreference = "light" | "dark" | "system";

export const THEME_KEY = "stark-theme";

export function readTheme(): ThemePreference {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" || t === "system" ? t : "system";
  } catch {
    return "system";
  }
}

export function saveTheme(theme: ThemePreference) {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* storage blocked: the choice still applies for this session */
  }
}

export function applyTheme(theme: ThemePreference) {
  const resolved = theme === "system" ? (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : theme;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
}
