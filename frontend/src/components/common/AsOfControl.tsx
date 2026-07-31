import { useId } from "react";
import { Clock, History } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Point-in-time ("time machine") control.
 *
 * Engaging a date makes the backend answer as of that day — no price, filing,
 * headline or search result published later can reach the computation. The
 * control states that guarantee explicitly, because the entire value of the
 * feature is the user trusting that "as of 2021" really means it.
 */
export function AsOfControl({
  value,
  onChange,
  className,
  max,
}: {
  value: string | null;
  onChange: (next: string | null) => void;
  className?: string;
  max?: string;
}) {
  const id = useId();
  const engaged = Boolean(value);

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-2 rounded-lg border px-3 py-2 transition-colors",
        engaged ? "border-primary/40 bg-primary/[0.06]" : "bg-background/40",
        className,
      )}
    >
      <label
        htmlFor={id}
        className="flex items-center gap-1.5 font-mono text-[9px] font-semibold uppercase tracking-[0.16em] text-muted-foreground"
      >
        {engaged ? (
          <History className="h-3.5 w-3.5 text-primary" />
        ) : (
          <Clock className="h-3.5 w-3.5" />
        )}
        Point in time
      </label>

      <input
        id={id}
        type="date"
        max={max}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
        className="rounded border bg-background px-2 py-1 font-mono text-[11px] tabular-nums text-foreground outline-none focus:border-primary/60"
        aria-label="Run this study as of a past date"
      />

      {engaged ? (
        <>
          <span className="pill pill-success">as-of active</span>
          <button
            type="button"
            onClick={() => onChange(null)}
            className="font-mono text-[10px] text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            live
          </button>
          <span className="w-full text-[10px] leading-4 text-muted-foreground">
            Nothing published after {value} can reach this result — prices, filings, news and
            search evidence are all bounded.
          </span>
        </>
      ) : (
        <span className="font-mono text-[10px] text-muted-foreground">live data</span>
      )}
    </div>
  );
}
