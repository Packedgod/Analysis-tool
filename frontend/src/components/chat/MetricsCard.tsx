import { memo } from "react";
import { cn } from "@/lib/utils";
import { getMetricLabel, DISPLAY_ORDER, formatMetricVal, metricSentiment } from "@/lib/formatters";

const SENTIMENT = {
  positive: "text-success",
  neutral: "text-foreground",
  negative: "text-danger",
} as const;

interface Props {
  metrics: Record<string, number>;
  compact?: boolean;
}

export const MetricsCard = memo(function MetricsCard({ metrics, compact = false }: Props) {
  const entries = DISPLAY_ORDER
    .filter((k) => metrics[k] != null)
    .map((k) => ({ k, v: metrics[k] }));

  if (entries.length === 0) return null;

  const shown = compact ? entries.slice(0, 6) : entries;

  return (
    <div className={cn(
      "grid gap-2 rounded-2xl border border-border/70 bg-background/40 p-2 shadow-[inset_0_1px_0_hsl(var(--foreground)/0.025)]",
      compact ? "grid-cols-3" : "grid-cols-[repeat(auto-fit,minmax(120px,1fr))]"
    )}>
      {shown.map(({ k, v }) => (
        <div key={k} className="rounded-xl border border-transparent px-2 py-2.5 text-center transition hover:border-primary/20 hover:bg-primary/5">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide font-medium">
            {getMetricLabel(k)}
          </p>
          <p className={cn(
            "mt-1 font-mono text-base font-bold tabular-nums",
            SENTIMENT[metricSentiment(k, v)]
          )}>
            {formatMetricVal(k, v)}
          </p>
        </div>
      ))}
    </div>
  );
});
