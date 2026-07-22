import { useState } from "react";
import { Check, Copy, Palette, RotateCcw, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  DEFAULT_CUSTOM_THEME,
  THEMES,
  getCustomTheme,
  saveCustomTheme,
  useDarkMode,
  type CustomTheme,
} from "@/hooks/useDarkMode";

const COLOR_FIELDS: Array<{ key: keyof CustomTheme; label: string }> = [
  { key: "background", label: "Canvas" },
  { key: "card", label: "Panels" },
  { key: "foreground", label: "Text" },
  { key: "primary", label: "Primary" },
  { key: "muted", label: "Muted surface" },
  { key: "mutedForeground", label: "Muted text" },
  { key: "border", label: "Borders" },
  { key: "success", label: "Positive" },
  { key: "danger", label: "Negative" },
  { key: "warning", label: "Warning" },
  { key: "info", label: "Information" },
];

export function ThemeStudio() {
  const { theme, setTheme } = useDarkMode();
  const [custom, setCustom] = useState<CustomTheme>(getCustomTheme);
  const [copied, setCopied] = useState(false);

  const updateCustom = (key: keyof CustomTheme, value: string) => {
    const next = { ...custom, [key]: value };
    setCustom(next);
    if (theme !== "custom") setTheme("custom");
    saveCustomTheme(next);
  };

  const resetCustom = () => {
    const next = { ...DEFAULT_CUSTOM_THEME };
    setCustom(next);
    setTheme("custom");
    saveCustomTheme(next);
  };

  const copyTheme = async () => {
    await navigator.clipboard.writeText(JSON.stringify(custom, null, 2));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };

  return (
    <section className="terminal-card overflow-hidden rounded-2xl border bg-card/80 shadow-sm">
      <div className="flex flex-col gap-3 border-b px-5 py-5 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Palette className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold">Live theme studio</h2>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Switch complete colour systems instantly, or tune your own palette. Changes affect dashboards, reports, and charts and persist in this browser.
          </p>
        </div>
        <span className="inline-flex w-fit items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary">
          <Sparkles className="h-3.5 w-3.5" /> Live preview
        </span>
      </div>

      <div className="space-y-6 p-5">
        <div>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold">Generated themes</h3>
              <p className="text-xs text-muted-foreground">Choose a ready-to-use desk.</p>
            </div>
            <span className="font-mono text-[10px] text-muted-foreground">{THEMES.length - 1} presets</span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {THEMES.filter((item) => item.id !== "custom").map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setTheme(item.id)}
                aria-pressed={theme === item.id}
                className={cn(
                  "group min-h-[108px] rounded-xl border p-3 text-left transition hover:-translate-y-0.5 hover:border-primary/35",
                  theme === item.id ? "border-primary/55 bg-primary/8 ring-2 ring-primary/15" : "bg-background/35",
                )}
              >
                <span className="mb-5 flex items-center gap-1.5">
                  {[item.tone, item.dark ? "#0b1110" : "#f4f4ef", item.dark ? "#27332d" : "#d7d9d3"].map((colour, index) => (
                    <span key={index} className="h-4 w-4 rounded-full border border-white/10" style={{ background: colour }} />
                  ))}
                  {theme === item.id && <Check className="ml-auto h-4 w-4 text-primary" />}
                </span>
                <span className="block text-xs font-semibold">{item.label}</span>
                <span className="mt-1 block text-[10px] leading-4 text-muted-foreground">{item.description}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border bg-background/30 p-4">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-primary" />
                <h3 className="text-sm font-semibold">Custom Live</h3>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">Every colour applies as you move it—no save button or reload.</p>
            </div>
            <div className="flex gap-2">
              <button type="button" onClick={resetCustom} className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground">
                <RotateCcw className="h-3.5 w-3.5" /> Reset
              </button>
              <button type="button" onClick={copyTheme} className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs text-muted-foreground transition hover:bg-muted hover:text-foreground">
                {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />} {copied ? "Copied" : "Export JSON"}
              </button>
            </div>
          </div>

          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
            {COLOR_FIELDS.map(({ key, label }) => (
              <label key={key} className="group flex items-center gap-2 rounded-xl border bg-card/60 p-2.5 transition focus-within:border-primary/50 hover:border-border/90">
                <input
                  type="color"
                  value={custom[key]}
                  onInput={(event) => updateCustom(key, event.currentTarget.value)}
                  aria-label={`${label} colour`}
                  className="h-9 w-9 cursor-pointer rounded-lg border-0 bg-transparent p-0"
                />
                <span className="min-w-0">
                  <span className="block text-[10px] font-medium text-muted-foreground">{label}</span>
                  <span className="block truncate font-mono text-[10px] uppercase">{custom[key]}</span>
                </span>
              </label>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
