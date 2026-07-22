import { useCallback, useEffect, useState } from "react";

export type ThemeName =
  | "midnight"
  | "terminal"
  | "ocean"
  | "aurora"
  | "violet"
  | "ember"
  | "rose"
  | "graphite"
  | "exchange"
  | "ivory"
  | "custom";

export interface ThemeDefinition {
  id: ThemeName;
  label: string;
  description: string;
  tone: string;
  dark: boolean;
}

export interface CustomTheme {
  background: string;
  foreground: string;
  card: string;
  primary: string;
  muted: string;
  mutedForeground: string;
  border: string;
  success: string;
  danger: string;
  warning: string;
  info: string;
}

export const THEMES: ThemeDefinition[] = [
  { id: "midnight", label: "Midnight Lime", description: "Black glass with electric lime signals", tone: "#b6ff3b", dark: true },
  { id: "terminal", label: "Forest Terminal", description: "Deep exchange green with crisp chart ink", tone: "#84cc16", dark: true },
  { id: "ocean", label: "Ocean Desk", description: "Navy, cyan, and cool blue market depth", tone: "#38bdf8", dark: true },
  { id: "aurora", label: "Aurora", description: "Emerald interface with arctic highlights", tone: "#34d399", dark: true },
  { id: "violet", label: "Violet Pulse", description: "Purple research cockpit with blue data", tone: "#a78bfa", dark: true },
  { id: "ember", label: "Ember", description: "Warm charcoal with amber momentum", tone: "#fb923c", dark: true },
  { id: "rose", label: "Rose Quant", description: "Plum-black canvas with rose accents", tone: "#fb7185", dark: true },
  { id: "graphite", label: "Graphite", description: "Neutral monochrome for dense reports", tone: "#d4d4d8", dark: true },
  { id: "exchange", label: "Exchange Light", description: "Clean blue institutional workspace", tone: "#2563eb", dark: false },
  { id: "ivory", label: "Ivory Research", description: "Warm paper palette for long-form reading", tone: "#b45309", dark: false },
  { id: "custom", label: "Custom Live", description: "Your saved live colour system", tone: "linear-gradient(135deg,#b6ff3b,#38bdf8,#a78bfa)", dark: true },
];

export const DEFAULT_CUSTOM_THEME: CustomTheme = {
  background: "#07100c",
  foreground: "#e8f5ed",
  card: "#0c1712",
  primary: "#b6ff3b",
  muted: "#16231b",
  mutedForeground: "#91a598",
  border: "#26372c",
  success: "#76e66b",
  danger: "#ff6178",
  warning: "#ffc857",
  info: "#53d6c7",
};

const THEME_KEY = "qa-color-theme";
const CUSTOM_KEY = "qa-custom-theme";
const THEME_EVENT = "qa-theme-change";
const CUSTOM_PROPERTIES = [
  "--background", "--foreground", "--card", "--card-foreground", "--popover", "--popover-foreground",
  "--primary", "--primary-foreground", "--muted", "--muted-foreground", "--border", "--success",
  "--danger", "--warning", "--info", "--chart-grid", "--chart-text", "--chart-axis",
] as const;

const DARK_THEMES = new Set(THEMES.filter((theme) => theme.dark).map((theme) => theme.id));

function validHex(value: unknown): value is string {
  return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);
}

function hexToHsl(hex: string): string {
  const value = hex.slice(1);
  const r = parseInt(value.slice(0, 2), 16) / 255;
  const g = parseInt(value.slice(2, 4), 16) / 255;
  const b = parseInt(value.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const lightness = (max + min) / 2;
  const delta = max - min;
  let hue = 0;
  if (delta) {
    if (max === r) hue = ((g - b) / delta) % 6;
    else if (max === g) hue = (b - r) / delta + 2;
    else hue = (r - g) / delta + 4;
    hue *= 60;
    if (hue < 0) hue += 360;
  }
  const saturation = delta === 0 ? 0 : delta / (1 - Math.abs(2 * lightness - 1));
  return `${Math.round(hue)} ${Math.round(saturation * 100)}% ${Math.round(lightness * 100)}%`;
}

function contrastForeground(hex: string): string {
  const value = hex.slice(1);
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return ((r * 299 + g * 587 + b * 114) / 1000) > 150 ? "220 35% 7%" : "0 0% 100%";
}

export function getCustomTheme(): CustomTheme {
  try {
    const parsed = JSON.parse(localStorage.getItem(CUSTOM_KEY) || "{}") as Partial<CustomTheme>;
    return Object.fromEntries(Object.entries(DEFAULT_CUSTOM_THEME).map(([key, fallback]) => [key, validHex(parsed[key as keyof CustomTheme]) ? parsed[key as keyof CustomTheme] : fallback])) as unknown as CustomTheme;
  } catch {
    return { ...DEFAULT_CUSTOM_THEME };
  }
}

function clearCustomProperties() {
  for (const property of CUSTOM_PROPERTIES) document.documentElement.style.removeProperty(property);
}

function applyCustomTheme(theme: CustomTheme) {
  const root = document.documentElement;
  const values: Record<string, string> = {
    "--background": hexToHsl(theme.background),
    "--foreground": hexToHsl(theme.foreground),
    "--card": hexToHsl(theme.card),
    "--card-foreground": hexToHsl(theme.foreground),
    "--popover": hexToHsl(theme.card),
    "--popover-foreground": hexToHsl(theme.foreground),
    "--primary": hexToHsl(theme.primary),
    "--primary-foreground": contrastForeground(theme.primary),
    "--muted": hexToHsl(theme.muted),
    "--muted-foreground": hexToHsl(theme.mutedForeground),
    "--border": hexToHsl(theme.border),
    "--success": hexToHsl(theme.success),
    "--danger": hexToHsl(theme.danger),
    "--warning": hexToHsl(theme.warning),
    "--info": hexToHsl(theme.info),
    "--chart-grid": hexToHsl(theme.muted),
    "--chart-text": hexToHsl(theme.mutedForeground),
    "--chart-axis": hexToHsl(theme.border),
  };
  for (const [property, value] of Object.entries(values)) root.style.setProperty(property, value);
}

function applyTheme(theme: ThemeName) {
  const dark = DARK_THEMES.has(theme);
  document.documentElement.dataset.theme = theme;
  document.documentElement.classList.toggle("dark", dark);
  if (theme === "custom") applyCustomTheme(getCustomTheme());
  else clearCustomProperties();
  localStorage.setItem(THEME_KEY, theme);
  localStorage.setItem("qa-theme", dark ? "dark" : "light");
}

export function saveCustomTheme(theme: CustomTheme) {
  localStorage.setItem(CUSTOM_KEY, JSON.stringify(theme));
  if (document.documentElement.dataset.theme === "custom") applyCustomTheme(theme);
  window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: { theme: "custom" } }));
}

function initialTheme(): ThemeName {
  const saved = localStorage.getItem(THEME_KEY) as ThemeName | null;
  if (saved && THEMES.some((theme) => theme.id === saved)) return saved;
  const legacy = localStorage.getItem("qa-theme");
  if (legacy === "light") return "ivory";
  if (legacy === "dark") return "midnight";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "midnight" : "exchange";
}

export function useDarkMode() {
  const [theme, setThemeState] = useState<ThemeName>(initialTheme);
  const [, setRevision] = useState(0);
  const dark = DARK_THEMES.has(theme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    const synchronize = (event: Event) => {
      const detail = (event as CustomEvent<{ theme?: ThemeName }>).detail;
      const next = detail?.theme ?? initialTheme();
      setThemeState(next);
      setRevision((value) => value + 1);
    };
    const synchronizeStorage = () => synchronize(new CustomEvent(THEME_EVENT, { detail: { theme: initialTheme() } }));
    window.addEventListener(THEME_EVENT, synchronize);
    window.addEventListener("storage", synchronizeStorage);
    return () => {
      window.removeEventListener(THEME_EVENT, synchronize);
      window.removeEventListener("storage", synchronizeStorage);
    };
  }, []);

  const setTheme = useCallback((next: ThemeName) => {
    applyTheme(next);
    setThemeState(next);
    window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: { theme: next } }));
  }, []);

  return {
    dark,
    theme,
    setTheme,
    toggle: () => setTheme(DARK_THEMES.has(theme) ? "ivory" : "midnight"),
  };
}
