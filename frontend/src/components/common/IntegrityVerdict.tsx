import { ShieldCheck, ShieldAlert, ShieldQuestion, Clock, Info } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The overfitting-honesty payload emitted by the backend's validation step
 * (`backtest/overfitting.py`). Every field is optional because a degraded or
 * partial run must still render rather than blanking the panel.
 */
export interface OverfittingReport {
  sharpe_annualized?: number | null;
  probabilistic_sharpe_ratio?: number | null;
  deflated_sharpe_ratio?: number | null;
  deflated_benchmark_sharpe_annualized?: number | null;
  min_track_record_length_periods?: number | null;
  n_periods?: number | null;
  n_trials?: number | null;
  credible_at_95?: boolean | null;
  interpretation?: string | null;
  note?: string | null;
}

export interface PointInTime {
  as_of?: string | null;
  engaged?: boolean | null;
  rows_withheld?: number | null;
}

function pct(value?: number | null): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : `${(value * 100).toFixed(0)}%`;
}

function num(value?: number | null, digits = 2): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : value.toFixed(digits);
}

/**
 * Headline trust signal for a backtest.
 *
 * A raw Sharpe flatters every strategy; the deflated Sharpe is the number that
 * survives correction for track-record length, non-normal returns and — above
 * all — how many strategies were tried before this one was picked. Showing the
 * verdict *first*, above the metrics, is the whole point: the user should meet
 * "is this real?" before they meet "how good does it look?".
 */
export function IntegrityVerdict({
  report,
  pointInTime,
  className,
}: {
  report?: OverfittingReport | null;
  pointInTime?: PointInTime | null;
  className?: string;
}) {
  if (!report || report.note) {
    return (
      <div className={cn("verdict verdict-unknown", className)}>
        <ShieldQuestion className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div>
          <p className="verdict-title text-muted-foreground">Statistical credibility unavailable</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {report?.note ?? "This run has no overfitting-honesty statistics attached."}
          </p>
        </div>
      </div>
    );
  }

  const credible = report.credible_at_95 === true;
  const dsr = report.deflated_sharpe_ratio;
  const Icon = credible ? ShieldCheck : ShieldAlert;

  return (
    <section className={cn("space-y-2", className)}>
      <div className={cn("verdict", credible ? "verdict-pass" : "verdict-fail")}>
        <Icon
          className={cn("mt-0.5 h-4 w-4 shrink-0", credible ? "text-success" : "text-danger")}
          aria-hidden="true"
        />
        <div className="min-w-0">
          <p className={cn("verdict-title", credible ? "text-success" : "text-danger")}>
            {credible ? "Statistically credible" : "Not statistically credible"}
          </p>
          <p className="mt-1 text-xs leading-5 text-foreground/80">{report.interpretation}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <div className="stat-tile">
          <span className="stat-tile-label">Sharpe (raw)</span>
          <span className="stat-tile-value">{num(report.sharpe_annualized)}</span>
          <span className="stat-tile-sub">annualised, uncorrected</span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile-label">Deflated</span>
          <span
            className={cn("stat-tile-value", credible ? "val-up" : "val-down")}
            title="Probability the edge is real after correcting for multiple testing"
          >
            {pct(dsr)}
          </span>
          <span className="stat-tile-sub">confidence after {report.n_trials ?? 1} trial(s)</span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile-label">Luck bar</span>
          <span className="stat-tile-value">
            {num(report.deflated_benchmark_sharpe_annualized)}
          </span>
          <span className="stat-tile-sub">Sharpe expected by chance</span>
        </div>
        <div className="stat-tile">
          <span className="stat-tile-label">Min track record</span>
          <span className="stat-tile-value">
            {report.min_track_record_length_periods === null ||
            report.min_track_record_length_periods === undefined
              ? "∞"
              : Math.ceil(report.min_track_record_length_periods)}
          </span>
          <span className="stat-tile-sub">periods needed · have {report.n_periods ?? "—"}</span>
        </div>
      </div>

      {pointInTime?.engaged ? (
        <p className="flex items-center gap-1.5 font-mono text-[10px] text-muted-foreground">
          <Clock className="h-3 w-3 text-primary" />
          Point-in-time: computed as of {pointInTime.as_of}
          {pointInTime.rows_withheld ? ` · ${pointInTime.rows_withheld} future row(s) withheld` : ""}
        </p>
      ) : null}
    </section>
  );
}

/**
 * Multiple-testing verdict for a factor screen (the alpha-zoo bench).
 * The best IR out of hundreds screened is upward-biased; this says whether it
 * clears the bar luck alone would set.
 */
export function SelectionVerdict({
  selection,
  className,
}: {
  selection?: {
    n_trials?: number | null;
    best_score?: number | null;
    expected_best_under_null?: number | null;
    survives_selection?: boolean | null;
    interpretation?: string | null;
    note?: string | null;
    error?: string | null;
  } | null;
  className?: string;
}) {
  if (!selection || selection.note || selection.error) return null;
  const survives = selection.survives_selection === true;
  return (
    <div
      className={cn("verdict", survives ? "verdict-pass" : "verdict-fail", className)}
    >
      <Info
        className={cn("mt-0.5 h-4 w-4 shrink-0", survives ? "text-success" : "text-danger")}
        aria-hidden="true"
      />
      <div className="min-w-0">
        <p className={cn("verdict-title", survives ? "text-success" : "text-danger")}>
          {survives ? "Clears selection bias" : "Likely selection noise"}
        </p>
        <p className="mt-1 text-xs leading-5 text-foreground/80">{selection.interpretation}</p>
      </div>
    </div>
  );
}
