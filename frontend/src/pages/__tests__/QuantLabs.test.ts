import { describe, expect, it } from "vitest";
import type { QuantLabResult } from "@/lib/api";
import { buildChartSpec, indexedMarketSeries, marketTickers } from "@/pages/QuantLabs";

const marketResult: QuantLabResult = {
  kind: "market_dashboard",
  evidence: {
    source: "Fixture",
    observed_at: "2026-07-20T00:00:00Z",
    method: "Observed OHLCV",
    data_class: "observed",
    caveats: [],
  },
  series: [
    { ticker: "SPY", date: "2026-01-01", open: 99, high: 102, low: 98, close: 100, ma20: null, ma50: null },
    { ticker: "SPY", date: "2026-01-02", open: 100, high: 112, low: 99, close: 110, ma20: 104, ma50: null },
    { ticker: "QQQ", date: "2026-01-01", open: 198, high: 204, low: 197, close: 200, ma20: null, ma50: null },
    { ticker: "QQQ", date: "2026-01-02", open: 200, high: 212, low: 199, close: 210, ma20: 204, ma50: null },
    { ticker: "AAPL", date: "2026-01-02", open: 49, high: 52, low: 48, close: 50, ma20: null, ma50: null },
  ],
};

describe("Quant Labs multi-symbol market charts", () => {
  it("discovers every returned symbol in provider order", () => {
    expect(marketTickers(marketResult)).toEqual(["SPY", "QQQ", "AAPL"]);
  });

  it("normalizes each symbol to 100 and aligns missing dates honestly", () => {
    const indexed = indexedMarketSeries(marketResult);
    expect(indexed.dates).toEqual(["2026-01-01", "2026-01-02"]);
    expect(indexed.series[0]).toEqual({ ticker: "SPY", data: [100, 110] });
    expect(indexed.series[1]).toEqual({ ticker: "QQQ", data: [100, 105] });
    expect(indexed.series[2]).toEqual({ ticker: "AAPL", data: [null, 100] });
  });

  it("builds the requested ticker as a candlestick view", () => {
    const spec = buildChartSpec(marketResult, { mode: "single", ticker: "QQQ" });
    const series = spec.option.series as Array<{ name?: string; data?: unknown[] }>;
    expect(spec.legends.map((item) => item.name)).toEqual(["QQQ", "MA20", "MA50"]);
    expect(series[0].name).toBe("QQQ");
    expect(series[0].data).toHaveLength(2);
  });

  it("builds a collective indexed comparison for every symbol", () => {
    const spec = buildChartSpec(marketResult, { mode: "compare" });
    const series = spec.option.series as Array<{ name?: string; data?: unknown[] }>;
    expect(spec.legends.map((item) => item.name)).toEqual(["SPY", "QQQ", "AAPL"]);
    expect(series.map((item) => item.name)).toEqual(["SPY", "QQQ", "AAPL"]);
  });
});
