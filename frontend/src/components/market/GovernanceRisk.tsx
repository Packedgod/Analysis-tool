import { AlertTriangle, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

/** Payload from the backend `get_promoter_pledge` tool. */
export interface PromoterRisk {
  status?: string;
  latest_period?: string | null;
  pledge_severity?: "none" | "low" | "watch" | "high" | "severe" | "unknown" | string;
  pledge_pct_of_promoter?: number | null;
  pledge_pct_of_total_equity?: number | null;
  pledge_qoq_change?: number | null;
  promoter_stake_qoq_change?: number | null;
  fii_trend_window?: number | null;
  dii_trend_window?: number | null;
  periods_analyzed?: number | null;
  flags?: string[];
  assessment?: string | null;
}

const SEVERITY_PILL: Record<string, string> = {
  severe: "pill-danger",
  high: "pill-danger",
  watch: "pill-warning",
  low: "pill-muted",
  none: "pill-success",
  unknown: "pill-muted",
};

function pp(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}pp`;
}

function Delta({ value, invert = false }: { value?: number | null; invert?: boolean }) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return <span className="val-flat">—</span>;
  }
  // For pledge, rising is bad; for stake/flows, rising is good.
  const good = invert ? value < 0 : value > 0;
  const Icon = value >= 0 ? TrendingUp : TrendingDown;
  return (
    <span className={cn("inline-flex items-center gap-1", good ? "val-up" : "val-down")}>
      <Icon className="h-3 w-3" />
      {pp(value)}
    </span>
  );
}

/**
 * Promoter pledge / shareholding governance panel.
 *
 * Pledging is the highest-signal India-specific red flag and is normally shown —
 * where it is shown at all — as one stale percentage. The point of this panel is
 * the *direction of travel*: pledge rising while the promoter stake falls is the
 * combination that preceded India's most notable blow-ups, so that pattern is
 * given its own escalated treatment rather than being buried in a table.
 */
export function GovernanceRisk({
  risk,
  className,
}: {
  risk?: PromoterRisk | null;
  className?: string;
}) {
  if (!risk || risk.status !== "ok") return null;

  const severity = String(risk.pledge_severity ?? "unknown");
  const flags = risk.flags ?? [];
  const escalating = flags.includes("escalating_governance_risk");
  const clean = severity === "none";

  return (
    <section className={cn("rounded-xl border bg-card/90 p-4", className)}>
      <div className="panel-head">
        <h3 className="panel-title">Governance · promoter pledge</h3>
        <span className="font-mono text-[10px] text-muted-foreground">
          {risk.latest_period ?? "—"} · {risk.periods_analyzed ?? 0}q
        </span>
      </div>

      {escalating ? (
        <div className="verdict verdict-fail mb-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <div>
            <p className="verdict-title text-danger">Escalating governance risk</p>
            <p className="mt-1 text-xs leading-5 text-foreground/80">{risk.assessment}</p>
          </div>
        </div>
      ) : clean ? (
        <div className="verdict verdict-pass mb-3">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" />
          <div>
            <p className="verdict-title text-success">No pledging reported</p>
            <p className="mt-1 text-xs leading-5 text-foreground/80">{risk.assessment}</p>
          </div>
        </div>
      ) : (
        <p className="mb-3 text-xs leading-5 text-muted-foreground">{risk.assessment}</p>
      )}

      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <div className="stat-tile">
          <span className="stat-tile-label">Pledged</span>
          <span
            className={cn(
              "stat-tile-value",
              severity === "severe" || severity === "high" ? "val-down" : undefined,
            )}
          >
            {risk.pledge_pct_of_promoter === null || risk.pledge_pct_of_promoter === undefined
              ? "—"
              : `${risk.pledge_pct_of_promoter.toFixed(1)}%`}
          </span>
          <span className="stat-tile-sub">
            of promoter holding ·{" "}
            {risk.pledge_pct_of_total_equity === null || risk.pledge_pct_of_total_equity === undefined
              ? "—"
              : `${risk.pledge_pct_of_total_equity.toFixed(1)}% of equity`}
          </span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile-label">Pledge QoQ</span>
          <span className="stat-tile-value text-[15px]">
            <Delta value={risk.pledge_qoq_change} invert />
          </span>
          <span className="stat-tile-sub">quarter-on-quarter</span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile-label">Promoter stake</span>
          <span className="stat-tile-value text-[15px]">
            <Delta value={risk.promoter_stake_qoq_change} />
          </span>
          <span className="stat-tile-sub">quarter-on-quarter</span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile-label">FII trend</span>
          <span className="stat-tile-value text-[15px]">
            <Delta value={risk.fii_trend_window} />
          </span>
          <span className="stat-tile-sub">across window</span>
        </div>
      </div>

      {flags.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          <span className={cn("pill", SEVERITY_PILL[severity] ?? "pill-muted")}>{severity}</span>
          {flags
            .filter((f) => f !== "escalating_governance_risk")
            .map((flag) => (
              <span key={flag} className="pill pill-muted">
                {flag.replace(/_/g, " ")}
              </span>
            ))}
        </div>
      ) : null}
    </section>
  );
}
