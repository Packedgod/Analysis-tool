import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Database,
  Expand,
  LineChart as LineChartIcon,
  Loader2,
  Maximize2,
  RefreshCw,
  Sparkles,
  Table2,
  X,
} from "lucide-react";
import { api, type InsightChart, type RunInsights } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { echarts, CHART_GROUP, connectCharts } from "@/lib/echarts";
import { useDarkMode } from "@/hooks/useDarkMode";
import { cn } from "@/lib/utils";

type View = "overview" | "charts" | "data";
type ChartMode = "bar" | "line";

const SERIES_COLORS = ["#b6ff3b", "#52d681", "#62b6ff", "#f7c948", "#ff718c"];

interface Props {
  runId: string;
  compact?: boolean;
  poll?: boolean;
  className?: string;
}

export function VisualInsightsPanel({ runId, compact = false, poll = false, className }: Props) {
  const [insights, setInsights] = useState<RunInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [view, setView] = useState<View>("overview");
  const [expanded, setExpanded] = useState<InsightChart | null>(null);

  const load = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true); else setLoading(true);
    try {
      setInsights(await api.getRunInsights(runId));
    } catch {
      if (!quiet) setInsights(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [runId]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!poll) return;
    const timer = window.setInterval(() => void load(true), 8_000);
    return () => window.clearInterval(timer);
  }, [load, poll]);
  useEffect(() => {
    if (!expanded) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [expanded]);

  if (loading) {
    return (
      <div className={cn("rounded-xl border bg-card/70 p-5", className)}>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          Building interactive visuals from report data…
        </div>
        <div className="mt-4 h-36 animate-pulse rounded-lg bg-muted/60" />
      </div>
    );
  }

  if (!insights || (insights.charts.length === 0 && insights.kpis.length === 0)) return null;

  if (compact) {
    const firstChart = insights.charts[0];
    return (
      <section className={cn("overflow-hidden rounded-xl border bg-card shadow-sm", className)}>
        <div className="flex items-center justify-between border-b bg-gradient-to-r from-primary/10 via-primary/5 to-transparent px-4 py-2.5">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary">
            <Sparkles className="h-3.5 w-3.5" /> Live visual brief
          </div>
          <Link to={`/runs/${runId}`} className="inline-flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-primary">
            Explore <ArrowUpRight className="h-3 w-3" />
          </Link>
        </div>
        {firstChart ? <InsightChartView chart={firstChart} height={190} minimal /> : <KpiStrip insights={insights} compact />}
      </section>
    );
  }

  const visibleCharts = view === "overview" ? insights.charts.slice(0, 4) : insights.charts;
  return (
    <section className={cn("min-h-full bg-[radial-gradient(circle_at_top_right,hsl(var(--primary)/0.08),transparent_34%)] p-4 lg:p-6", className)}>
      <div className="mx-auto max-w-[1500px] space-y-5">
        <header className="overflow-hidden rounded-2xl border bg-card/85 shadow-sm backdrop-blur">
          <div className="flex flex-col gap-5 bg-gradient-to-br from-primary/12 via-card to-card p-5 lg:flex-row lg:items-center lg:justify-between lg:p-6">
            <div>
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-primary">
                <Activity className="h-4 w-4" /> Live visual intelligence
              </div>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight">Interactive analysis cockpit</h2>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                Financial metrics, scoring tables, and time series are converted directly from the run artifacts. Hover, zoom, filter, export, and inspect the source data.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="rounded-full border bg-background/70 px-3 py-1.5 text-xs text-muted-foreground">
                <span className="mr-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
                {insights.charts.length} charts · {insights.sources.length} sources
              </div>
              <button onClick={() => void load(true)} disabled={refreshing} className="inline-flex items-center gap-2 rounded-full border bg-background/70 px-3 py-1.5 text-xs font-medium transition hover:bg-muted disabled:opacity-50">
                <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} /> Refresh
              </button>
            </div>
          </div>
          <div className="flex items-center gap-1 border-t px-3 py-2">
            {([
              ["overview", Sparkles, "Overview"],
              ["charts", BarChart3, "All charts"],
              ["data", Table2, "Source data"],
            ] as const).map(([id, Icon, label]) => (
              <button key={id} onClick={() => setView(id)} className={cn("inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition", view === id ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-muted hover:text-foreground")}>
                <Icon className="h-3.5 w-3.5" /> {label}
              </button>
            ))}
          </div>
        </header>

        {view !== "data" && <KpiStrip insights={insights} />}

        {view !== "data" && (
          <div className="grid gap-4 xl:grid-cols-2">
            {visibleCharts.map((chart, index) => (
              <article key={chart.id} className={cn("group overflow-hidden rounded-2xl border bg-card/90 shadow-sm transition hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-lg", index === 0 && view === "overview" && "xl:col-span-2")}>
                <div className="flex items-center justify-between border-b px-4 py-3">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold">{chart.title}</h3>
                    <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{chart.source} · {chart.categories.length} observations</p>
                  </div>
                  <button onClick={() => setExpanded(chart)} className="rounded-lg p-2 text-muted-foreground opacity-60 transition hover:bg-muted hover:text-foreground group-hover:opacity-100" title="Expand chart">
                    <Maximize2 className="h-4 w-4" />
                  </button>
                </div>
                <InsightChartView chart={chart} height={index === 0 && view === "overview" ? 400 : 320} />
              </article>
            ))}
          </div>
        )}

        {view === "data" && <InsightTables insights={insights} />}

        {view === "overview" && insights.charts.length > 4 && (
          <button onClick={() => setView("charts")} className="mx-auto flex items-center gap-2 rounded-full border bg-card px-5 py-2 text-sm font-medium shadow-sm transition hover:border-primary/40 hover:text-primary">
            <Expand className="h-4 w-4" /> Explore all {insights.charts.length} charts
          </button>
        )}
      </div>

      {expanded && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/85 p-4 backdrop-blur-md" role="dialog" aria-modal="true">
          <div className="w-full max-w-7xl overflow-hidden rounded-2xl border bg-card shadow-2xl">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <div><h3 className="text-lg font-semibold">{expanded.title}</h3><p className="text-xs text-muted-foreground">{expanded.source}</p></div>
              <button aria-label="Close expanded chart" onClick={() => setExpanded(null)} className="rounded-lg p-2 hover:bg-muted"><X className="h-5 w-5" /></button>
            </div>
            <InsightChartView chart={expanded} height={650} />
          </div>
        </div>
      )}
    </section>
  );
}

function KpiStrip({ insights, compact = false }: { insights: RunInsights; compact?: boolean }) {
  const items = insights.kpis.slice(0, compact ? 4 : 8);
  if (items.length === 0) return null;
  return (
    <div className={cn("grid gap-3", compact ? "grid-cols-2 p-3 sm:grid-cols-4" : "grid-cols-2 md:grid-cols-4 xl:grid-cols-8")}>
      {items.map((item, index) => (
        <div key={`${item.source}-${item.label}-${index}`} className="relative overflow-hidden rounded-xl border bg-card/90 p-3 shadow-sm">
          <div className="absolute -right-5 -top-5 h-14 w-14 rounded-full bg-primary/10" />
          <div className="truncate text-[10px] font-medium uppercase tracking-wide text-muted-foreground" title={item.label}>{item.label}</div>
          <div className="mt-1 truncate text-lg font-semibold tabular-nums" title={item.display}>{formatKpi(item.value, item.unit)}</div>
          <div className="mt-1 truncate text-[9px] text-muted-foreground/70">{item.source}</div>
        </div>
      ))}
    </div>
  );
}

function formatKpi(value: number, unit: string) {
  const abs = Math.abs(value);
  const formatted = abs >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 1 }) : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (unit.startsWith("₹") || unit.startsWith("$") || unit.startsWith("€") || unit.startsWith("£")) {
    const [currency, scale] = unit.split(" ");
    return `${currency}${formatted}${scale ? ` ${scale}` : ""}`;
  }
  return unit === "value" ? formatted : `${formatted}${unit === "%" || unit === "×" ? unit : ` ${unit}`}`;
}

function InsightChartView({ chart, height, minimal = false }: { chart: InsightChart; height: number; minimal?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<ChartMode>(chart.type);
  const { dark } = useDarkMode();
  const hasLongCategories = chart.categories.some((value) => value.length > 18);

  useEffect(() => {
    if (!ref.current) return;
    const theme = getChartTheme();
    const instance = echarts.init(ref.current);
    instance.group = CHART_GROUP;
    connectCharts();
    const horizontal = mode === "bar" && hasLongCategories;
    instance.setOption({
      animationDuration: 650,
      animationEasing: "cubicOut",
      color: SERIES_COLORS,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: mode === "bar" ? "shadow" : "cross" },
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        valueFormatter: (value: unknown) => typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value ?? "—"),
      },
      legend: { show: chart.series.length > 1, top: 8, left: 14, textStyle: { color: theme.textColor, fontSize: 10 } },
      toolbox: minimal ? undefined : {
        right: 12,
        top: 4,
        feature: { saveAsImage: { title: "Export PNG", pixelRatio: 2 }, restore: { title: "Reset" } },
        iconStyle: { borderColor: theme.textColor },
      },
      grid: { left: horizontal ? 150 : 56, right: 28, top: chart.series.length > 1 ? 48 : 32, bottom: chart.categories.length > 10 ? 64 : 42 },
      xAxis: horizontal
        ? { type: "value", splitLine: { lineStyle: { color: theme.gridColor } }, axisLabel: { color: theme.textColor, fontSize: 10 } }
        : { type: "category", data: chart.categories, axisLine: { lineStyle: { color: theme.axisColor } }, axisLabel: { color: theme.textColor, fontSize: 10, rotate: chart.categories.length > 7 ? 28 : 0, hideOverlap: true } },
      yAxis: horizontal
        ? { type: "category", data: chart.categories, axisLine: { lineStyle: { color: theme.axisColor } }, axisLabel: { color: theme.textColor, fontSize: 10, width: 136, overflow: "truncate" } }
        : { type: "value", splitLine: { lineStyle: { color: theme.gridColor } }, axisLabel: { color: theme.textColor, fontSize: 10 } },
      dataZoom: chart.categories.length > 14 ? [{ type: "inside", start: 0, end: Math.max(30, 1400 / chart.categories.length) }, { type: "slider", height: 16, bottom: 5 }] : [],
      series: chart.series.map((series, index) => ({
        name: series.name,
        type: mode,
        data: series.values,
        smooth: mode === "line" ? 0.28 : false,
        symbol: mode === "line" ? "circle" : undefined,
        symbolSize: mode === "line" ? 5 : undefined,
        showSymbol: mode === "line" && chart.categories.length < 30,
        lineStyle: mode === "line" ? { width: 2.5, shadowBlur: 10, shadowColor: `${SERIES_COLORS[index % SERIES_COLORS.length]}44` } : undefined,
        areaStyle: mode === "line" ? { opacity: 0.12 } : undefined,
        itemStyle: mode === "bar" ? { borderRadius: horizontal ? [0, 5, 5, 0] : [5, 5, 0, 0] } : undefined,
        emphasis: { focus: "series" },
      })),
    });
    const ro = new ResizeObserver(() => instance.resize());
    ro.observe(ref.current);
    return () => { ro.disconnect(); instance.dispose(); };
  }, [chart, mode, dark, hasLongCategories, minimal]);

  return (
    <div className="relative p-2">
      {!minimal && (
        <div className="absolute right-20 top-2 z-10 flex rounded-lg border bg-background/80 p-0.5 backdrop-blur">
          <button onClick={() => setMode("bar")} className={cn("rounded-md p-1.5", mode === "bar" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")} title="Bar view"><BarChart3 className="h-3.5 w-3.5" /></button>
          <button onClick={() => setMode("line")} className={cn("rounded-md p-1.5", mode === "line" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")} title="Line view"><LineChartIcon className="h-3.5 w-3.5" /></button>
        </div>
      )}
      <div ref={ref} style={{ height }} />
    </div>
  );
}

function InsightTables({ insights }: { insights: RunInsights }) {
  if (insights.tables.length === 0) {
    return <div className="rounded-2xl border border-dashed bg-card p-10 text-center text-sm text-muted-foreground"><Database className="mx-auto mb-3 h-8 w-8" />No structured tables were found in this report.</div>;
  }
  return (
    <div className="space-y-4">
      {insights.tables.map((table, index) => (
        <article key={`${table.source}-${table.title}-${index}`} className="overflow-hidden rounded-2xl border bg-card shadow-sm">
          <div className="flex items-center justify-between border-b px-4 py-3"><div><h3 className="text-sm font-semibold">{table.title}</h3><p className="text-[11px] text-muted-foreground">{table.source}</p></div><Table2 className="h-4 w-4 text-primary" /></div>
          <div className="max-h-[440px] overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 z-10 bg-muted/95 backdrop-blur"><tr>{table.columns.map((column) => <th key={column} className="whitespace-nowrap border-b px-3 py-2 text-left font-semibold">{column}</th>)}</tr></thead>
              <tbody>{table.rows.map((row, rowIndex) => <tr key={rowIndex} className="border-b last:border-0 hover:bg-primary/5">{table.columns.map((_, cellIndex) => <td key={cellIndex} className="max-w-xs px-3 py-2 tabular-nums">{row[cellIndex] ?? ""}</td>)}</tr>)}</tbody>
            </table>
          </div>
        </article>
      ))}
    </div>
  );
}
