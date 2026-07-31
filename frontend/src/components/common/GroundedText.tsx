import { AlertTriangle, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";

/** Payload from the backend `report_audit` tool's `grounding` command. */
export interface GroundingReport {
  n_claims?: number | null;
  n_grounded?: number | null;
  n_ungrounded?: number | null;
  grounding_ratio?: number | null;
  ungrounded?: string[];
}

/**
 * Provenance banner for a generated report.
 *
 * The guarantee this product sells is that no figure is invented. That is only
 * credible if the *exceptions* are visible, so this states the ratio and names
 * every un-sourced figure rather than showing a reassuring green tick. A high
 * ratio is not "pass" — the un-sourced list is the actionable part.
 */
export function GroundingSummary({
  report,
  className,
}: {
  report?: GroundingReport | null;
  className?: string;
}) {
  if (!report || !report.n_claims) return null;
  const ungrounded = report.ungrounded ?? [];
  const clean = ungrounded.length === 0;
  const ratio = report.grounding_ratio ?? 0;

  return (
    <section className={cn("rounded-xl border bg-card/90 p-4", className)}>
      <div className="panel-head">
        <h3 className="panel-title">Numeric provenance</h3>
        <span className="font-mono text-[10px] text-muted-foreground">
          {report.n_grounded ?? 0}/{report.n_claims} traced
        </span>
      </div>

      <div className={cn("verdict", clean ? "verdict-pass" : "verdict-fail")}>
        {clean ? (
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" />
        ) : (
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
        )}
        <div className="min-w-0">
          <p className={cn("verdict-title", clean ? "text-success" : "text-danger")}>
            {clean
              ? "Every figure traces to a source"
              : `${ungrounded.length} figure${ungrounded.length === 1 ? "" : "s"} not traceable`}
          </p>
          <p className="mt-1 text-xs leading-5 text-foreground/80">
            {clean
              ? `All ${report.n_claims} numeric claims appear in the fetched sources.`
              : "These figures do not appear in the fetched sources. Verify or remove them before publishing — a derived number should be recomputed from sourced values."}
          </p>
          {!clean && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {ungrounded.slice(0, 24).map((figure, index) => (
                <span key={`${figure}-${index}`} className="unsourced font-mono text-[11px]">
                  {figure}
                </span>
              ))}
              {ungrounded.length > 24 && (
                <span className="font-mono text-[10px] text-muted-foreground">
                  +{ungrounded.length - 24} more
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", clean ? "bg-success" : "bg-warning")}
          style={{ width: `${Math.round(ratio * 100)}%` }}
          role="progressbar"
          aria-valuenow={Math.round(ratio * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Share of figures traced to a source"
        />
      </div>
    </section>
  );
}
