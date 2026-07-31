import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { IntegrityVerdict, SelectionVerdict } from "../IntegrityVerdict";
import { GovernanceRisk } from "@/components/market/GovernanceRisk";

describe("IntegrityVerdict", () => {
  const credible = {
    sharpe_annualized: 1.95,
    deflated_sharpe_ratio: 0.98,
    deflated_benchmark_sharpe_annualized: 0.4,
    min_track_record_length_periods: 120,
    n_periods: 500,
    n_trials: 1,
    credible_at_95: true,
    interpretation: "Credible: the edge is statistically significant.",
  };

  it("leads with a pass verdict when the deflated Sharpe clears the bar", () => {
    render(<IntegrityVerdict report={credible} />);
    expect(screen.getByText(/statistically credible/i)).toBeInTheDocument();
    expect(screen.getByText(/98%/)).toBeInTheDocument();
  });

  it("fails a seductive raw Sharpe that does not survive deflation", () => {
    render(
      <IntegrityVerdict
        report={{ ...credible, deflated_sharpe_ratio: 0.13, credible_at_95: false,
                  n_trials: 500, interpretation: "Not yet credible." }}
      />,
    );
    expect(screen.getByText(/not statistically credible/i)).toBeInTheDocument();
    // the raw Sharpe is still shown, but the verdict contradicts it
    expect(screen.getByText("1.95")).toBeInTheDocument();
    expect(screen.getByText(/13%/)).toBeInTheDocument();
    expect(screen.getByText(/500 trial/i)).toBeInTheDocument();
  });

  it("degrades to an explicit unknown rather than implying credibility", () => {
    render(<IntegrityVerdict report={{ note: "insufficient observations" }} />);
    expect(screen.getByText(/credibility unavailable/i)).toBeInTheDocument();
  });

  it("renders nothing misleading when the report is absent", () => {
    render(<IntegrityVerdict report={null} />);
    expect(screen.getByText(/credibility unavailable/i)).toBeInTheDocument();
  });

  it("shows an infinite track-record requirement as ∞", () => {
    render(<IntegrityVerdict report={{ ...credible, min_track_record_length_periods: null }} />);
    expect(screen.getByText("∞")).toBeInTheDocument();
  });

  it("surfaces the point-in-time banner only when the clock was engaged", () => {
    const { rerender } = render(<IntegrityVerdict report={credible} />);
    expect(screen.queryByText(/point-in-time/i)).not.toBeInTheDocument();
    rerender(
      <IntegrityVerdict report={credible} pointInTime={{ engaged: true, as_of: "2021-06-30", rows_withheld: 42 }} />,
    );
    expect(screen.getByText(/as of 2021-06-30/i)).toBeInTheDocument();
    expect(screen.getByText(/42 future row/i)).toBeInTheDocument();
  });
});

describe("SelectionVerdict", () => {
  it("flags a best-of-N winner that is only selection noise", () => {
    render(
      <SelectionVerdict
        selection={{ n_trials: 461, best_score: 0.3, expected_best_under_null: 0.5,
                     survives_selection: false, interpretation: "Does not clear the bar." }}
      />,
    );
    expect(screen.getByText(/likely selection noise/i)).toBeInTheDocument();
  });

  it("passes a genuine winner", () => {
    render(
      <SelectionVerdict
        selection={{ n_trials: 461, best_score: 0.9, expected_best_under_null: 0.4,
                     survives_selection: true, interpretation: "Clears the bar." }}
      />,
    );
    expect(screen.getByText(/clears selection bias/i)).toBeInTheDocument();
  });

  it("renders nothing when the correction could not be computed", () => {
    const { container } = render(<SelectionVerdict selection={{ note: "need >=2 trials" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("GovernanceRisk", () => {
  const escalating = {
    status: "ok",
    latest_period: "2023-09-30",
    pledge_severity: "high",
    pledge_pct_of_promoter: 41,
    pledge_pct_of_total_equity: 22.14,
    pledge_qoq_change: 22,
    promoter_stake_qoq_change: -5.5,
    fii_trend_window: -8,
    periods_analyzed: 3,
    flags: ["pledge_high", "pledge_rising", "promoter_stake_falling", "escalating_governance_risk"],
    assessment: "Promoters are pledging more while selling down.",
  };

  it("escalates the pre-blowup pattern to its own alert", () => {
    render(<GovernanceRisk risk={escalating} />);
    expect(screen.getByText(/escalating governance risk/i)).toBeInTheDocument();
    expect(screen.getByText("41.0%")).toBeInTheDocument();
    expect(screen.getByText(/22.1% of equity/)).toBeInTheDocument();
  });

  it("reports a clean book positively", () => {
    render(
      <GovernanceRisk
        risk={{ status: "ok", pledge_severity: "none", pledge_pct_of_promoter: 0,
                flags: [], assessment: "No promoter pledging reported.", periods_analyzed: 4 }}
      />,
    );
    expect(screen.getByText(/no pledging reported/i)).toBeInTheDocument();
  });

  it("renders nothing when data is unavailable rather than implying safety", () => {
    const { container } = render(<GovernanceRisk risk={{ status: "unavailable" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("GroundingSummary", () => {
  it("names every un-sourced figure rather than showing a bare tick", async () => {
    const { GroundingSummary } = await import("../GroundedText");
    render(
      <GroundingSummary
        report={{ n_claims: 3, n_grounded: 2, n_ungrounded: 1, grounding_ratio: 0.667, ungrounded: ["91%"] }}
      />,
    );
    expect(screen.getByText(/1 figure not traceable/i)).toBeInTheDocument();
    expect(screen.getByText("91%")).toBeInTheDocument();
    expect(screen.getByText("2/3 traced")).toBeInTheDocument();
  });

  it("confirms a fully-sourced report", async () => {
    const { GroundingSummary } = await import("../GroundedText");
    render(<GroundingSummary report={{ n_claims: 5, n_grounded: 5, n_ungrounded: 0, grounding_ratio: 1, ungrounded: [] }} />);
    expect(screen.getByText(/every figure traces to a source/i)).toBeInTheDocument();
  });

  it("renders nothing when there are no numeric claims to audit", async () => {
    const { GroundingSummary } = await import("../GroundedText");
    const { container } = render(<GroundingSummary report={{ n_claims: 0 }} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("GovernanceRisk schema drift", () => {
  it("says pledge is unknown rather than hiding the panel", () => {
    render(<GovernanceRisk risk={{ status: "schema_drift" }} />);
    expect(screen.getByText(/pledge status unknown/i)).toBeInTheDocument();
    // must never be read as evidence of a clean book
    expect(screen.getByText(/not.*evidence of zero pledging/i)).toBeInTheDocument();
  });

  it("still hides when there is simply no data", () => {
    const { container } = render(<GovernanceRisk risk={{ status: "unavailable" }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
