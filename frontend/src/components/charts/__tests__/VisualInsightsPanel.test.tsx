import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { VisualInsightsPanel } from "../VisualInsightsPanel";

const { getRunInsights, setOption } = vi.hoisted(() => ({
  getRunInsights: vi.fn(),
  setOption: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, api: { ...actual.api, getRunInsights } };
});

vi.mock("@/lib/echarts", () => ({
  CHART_GROUP: "tests",
  connectCharts: vi.fn(),
  echarts: {
    init: vi.fn(() => ({
      group: "",
      setOption,
      resize: vi.fn(),
      dispose: vi.fn(),
    })),
  },
}));

vi.mock("@/hooks/useDarkMode", () => ({ useDarkMode: () => ({ dark: false }) }));

const fixture = {
  run_id: "run-1",
  generated_at: "2026-07-17T00:00:00Z",
  sources: ["report.md"],
  kpis: [
    { label: "Revenue", value: 8257.04, display: "Rs 8,257.04 cr", unit: "₹ cr", source: "report.md" },
    { label: "ROCE", value: 6.1, display: "6.1%", unit: "%", source: "report.md" },
  ],
  charts: [{
    id: "chart-1",
    title: "Key financial metrics",
    type: "bar" as const,
    categories: ["Revenue", "EBITDA"],
    series: [{ name: "₹ cr", unit: "₹ cr", values: [8257.04, 2108.25] }],
    source: "report.md",
  }],
  tables: [{ title: "Annual", columns: ["Year", "Revenue"], rows: [["2025", "8257"]], source: "report.md" }],
};

describe("VisualInsightsPanel", () => {
  beforeEach(() => {
    getRunInsights.mockResolvedValue(fixture);
    setOption.mockClear();
  });

  it("renders an interactive dashboard from derived insights", async () => {
    render(<MemoryRouter><VisualInsightsPanel runId="run-1" /></MemoryRouter>);

    expect(await screen.findByText("Interactive analysis cockpit")).toBeInTheDocument();
    expect(screen.getByText("Key financial metrics")).toBeInTheDocument();
    expect(screen.getByText("₹8,257 cr")).toBeInTheDocument();
    await waitFor(() => expect(setOption).toHaveBeenCalled());
  });

  it("renders a compact chart preview with a report link", async () => {
    render(<MemoryRouter><VisualInsightsPanel runId="run-1" compact /></MemoryRouter>);

    expect(await screen.findByText("Live visual brief")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /explore/i })).toHaveAttribute("href", "/runs/run-1");
  });

  it("renders nothing when a report contains no numerical insights", async () => {
    getRunInsights.mockResolvedValue({ ...fixture, kpis: [], charts: [], tables: [] });
    const { container } = render(<MemoryRouter><VisualInsightsPanel runId="run-1" /></MemoryRouter>);

    await waitFor(() => expect(getRunInsights).toHaveBeenCalled());
    await waitFor(() => expect(container.innerHTML).toBe(""));
  });
});
