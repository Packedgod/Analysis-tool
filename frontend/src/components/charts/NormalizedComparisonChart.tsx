import { useEffect, useMemo, useRef } from "react";
import type { PriceBar } from "@/lib/api";
import { getChartTheme } from "@/lib/chart-theme";
import { echarts } from "@/lib/echarts";
import { useDarkMode } from "@/hooks/useDarkMode";

const SERIES_COLORS = ["#a3e635", "#38bdf8", "#a78bfa", "#fb7185", "#f59e0b", "#2dd4bf"];

interface Props {
  series: Array<{ symbol: string; bars: PriceBar[] }>;
  height?: number;
}

function barDate(bar: PriceBar): string {
  return String(bar.time || bar.timestamp || "").slice(0, 10);
}

export function NormalizedComparisonChart({ series, height = 320 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { dark } = useDarkMode();
  const normalized = useMemo(() => {
    const dates = [...new Set(series.flatMap(({ bars }) => bars.map(barDate).filter(Boolean)))].sort();
    return {
      dates,
      series: series.map(({ symbol, bars }) => {
        const firstClose = bars.map((bar) => Number(bar.close)).find((value) => Number.isFinite(value) && value !== 0);
        const closeByDate = new Map(bars.map((bar) => [barDate(bar), Number(bar.close)]));
        return {
          symbol,
          data: dates.map((date) => {
            const close = closeByDate.get(date);
            return firstClose && close != null && Number.isFinite(close) ? Number(((close / firstClose) * 100).toFixed(4)) : null;
          }),
        };
      }),
    };
  }, [series]);

  useEffect(() => {
    if (!ref.current || normalized.series.length < 2) return;
    const theme = getChartTheme();
    const chart = echarts.init(ref.current);
    chart.setOption({
      animationDuration: 420,
      backgroundColor: "transparent",
      color: SERIES_COLORS,
      tooltip: {
        trigger: "axis",
        backgroundColor: theme.tooltipBg,
        borderColor: theme.tooltipBorder,
        textStyle: { color: theme.tooltipText, fontSize: 11 },
        valueFormatter: (value: unknown) => `${Number(value).toFixed(2)}`,
      },
      legend: {
        type: "scroll",
        data: normalized.series.map((item) => item.symbol),
        left: 8,
        top: 4,
        textStyle: { color: theme.textColor, fontSize: 10 },
      },
      grid: { left: 58, right: 24, top: 48, bottom: 46 },
      xAxis: {
        type: "category",
        data: normalized.dates,
        axisLine: { lineStyle: { color: theme.axisColor } },
        axisTick: { show: false },
        axisLabel: { color: theme.textColor, fontSize: 10, hideOverlap: true },
      },
      yAxis: {
        type: "value",
        scale: true,
        name: "Indexed (start = 100)",
        nameTextStyle: { color: theme.textColor, fontSize: 10 },
        axisLabel: { color: theme.textColor, fontSize: 10 },
        splitLine: { lineStyle: { color: theme.gridColor } },
      },
      dataZoom: [{ type: "inside", filterMode: "none" }],
      series: normalized.series.map((item, index) => ({
        type: "line",
        name: item.symbol,
        data: item.data,
        connectNulls: false,
        showSymbol: false,
        sampling: "lttb",
        lineStyle: { color: SERIES_COLORS[index % SERIES_COLORS.length], width: 2 },
        itemStyle: { color: SERIES_COLORS[index % SERIES_COLORS.length] },
      })),
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [normalized, dark]);

  if (series.length < 2) return null;
  return <div ref={ref} style={{ height }} className="w-full" aria-label="Normalized multi-symbol price comparison" />;
}
