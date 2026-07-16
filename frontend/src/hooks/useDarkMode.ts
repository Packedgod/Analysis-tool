import { useEffect, useState } from "react";

export type ThemeName = "midnight" | "exchange" | "terminal" | "ivory";

export const THEMES: Array<{ id: ThemeName; label: string; tone: string }> = [
  { id: "midnight", label: "Midnight", tone: "#2dd4bf" },
  { id: "exchange", label: "Exchange", tone: "#2563eb" },
  { id: "terminal", label: "Terminal", tone: "#84cc16" },
  { id: "ivory", label: "Ivory", tone: "#b45309" },
];

const DARK_THEMES = new Set<ThemeName>(["midnight", "terminal"]);

function initialTheme(): ThemeName {
  const saved = localStorage.getItem("qa-color-theme") as ThemeName | null;
  if (saved && THEMES.some((theme) => theme.id === saved)) return saved;
  const legacy = localStorage.getItem("qa-theme");
  if (legacy === "light") return "ivory";
  if (legacy === "dark") return "midnight";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "midnight" : "exchange";
}

export function useDarkMode() {
  const [theme, setTheme] = useState<ThemeName>(initialTheme);
  const dark = DARK_THEMES.has(theme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("qa-color-theme", theme);
    localStorage.setItem("qa-theme", dark ? "dark" : "light");
  }, [dark, theme]);

  return {
    dark,
    theme,
    setTheme,
    toggle: () => setTheme((current) => (DARK_THEMES.has(current) ? "ivory" : "midnight")),
  };
}

