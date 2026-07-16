import { describe, expect, it } from "vitest";

import { buildAnalysisPrompt } from "@/pages/Home";

describe("buildAnalysisPrompt", () => {
  it("requires official reports, reliable evidence, simulation safety, and no broker", () => {
    const prompt = buildAnalysisPrompt({
      company: "Reliance Industries",
      ticker: "RELIANCE.NS",
      factors: "cash flow and competitive position",
      historyYears: 3,
      strategyPath: "uploads/strategy.pdf",
      strategyName: "strategy.pdf",
      useTeam: true,
    });

    expect(prompt).toContain("official website");
    expect(prompt).toContain("Reuters");
    expect(prompt).toContain("RELIANCE.NS");
    expect(prompt).toContain("uploads/strategy.pdf");
    expect(prompt).toContain("never place or prepare an order");
    expect(prompt).toContain("multi-agent investment committee");
  });
});
