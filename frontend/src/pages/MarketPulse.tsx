import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  AlertCircle, BarChart3, Bookmark, BookmarkCheck, Crosshair,
  ExternalLink, Filter, Loader2, Newspaper, Plus, SlidersHorizontal, Star,
  Table2, Trash2, TrendingDown, TrendingUp, X,
} from "lucide-react";
import { toast } from "sonner";

import {
  api, type CandlesResponse, type NewsResponse, type QuoteResponse,
  type ScreenResponse, type ScreenRow,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { CandlestickChart, type PriceLevel } from "@/components/charts/CandlestickChart";
import { SymbolSearch } from "@/components/market/SymbolSearch";
import { Eyebrow, Reveal, SectionMark } from "@/components/common/Motion";
import {
  matchesStandard, usePositions, useStandards, useWatchlist,
  type PositionKind, type StandardOperator,
} from "@/hooks/useMarketPrefs";
import { FIELD_BY_KEY, FIELD_SPECS, currencySymbol, formatField, rangePosition } from "@/lib/marketFields";
import { useCountUp } from "@/hooks/useMotion";

const RANGES = ["1D", "5D", "1M", "3M", "6M", "1Y", "5Y", "MAX"] as const;
const TABS = [
  { id: "chart", label: "Chart", icon: BarChart3 },
  { id: "news", label: "News", icon: Newspaper },
  { id: "fundamentals", label: "Fundamentals", icon: Table2 },
] as const;
type TabId = (typeof TABS)[number]["id"];

const OPERATOR_LABEL: Record<StandardOperator, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤" };
const POSITION_COLOR: Record<PositionKind, string> = {
  entry: "#3b82f6",
  target: "#22c55e",
  stop: "#ef4444",
};

function pctTone(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "text-muted-foreground";
  return value >= 0 ? "text-success" : "text-danger";
}

/** Headline price with the same eased-counter treatment as the home tape. */
function BigPrice({ value, currency }: { value: number | null; currency: string | null }) {
  const animated = useCountUp(value ?? 0);
  if (value == null) return <span className="display-2 text-muted-foreground">—</span>;
  return (
    <span className="display-2 figure font-light">
      {currencySymbol(currency)}
      {animated.toLocaleString(undefined, {
        minimumFractionDigits: value >= 1000 ? 0 : 2,
        maximumFractionDigits: value >= 1000 ? 0 : 2,
      })}
    </span>
  );
}

export function MarketPulse() {
  const [searchParams, setSearchParams] = useSearchParams();
  const symbol = (searchParams.get("symbol") || "RELIANCE.NS").toUpperCase();

  const [tab, setTab] = useState<TabId>("chart");
  const [range, setRange] = useState<string>("6M");

  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(true);

  const [candles, setCandles] = useState<CandlesResponse | null>(null);
  const [candlesError, setCandlesError] = useState<string | null>(null);
  const [candlesLoading, setCandlesLoading] = useState(true);

  const [news, setNews] = useState<NewsResponse | null>(null);
  const [newsError, setNewsError] = useState<string | null>(null);

  const [screen, setScreen] = useState<ScreenResponse | null>(null);
  const [screenLoading, setScreenLoading] = useState(true);

  const watchlist = useWatchlist();
  const { standards, add: addStandard, remove: removeStandard, toggle: toggleStandard } = useStandards();
  const { positions, add: addPosition, remove: removePosition } = usePositions(symbol);

  const selectSymbol = useCallback((next: string) => {
    setSearchParams({ symbol: next.toUpperCase() }, { replace: false });
  }, [setSearchParams]);

  // --- Data loading. Each stream fails independently so one dead provider
  // --- call never blanks the whole workspace.
  useEffect(() => {
    const controller = new AbortController();
    setQuoteLoading(true);
    setQuoteError(null);
    api.getQuote(symbol, controller.signal)
      .then(setQuote)
      .catch((error) => {
        if (controller.signal.aborted) return;
        setQuote(null);
        setQuoteError(error instanceof Error ? error.message : "Quote unavailable.");
      })
      .finally(() => { if (!controller.signal.aborted) setQuoteLoading(false); });
    return () => controller.abort();
  }, [symbol]);

  useEffect(() => {
    const controller = new AbortController();
    setCandlesLoading(true);
    setCandlesError(null);
    api.getCandles(symbol, range, controller.signal)
      .then(setCandles)
      .catch((error) => {
        if (controller.signal.aborted) return;
        setCandles(null);
        setCandlesError(error instanceof Error ? error.message : "Price history unavailable.");
      })
      .finally(() => { if (!controller.signal.aborted) setCandlesLoading(false); });
    return () => controller.abort();
  }, [symbol, range]);

  useEffect(() => {
    const controller = new AbortController();
    setNewsError(null);
    api.getNews(symbol, controller.signal)
      .then(setNews)
      .catch((error) => {
        if (controller.signal.aborted) return;
        setNews(null);
        setNewsError(error instanceof Error ? error.message : "News unavailable.");
      });
    return () => controller.abort();
  }, [symbol]);

  // The screener grid covers the watchlist plus whatever is selected, so the
  // selected name is always comparable even before it is saved.
  const screenUniverse = useMemo(() => {
    const set = [...watchlist.symbols];
    if (!set.includes(symbol)) set.push(symbol);
    return set;
  }, [watchlist.symbols, symbol]);

  useEffect(() => {
    if (!screenUniverse.length) { setScreen(null); setScreenLoading(false); return; }
    const controller = new AbortController();
    setScreenLoading(true);
    api.screenSymbols(screenUniverse, controller.signal)
      .then(setScreen)
      .catch(() => { if (!controller.signal.aborted) setScreen(null); })
      .finally(() => { if (!controller.signal.aborted) setScreenLoading(false); });
    return () => controller.abort();
  }, [screenUniverse]);

  const activeStandards = useMemo(() => standards.filter((s) => s.enabled), [standards]);

  const rows = screen?.rows ?? [];
  const passingSymbols = useMemo(() => {
    if (!activeStandards.length) return new Set(rows.map((r) => r.symbol));
    return new Set(
      rows.filter((row) =>
        activeStandards.every((standard) =>
          matchesStandard(row[standard.field as keyof ScreenRow] as number | null, standard))
      ).map((row) => row.symbol),
    );
  }, [rows, activeStandards]);

  // Marked positions become horizontal lines on the price pane.
  const chartLevels: PriceLevel[] = useMemo(
    () => positions.map((position) => ({
      price: position.price,
      label: position.note?.trim() || position.kind.toUpperCase(),
      color: POSITION_COLOR[position.kind],
      solid: position.kind === "entry",
    })),
    [positions],
  );

  const selectedRow = rows.find((row) => row.symbol === symbol);
  const fundamentals = quote?.fundamentals ?? {};
  const inWatchlist = watchlist.has(symbol);

  return (
    <div className="terminal-shell min-h-full">
      <main className="mx-auto max-w-[1540px] space-y-5 px-4 py-5 sm:px-5 lg:px-7 lg:py-7">
        {/* Header + search */}
        <Reveal variant="fade">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <Eyebrow className="eyebrow-primary">Market pulse</Eyebrow>
              <h1 className="display-2 mt-2">Research the tape.</h1>
              <p className="mt-3 max-w-2xl text-sm text-muted-foreground">
                Search any listed security, read its chart and headlines, set your own screening
                standards, mark the levels you care about, and keep a watchlist.
              </p>
            </div>
            <div className="w-full lg:w-[420px]">
              <SymbolSearch onSelect={selectSymbol} />
            </div>
          </div>
        </Reveal>

        {/* Quote header */}
        <section className="terminal-card spotlight overflow-hidden rounded-[22px] border bg-card/90">
          <div className="flex flex-wrap items-start justify-between gap-5 p-5 sm:p-6">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="figure rounded-md border bg-background/60 px-2 py-1 text-[11px] font-semibold text-primary">
                  {symbol}
                </span>
                {quote?.exchange && <span className="eyebrow text-[9px]">{quote.exchange}</span>}
                {quote?.quote_type && <span className="eyebrow text-[9px]">{quote.quote_type}</span>}
              </div>
              <h2 className="mt-2 truncate text-xl font-normal tracking-tight">
                {quoteLoading ? "Loading…" : quote?.name || symbol}
              </h2>

              <div className="mt-4 flex flex-wrap items-baseline gap-4">
                <BigPrice value={quote?.price ?? null} currency={quote?.currency ?? null} />
                {quote?.change_percent != null && (
                  <span className={cn("figure flex items-center gap-1.5 text-sm font-semibold", pctTone(quote.change_percent))}>
                    {quote.change_percent >= 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                    {quote.change_percent >= 0 ? "+" : ""}{quote.change_percent.toFixed(2)}%
                  </span>
                )}
              </div>

              {quoteError && (
                <p className="mt-3 flex items-center gap-2 text-xs text-danger">
                  <AlertCircle className="h-3.5 w-3.5" /> {quoteError}
                </p>
              )}
              {quote && (
                <p className="eyebrow mt-3 text-[9px]">
                  {quote.source} · observed {new Date(quote.observed_at).toLocaleTimeString()}
                </p>
              )}
            </div>

            <div className="flex flex-col items-end gap-3">
              <button
                type="button"
                onClick={() => {
                  watchlist.toggle(symbol);
                  toast.success(inWatchlist ? `${symbol} removed from watchlist` : `${symbol} added to watchlist`);
                }}
                className={cn(
                  "inline-flex items-center gap-2 rounded-lg border px-3.5 py-2.5 text-xs font-medium transition",
                  inWatchlist
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "hover:border-primary/40 hover:bg-primary/5",
                )}
              >
                {inWatchlist ? <BookmarkCheck className="h-4 w-4" /> : <Bookmark className="h-4 w-4" />}
                {inWatchlist ? "In watchlist" : "Add to watchlist"}
              </button>

              {selectedRow && <RangeMeter row={selectedRow} />}
            </div>
          </div>

          {/* Key stats strip */}
          <div className="grid grid-cols-2 gap-px border-t bg-border/60 sm:grid-cols-3 lg:grid-cols-6">
            {(["market_cap", "trailing_pe", "price_to_book", "dividend_yield", "return_on_equity", "beta"] as const).map((key) => {
              const spec = FIELD_BY_KEY.get(key)!;
              const value = selectedRow ? (selectedRow[key] as number | null) : null;
              return (
                <div key={key} className="bg-card px-4 py-3">
                  <p className="eyebrow text-[9px]">{spec.label}</p>
                  <p className="figure mt-1.5 text-sm">{formatField(value, spec.format, quote?.currency)}</p>
                </div>
              );
            })}
          </div>
        </section>

        {/* Tabs */}
        <div className="flex flex-wrap items-center gap-1 border-b">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={cn(
                "-mb-px flex items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-medium transition-colors",
                tab === id
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="h-3.5 w-3.5" /> {label}
            </button>
          ))}
        </div>

        {tab === "chart" && (
          <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
            <article className="terminal-card overflow-hidden rounded-[20px] border bg-card/90">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3.5">
                <Eyebrow>Price &amp; patterns</Eyebrow>
                <div className="flex flex-wrap gap-1">
                  {RANGES.map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setRange(option)}
                      className={cn(
                        "figure rounded-md px-2.5 py-1.5 text-[10px] font-semibold transition",
                        range === option
                          ? "bg-primary/15 text-primary"
                          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                      )}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>
              <div className="p-3">
                {candlesLoading ? (
                  <div className="flex h-[460px] items-center justify-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" /> Loading price history…
                  </div>
                ) : candlesError ? (
                  <div className="flex h-[460px] flex-col items-center justify-center gap-2 text-sm text-danger">
                    <AlertCircle className="h-5 w-5" /> {candlesError}
                  </div>
                ) : candles && candles.bars.length ? (
                  <CandlestickChart data={candles.bars} levels={chartLevels} height={460} />
                ) : (
                  <div className="flex h-[460px] items-center justify-center text-sm text-muted-foreground">
                    No price history is published for this security.
                  </div>
                )}
              </div>
              {candles?.bars.length ? (
                <p className="eyebrow border-t px-5 py-2.5 text-[9px]">
                  {candles.source} · {candles.bars.length} bars · {candles.interval} interval
                </p>
              ) : null}
            </article>

            <PositionsPanel
              symbol={symbol}
              lastPrice={quote?.price ?? null}
              currency={quote?.currency ?? null}
              positions={positions}
              onAdd={addPosition}
              onRemove={removePosition}
            />
          </section>
        )}

        {tab === "news" && (
          <NewsPanel news={news} error={newsError} symbol={symbol} />
        )}

        {tab === "fundamentals" && (
          <FundamentalsPanel fundamentals={fundamentals} currency={quote?.currency ?? null} loading={quoteLoading} />
        )}

        {/* Screener */}
        <Reveal variant="fade">
          <SectionMark index={1} title="Screener &amp; watchlist" hint={`${rows.length} securities`} className="pt-4" />
        </Reveal>

        <section className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
          <StandardsPanel
            standards={standards}
            onAdd={addStandard}
            onRemove={removeStandard}
            onToggle={toggleStandard}
            passing={passingSymbols.size}
            total={rows.length}
          />

          <ScreenerTable
            rows={rows}
            loading={screenLoading}
            unavailable={screen?.unavailable ?? []}
            passing={passingSymbols}
            activeStandardCount={activeStandards.length}
            selected={symbol}
            watchlist={watchlist}
            onSelect={selectSymbol}
          />
        </section>
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 52-week range meter
// ---------------------------------------------------------------------------

function RangeMeter({ row }: { row: ScreenRow }) {
  const position = rangePosition(row);
  if (position === null) return null;
  return (
    <div className="w-56">
      <div className="flex items-center justify-between">
        <span className="eyebrow text-[9px]">52W range</span>
        <span className="figure text-[10px] text-muted-foreground">{(position * 100).toFixed(0)}%</span>
      </div>
      <div className="mt-2 h-1.5 rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${position * 100}%` }} />
      </div>
      <div className="mt-1.5 flex justify-between">
        <span className="figure text-[9px] text-muted-foreground">{formatField(row.fifty_two_week_low, "price", row.currency)}</span>
        <span className="figure text-[9px] text-muted-foreground">{formatField(row.fifty_two_week_high, "price", row.currency)}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Marked positions
// ---------------------------------------------------------------------------

interface PositionsPanelProps {
  symbol: string;
  lastPrice: number | null;
  currency: string | null;
  positions: ReturnType<typeof usePositions>["positions"];
  onAdd: ReturnType<typeof usePositions>["add"];
  onRemove: ReturnType<typeof usePositions>["remove"];
}

function PositionsPanel({ symbol, lastPrice, currency, positions, onAdd, onRemove }: PositionsPanelProps) {
  const [kind, setKind] = useState<PositionKind>("entry");
  const [price, setPrice] = useState("");
  const [note, setNote] = useState("");

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = Number(price);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      toast.error("Enter a price above zero.");
      return;
    }
    onAdd({ symbol, kind, price: parsed, note: note.trim() || undefined });
    setPrice("");
    setNote("");
    toast.success(`${kind} marked at ${currencySymbol(currency)}${parsed}`);
  };

  return (
    <aside className="terminal-card rounded-[20px] border bg-card/90 p-5">
      <div className="flex items-center gap-2">
        <Crosshair className="h-4 w-4 text-primary" />
        <Eyebrow>Mark positions</Eyebrow>
      </div>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        Levels you mark are drawn straight onto the chart above.
      </p>

      <form onSubmit={submit} className="mt-4 space-y-3">
        <div className="grid grid-cols-3 gap-1.5">
          {(["entry", "target", "stop"] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setKind(option)}
              className={cn(
                "rounded-lg border px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] transition",
                kind === option ? "border-primary/45 bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted/50",
              )}
            >
              {option}
            </button>
          ))}
        </div>
        <input
          value={price}
          onChange={(event) => setPrice(event.target.value)}
          inputMode="decimal"
          placeholder={lastPrice ? `Price (last ${lastPrice})` : "Price"}
          className="stock-input figure"
          aria-label="Position price"
        />
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Label (optional)"
          maxLength={24}
          className="stock-input"
          aria-label="Position label"
        />
        <button type="submit" className="primary-action w-full py-2.5 text-xs">
          <Plus className="h-3.5 w-3.5" /> Mark level
        </button>
      </form>

      <div className="mt-5 space-y-1.5">
        {positions.length === 0 ? (
          <p className="text-xs text-muted-foreground/70">No levels marked for {symbol}.</p>
        ) : positions.map((position) => (
          <div key={position.id} className="group flex items-center gap-2.5 rounded-lg border bg-background/40 px-3 py-2">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: POSITION_COLOR[position.kind] }} />
            <span className="eyebrow w-12 shrink-0 text-[9px]">{position.kind}</span>
            <span className="figure flex-1 text-xs">{currencySymbol(currency)}{position.price}</span>
            {position.note && <span className="truncate text-[10px] text-muted-foreground">{position.note}</span>}
            <button
              type="button"
              onClick={() => onRemove(position.id)}
              className="rounded p-1 text-muted-foreground opacity-0 transition group-hover:opacity-100 hover:text-danger"
              aria-label={`Remove ${position.kind} at ${position.price}`}
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Standards
// ---------------------------------------------------------------------------

interface StandardsPanelProps {
  standards: ReturnType<typeof useStandards>["standards"];
  onAdd: ReturnType<typeof useStandards>["add"];
  onRemove: ReturnType<typeof useStandards>["remove"];
  onToggle: ReturnType<typeof useStandards>["toggle"];
  passing: number;
  total: number;
}

function StandardsPanel({ standards, onAdd, onRemove, onToggle, passing, total }: StandardsPanelProps) {
  const [field, setField] = useState<string>("trailing_pe");
  const [operator, setOperator] = useState<StandardOperator>("lt");
  const [value, setValue] = useState("");

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) {
      toast.error("Enter a numeric threshold.");
      return;
    }
    onAdd({ field, operator, value: parsed, enabled: true });
    setValue("");
  };

  return (
    <aside className="terminal-card rounded-[20px] border bg-card/90 p-5">
      <div className="flex items-center gap-2">
        <SlidersHorizontal className="h-4 w-4 text-primary" />
        <Eyebrow>Screening standards</Eyebrow>
      </div>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        {standards.length === 0
          ? "Add criteria to filter the grid."
          : `${passing} of ${total} meet every active standard.`}
      </p>

      <form onSubmit={submit} className="mt-4 space-y-2.5">
        <select value={field} onChange={(event) => setField(event.target.value)} className="stock-input" aria-label="Metric">
          {FIELD_SPECS.map((spec) => (
            <option key={String(spec.key)} value={String(spec.key)}>{spec.label}</option>
          ))}
        </select>
        <div className="grid grid-cols-[84px_minmax(0,1fr)] gap-2">
          <select
            value={operator}
            onChange={(event) => setOperator(event.target.value as StandardOperator)}
            className="stock-input figure"
            aria-label="Operator"
          >
            {(Object.keys(OPERATOR_LABEL) as StandardOperator[]).map((op) => (
              <option key={op} value={op}>{OPERATOR_LABEL[op]}</option>
            ))}
          </select>
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            inputMode="decimal"
            placeholder="Threshold"
            className="stock-input figure"
            aria-label="Threshold value"
          />
        </div>
        <button type="submit" className="ghost-action w-full">
          <Filter className="h-3.5 w-3.5" /> Add standard
        </button>
      </form>

      <div className="mt-5 space-y-1.5">
        {standards.map((standard) => {
          const spec = FIELD_BY_KEY.get(standard.field);
          return (
            <div
              key={standard.id}
              className={cn(
                "group flex items-center gap-2 rounded-lg border px-3 py-2 transition",
                standard.enabled ? "bg-background/40" : "opacity-45",
              )}
            >
              <button
                type="button"
                onClick={() => onToggle(standard.id)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                aria-pressed={standard.enabled}
              >
                <Star className={cn("h-3 w-3 shrink-0", standard.enabled ? "fill-primary text-primary" : "text-muted-foreground")} />
                <span className="truncate text-[11px]">{spec?.label ?? standard.field}</span>
                <span className="figure shrink-0 text-[11px] text-primary">
                  {OPERATOR_LABEL[standard.operator]} {standard.value}
                </span>
              </button>
              <button
                type="button"
                onClick={() => onRemove(standard.id)}
                className="rounded p-1 text-muted-foreground opacity-0 transition group-hover:opacity-100 hover:text-danger"
                aria-label="Remove standard"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

// ---------------------------------------------------------------------------
// Screener grid
// ---------------------------------------------------------------------------

interface ScreenerTableProps {
  rows: ScreenRow[];
  loading: boolean;
  unavailable: string[];
  passing: Set<string>;
  activeStandardCount: number;
  selected: string;
  watchlist: ReturnType<typeof useWatchlist>;
  onSelect: (symbol: string) => void;
}

const COLUMNS = ["price", "change_percent", "market_cap", "trailing_pe", "price_to_book", "dividend_yield", "return_on_equity", "debt_to_equity"] as const;

function ScreenerTable({ rows, loading, unavailable, passing, activeStandardCount, selected, watchlist, onSelect }: ScreenerTableProps) {
  const [sortKey, setSortKey] = useState<string>("change_percent");
  const [ascending, setAscending] = useState(false);
  const [onlyPassing, setOnlyPassing] = useState(false);

  const visible = useMemo(() => {
    const filtered = onlyPassing && activeStandardCount > 0 ? rows.filter((row) => passing.has(row.symbol)) : rows;
    return [...filtered].sort((a, b) => {
      const left = a[sortKey as keyof ScreenRow];
      const right = b[sortKey as keyof ScreenRow];
      const leftNum = typeof left === "number" && Number.isFinite(left) ? left : null;
      const rightNum = typeof right === "number" && Number.isFinite(right) ? right : null;
      // Absent values sort last in both directions — a missing metric is not
      // a small one, and letting it float to the top would mislead.
      if (leftNum === null && rightNum === null) return 0;
      if (leftNum === null) return 1;
      if (rightNum === null) return -1;
      return ascending ? leftNum - rightNum : rightNum - leftNum;
    });
  }, [rows, sortKey, ascending, onlyPassing, passing, activeStandardCount]);

  const sortBy = (key: string) => {
    if (key === sortKey) setAscending((value) => !value);
    else { setSortKey(key); setAscending(false); }
  };

  return (
    <article className="terminal-card overflow-hidden rounded-[20px] border bg-card/90">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3.5">
        <Eyebrow>Comparison grid</Eyebrow>
        <div className="flex items-center gap-3">
          {activeStandardCount > 0 && (
            <label className="flex cursor-pointer items-center gap-2 text-[11px] text-muted-foreground">
              <input
                type="checkbox"
                checked={onlyPassing}
                onChange={(event) => setOnlyPassing(event.target.checked)}
                className="h-3.5 w-3.5 accent-primary"
              />
              Only matches
            </label>
          )}
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="data-table w-full min-w-[880px] text-left">
          <thead>
            <tr className="border-b">
              <th className="px-4 py-2.5"><span className="eyebrow text-[9px]">Security</span></th>
              {COLUMNS.map((key) => {
                const spec = FIELD_BY_KEY.get(key)!;
                return (
                  <th key={key} className="px-3 py-2.5 text-right">
                    <button
                      type="button"
                      onClick={() => sortBy(key)}
                      className={cn(
                        "eyebrow text-[9px] transition-colors hover:text-foreground",
                        sortKey === key && "text-primary",
                      )}
                    >
                      {spec.label}{sortKey === key ? (ascending ? " ↑" : " ↓") : ""}
                    </button>
                  </th>
                );
              })}
              <th className="w-10 px-2 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => {
              const isSelected = row.symbol === selected;
              const meets = activeStandardCount > 0 && passing.has(row.symbol);
              return (
                <tr
                  key={row.symbol}
                  onClick={() => onSelect(row.symbol)}
                  className={cn(
                    "cursor-pointer border-b border-border/50 transition-colors last:border-0",
                    isSelected ? "bg-primary/[0.07]" : "hover:bg-primary/[0.04]",
                  )}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {meets && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-success" title="Meets every active standard" />}
                      <div className="min-w-0">
                        <p className="figure truncate text-[11px] font-semibold">{row.symbol}</p>
                        <p className="truncate text-[10px] text-muted-foreground">{row.name}</p>
                      </div>
                    </div>
                  </td>
                  {COLUMNS.map((key) => {
                    const spec = FIELD_BY_KEY.get(key)!;
                    const value = row[key] as number | null;
                    return (
                      <td
                        key={key}
                        className={cn(
                          "figure px-3 py-3 text-right text-[11px]",
                          key === "change_percent" ? pctTone(value) : "text-foreground",
                        )}
                      >
                        {formatField(value, spec.format, row.currency)}
                      </td>
                    );
                  })}
                  <td className="px-2 py-3">
                    <button
                      type="button"
                      onClick={(event) => { event.stopPropagation(); watchlist.toggle(row.symbol); }}
                      className="rounded p-1.5 text-muted-foreground transition hover:text-primary"
                      aria-label={watchlist.has(row.symbol) ? `Remove ${row.symbol} from watchlist` : `Add ${row.symbol} to watchlist`}
                    >
                      {watchlist.has(row.symbol)
                        ? <BookmarkCheck className="h-3.5 w-3.5 text-primary" />
                        : <Bookmark className="h-3.5 w-3.5" />}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {!loading && visible.length === 0 && (
        <p className="px-5 py-8 text-center text-sm text-muted-foreground">
          {rows.length === 0 ? "Add securities to your watchlist to populate the grid." : "No security meets every active standard."}
        </p>
      )}

      {unavailable.length > 0 && (
        <p className="flex items-center gap-2 border-t px-5 py-2.5 text-[10px] text-warning">
          <AlertCircle className="h-3 w-3" /> No data returned for: {unavailable.join(", ")}
        </p>
      )}
    </article>
  );
}

// ---------------------------------------------------------------------------
// News
// ---------------------------------------------------------------------------

function NewsPanel({ news, error, symbol }: { news: NewsResponse | null; error: string | null; symbol: string }) {
  if (error) {
    return (
      <div className="terminal-card flex items-center gap-2 rounded-[20px] border bg-card/90 p-8 text-sm text-danger">
        <AlertCircle className="h-4 w-4" /> {error}
      </div>
    );
  }
  if (!news) {
    return (
      <div className="terminal-card flex items-center justify-center gap-2 rounded-[20px] border bg-card/90 p-10 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading headlines…
      </div>
    );
  }
  if (!news.items.length) {
    return (
      <div className="terminal-card rounded-[20px] border bg-card/90 p-10 text-center text-sm text-muted-foreground">
        No recent headlines published for {symbol}.
      </div>
    );
  }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      {news.items.map((item) => (
        <a
          key={item.id}
          href={item.url ?? undefined}
          target="_blank"
          rel="noopener noreferrer"
          className="spotlight spotlight-lift group terminal-card flex flex-col rounded-2xl border bg-card/80 p-4"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="eyebrow text-[9px]">{item.publisher || news.source}</span>
            {item.published_at && (
              <span className="figure text-[9px] text-muted-foreground">
                {new Date(item.published_at).toLocaleDateString()}
              </span>
            )}
          </div>
          <h3 className="mt-2.5 text-sm font-medium leading-5 tracking-tight">{item.title}</h3>
          {item.summary && (
            <p className="mt-2 line-clamp-3 text-xs leading-5 text-muted-foreground">{item.summary}</p>
          )}
          <span className="mt-auto flex items-center gap-1.5 pt-3 text-[10px] text-muted-foreground transition group-hover:text-primary">
            Read source <ExternalLink className="h-3 w-3" />
          </span>
        </a>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fundamentals
// ---------------------------------------------------------------------------

const FUNDAMENTAL_GROUPS: { title: string; fields: [string, string][] }[] = [
  {
    title: "Valuation",
    fields: [
      ["marketCap", "Market cap"], ["enterpriseValue", "Enterprise value"],
      ["trailingPE", "P/E (TTM)"], ["forwardPE", "P/E (forward)"],
      ["priceToBook", "Price / book"], ["priceToSalesTrailing12Months", "Price / sales"],
      ["trailingEps", "EPS (TTM)"], ["forwardEps", "EPS (forward)"],
    ],
  },
  {
    title: "Profitability",
    fields: [
      ["profitMargins", "Net margin"], ["grossMargins", "Gross margin"],
      ["operatingMargins", "Operating margin"], ["returnOnEquity", "Return on equity"],
      ["returnOnAssets", "Return on assets"], ["revenueGrowth", "Revenue growth"],
      ["earningsGrowth", "Earnings growth"], ["totalRevenue", "Total revenue"],
    ],
  },
  {
    title: "Balance sheet",
    fields: [
      ["totalCash", "Total cash"], ["totalDebt", "Total debt"],
      ["debtToEquity", "Debt / equity"], ["currentRatio", "Current ratio"],
      ["quickRatio", "Quick ratio"], ["bookValue", "Book value"],
      ["freeCashflow", "Free cash flow"], ["operatingCashflow", "Operating cash flow"],
    ],
  },
  {
    title: "Market & ownership",
    fields: [
      ["beta", "Beta"], ["dividendYield", "Dividend yield"], ["payoutRatio", "Payout ratio"],
      ["fiftyDayAverage", "50-day average"], ["twoHundredDayAverage", "200-day average"],
      ["sharesOutstanding", "Shares outstanding"],
      ["heldPercentInsiders", "Held by insiders"], ["heldPercentInstitutions", "Held by institutions"],
    ],
  },
];

// Fields the provider reports as a 0..1 fraction rather than a percentage.
const FRACTION_FIELDS = new Set([
  "profitMargins", "grossMargins", "operatingMargins", "returnOnEquity", "returnOnAssets",
  "revenueGrowth", "earningsGrowth", "payoutRatio", "heldPercentInsiders", "heldPercentInstitutions",
]);
const BIG_NUMBER_FIELDS = new Set([
  "marketCap", "enterpriseValue", "totalRevenue", "totalCash", "totalDebt",
  "freeCashflow", "operatingCashflow", "sharesOutstanding",
]);

function FundamentalsPanel({
  fundamentals, currency, loading,
}: { fundamentals: Record<string, string | number | undefined>; currency: string | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="terminal-card flex items-center justify-center gap-2 rounded-[20px] border bg-card/90 p-10 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading fundamentals…
      </div>
    );
  }

  const summary = fundamentals.longBusinessSummary;

  return (
    <div className="space-y-5">
      {typeof summary === "string" && summary && (
        <article className="terminal-card rounded-[20px] border bg-card/90 p-5">
          <Eyebrow>Business</Eyebrow>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-muted-foreground">{summary}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {(["sector", "industry", "country", "fullTimeEmployees"] as const).map((key) => {
              const value = fundamentals[key];
              if (value === undefined || value === null) return null;
              return (
                <span key={key} className="rounded-full border bg-background/50 px-3 py-1.5 text-[10px] text-muted-foreground">
                  {typeof value === "number" ? value.toLocaleString() : value}
                </span>
              );
            })}
          </div>
        </article>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {FUNDAMENTAL_GROUPS.map((group) => (
          <article key={group.title} className="terminal-card spotlight rounded-2xl border bg-card/80 p-4">
            <Eyebrow>{group.title}</Eyebrow>
            <dl className="mt-3 space-y-2">
              {group.fields.map(([key, label]) => {
                const raw = fundamentals[key];
                const numeric = typeof raw === "number" && Number.isFinite(raw) ? raw : null;
                let display = "—";
                if (numeric !== null) {
                  if (FRACTION_FIELDS.has(key)) display = formatField(numeric, "percent01");
                  else if (BIG_NUMBER_FIELDS.has(key)) display = formatField(numeric, "currency", currency);
                  else if (key === "dividendYield") display = formatField(numeric, "percentPlain");
                  else display = formatField(numeric, "ratio");
                } else if (typeof raw === "string") {
                  display = raw;
                }
                return (
                  <div key={key} className="flex items-baseline justify-between gap-3 border-b border-border/40 pb-1.5 last:border-0">
                    <dt className="text-[11px] text-muted-foreground">{label}</dt>
                    <dd className="figure text-[11px]">{display}</dd>
                  </div>
                );
              })}
            </dl>
          </article>
        ))}
      </div>
    </div>
  );
}
