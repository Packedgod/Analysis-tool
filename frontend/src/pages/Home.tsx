import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Building2,
  CalendarDays,
  Check,
  ChevronRight,
  Database,
  FileText,
  Gauge,
  Loader2,
  Paperclip,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";
import { toast } from "sonner";

import { api, type MarketOverview, type MarketOverviewItem, type UploadResult } from "@/lib/api";
import { cn } from "@/lib/utils";

const DEFAULT_FACTORS =
  "Revenue growth, margins, cash generation, balance-sheet strength, valuation, management execution, competitive position, catalysts, and key risks.";

const EMPTY_MARKET: MarketOverview = {
  status: "unavailable",
  source: "Yahoo Finance",
  observed_at: null,
  refresh_seconds: 60,
  items: [],
};

const WORKFLOW = [
  { label: "Resolve", detail: "Issuer identity", icon: Search },
  { label: "Verify", detail: "Primary evidence", icon: ShieldCheck },
  { label: "Model", detail: "Financial history", icon: Database },
  { label: "Simulate", detail: "Risk & returns", icon: BarChart3 },
];

function StockMark({ item, small = false }: { item: Pick<MarketOverviewItem, "mark" | "name">; small?: boolean }) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-full border border-primary/25 bg-gradient-to-br from-primary/25 to-primary/5 font-mono font-bold text-primary shadow-[inset_0_1px_0_hsl(var(--foreground)/0.08)]",
        small ? "h-7 w-7 text-[8px]" : "h-10 w-10 text-[10px]",
      )}
      aria-label={`${item.name} symbol mark`}
    >
      {item.mark.slice(0, small ? 4 : 5)}
    </span>
  );
}

function formatPrice(value: number) {
  return new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: value >= 1000 ? 0 : 2,
    minimumFractionDigits: value >= 1000 ? 0 : 2,
  }).format(value);
}

function MarketTape({ market }: { market: MarketOverview }) {
  if (market.items.length === 0) {
    return (
      <div className="market-tape h-11 border-y">
        <div className="mx-auto flex h-full max-w-[1540px] items-center gap-3 px-5 text-xs text-muted-foreground lg:px-7">
          <span className="h-2 w-2 rounded-full bg-warning" /> Market pulse is reconnecting; research remains available.
        </div>
      </div>
    );
  }

  const repeated = [...market.items, ...market.items];
  return (
    <div className="market-tape group h-11 overflow-hidden border-y" aria-label="Live market prices">
      <div className="market-tape-track flex h-full w-max items-center group-hover:[animation-play-state:paused]">
        {repeated.map((item, index) => {
          const up = item.change_percent >= 0;
          return (
            <div key={`${item.symbol}-${index}`} className="flex h-full items-center gap-3 border-r px-5">
              <span className="font-mono text-[11px] font-bold text-foreground">{item.symbol}</span>
              <span className="font-mono text-xs tabular-nums">₹{formatPrice(item.price)}</span>
              <span className={cn("flex items-center gap-1 font-mono text-[10px] font-semibold", up ? "text-success" : "text-danger")}>
                {up ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                {up ? "+" : ""}{item.change_percent.toFixed(2)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function Home() {
  const navigate = useNavigate();
  const [company, setCompany] = useState("");
  const [ticker, setTicker] = useState("");
  const [factors, setFactors] = useState(DEFAULT_FACTORS);
  const [historyYears, setHistoryYears] = useState(3);
  const [strategyFile, setStrategyFile] = useState<File | null>(null);
  const [uploadedSource, setUploadedSource] = useState<UploadResult | null>(null);
  const [useTeam, setUseTeam] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [market, setMarket] = useState<MarketOverview>(EMPTY_MARKET);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const load = async () => {
      try {
        const next = await api.getMarketOverview(controller.signal);
        if (active) setMarket(next);
      } catch {
        // Market data is deliberately non-blocking: retain the last verified snapshot.
      }
    };
    void load();
    const timer = window.setInterval(load, 60_000);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  const periodLabel = useMemo(() => `${historyYears + 1} fiscal years`, [historyYears]);
  const performers = useMemo(
    () => market.items.filter((item) => item.mark !== "INDEX").sort((a, b) => b.change_percent - a.change_percent).slice(0, 5),
    [market.items],
  );
  const lead = performers[0] ?? market.items[0];

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!company.trim() || !factors.trim()) {
      toast.error("Add a company and the factors you want analyzed.");
      return;
    }
    setSubmitting(true);
    try {
      let uploaded = uploadedSource ?? undefined;
      if (strategyFile && !uploaded) {
        uploaded = await api.uploadFile(strategyFile);
        setUploadedSource(uploaded);
      }
      const started = await api.startAnalysis({
        company: company.trim(),
        ticker: ticker.trim() || undefined,
        factors: factors.trim(),
        history_years: historyYears,
        strategy_path: uploaded?.file_path,
        strategy_name: uploaded?.filename,
        use_team: useTeam,
      });
      navigate(`/agent?session=${encodeURIComponent(started.session_id)}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "The analysis could not be started.");
    } finally {
      setSubmitting(false);
    }
  };

  const selectFile = (file: File | null) => {
    setStrategyFile(file);
    setUploadedSource(null);
  };

  return (
    <div className="terminal-shell min-h-full">
      <MarketTape market={market} />

      <main className="mx-auto max-w-[1540px] space-y-5 px-4 py-5 sm:px-5 lg:px-7 lg:py-7">
        <section className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(360px,.72fr)]">
          <article className="terminal-card market-grid relative min-h-[490px] overflow-hidden rounded-[22px] border p-5 sm:p-7 lg:p-9">
            <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_78%_36%,hsl(var(--primary)/0.18),transparent_28%)]" />
            <div className="relative z-10 flex h-full flex-col">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/10 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">
                  <Activity className="h-3.5 w-3.5" /> Evidence intelligence online
                </div>
                <div className="flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
                  <span className={cn("h-2 w-2 rounded-full", market.status === "live" ? "animate-pulse bg-success" : "bg-warning")} />
                  {market.status === "live" ? "Live market feed" : market.status === "stale" ? "Cached market feed" : "Feed reconnecting"}
                </div>
              </div>

              <div className="mt-9 max-w-4xl">
                <p className="mb-3 font-mono text-xs uppercase tracking-[0.22em] text-muted-foreground">Vantage research terminal</p>
                <h1 className="text-4xl font-semibold leading-[0.98] tracking-[-0.05em] sm:text-5xl lg:text-7xl">
                  See the evidence.<br /><span className="text-primary">Understand the equity.</span>
                </h1>
                <p className="mt-5 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">
                  One workspace for source-linked company research, interactive financials, portfolio simulation, risk diagnostics, and audit-ready reports.
                </p>
              </div>

              <div className="mt-auto grid gap-3 pt-8 sm:grid-cols-2 lg:grid-cols-4">
                {WORKFLOW.map(({ label, detail, icon: Icon }, index) => (
                  <div key={label} className="group rounded-xl border bg-background/35 p-3 backdrop-blur-sm transition hover:-translate-y-0.5 hover:border-primary/35 hover:bg-primary/5">
                    <div className="flex items-center justify-between">
                      <Icon className="h-4 w-4 text-primary" />
                      <span className="font-mono text-[9px] text-muted-foreground">0{index + 1}</span>
                    </div>
                    <p className="mt-3 text-sm font-semibold">{label}</p>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">{detail}</p>
                  </div>
                ))}
              </div>
            </div>
          </article>

          <form onSubmit={submit} className="terminal-card overflow-hidden rounded-[22px] border bg-card/95">
            <div className="flex items-start justify-between border-b px-5 py-5 sm:px-6">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-primary">Launch research</p>
                <h2 className="mt-1.5 text-xl font-semibold tracking-tight">Build an investment view</h2>
              </div>
              <span className="rounded-lg border bg-background/60 px-2.5 py-1.5 font-mono text-[10px] text-muted-foreground">{periodLabel}</span>
            </div>

            <div className="space-y-4 p-5 sm:p-6">
              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_150px]">
                <label className="space-y-2">
                  <span className="field-label"><Building2 className="h-3.5 w-3.5" /> Company</span>
                  <input value={company} onChange={(event) => setCompany(event.target.value)} placeholder="Reliance Industries" autoComplete="organization" className="stock-input" />
                </label>
                <label className="space-y-2">
                  <span className="field-label"><TrendingUp className="h-3.5 w-3.5" /> Symbol</span>
                  <input value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} placeholder="RELIANCE.NS" className="stock-input font-mono uppercase" />
                </label>
              </div>

              <label className="block space-y-2">
                <span className="field-label"><Search className="h-3.5 w-3.5" /> Research brief</span>
                <textarea value={factors} onChange={(event) => setFactors(event.target.value)} rows={5} className="stock-input resize-none leading-relaxed" />
              </label>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-2">
                  <span className="field-label"><CalendarDays className="h-3.5 w-3.5" /> History</span>
                  <select value={historyYears} onChange={(event) => setHistoryYears(Number(event.target.value))} className="stock-input">
                    {[1, 2, 3, 4, 5, 7, 10].map((years) => <option key={years} value={years}>Current + {years} prior year{years === 1 ? "" : "s"}</option>)}
                  </select>
                </label>
                <label className="space-y-2">
                  <span className="field-label"><Paperclip className="h-3.5 w-3.5" /> Verified source</span>
                  <input type="file" accept=".pdf,.doc,.docx,.txt,.md,.csv,.tsv,.xlsx,.xls,.json,.pine" onChange={(event) => selectFile(event.target.files?.[0] ?? null)} className="file-input" />
                </label>
              </div>

              {strategyFile && (
                <div className="flex items-center gap-3 rounded-xl border border-success/25 bg-success/5 px-3 py-2.5 text-xs">
                  <ShieldCheck className="h-4 w-4 shrink-0 text-success" />
                  <span className="min-w-0 flex-1 truncate"><strong>{strategyFile.name}</strong> · authoritative user source</span>
                  {uploadedSource && <Check className="h-4 w-4 text-success" />}
                </div>
              )}

              <label className="flex cursor-pointer items-center justify-between rounded-xl border bg-background/40 px-3 py-3 text-xs">
                <span className="flex items-center gap-2"><Users className="h-4 w-4 text-primary" /> Use shadow analyst team</span>
                <input type="checkbox" checked={useTeam} onChange={(event) => setUseTeam(event.target.checked)} className="h-4 w-4 accent-primary" />
              </label>

              <button type="submit" disabled={submitting} className="primary-action w-full py-3.5">
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {submitting ? "Opening research workspace…" : "Start analysis"}
                {!submitting && <ArrowRight className="h-4 w-4" />}
              </button>
            </div>
          </form>
        </section>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,.92fr)_minmax(310px,.7fr)]">
          <article className="terminal-card overflow-hidden rounded-[20px] border bg-card/90">
            <div className="flex items-center justify-between border-b px-5 py-4">
              <div><p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Market pulse</p><h2 className="mt-1 text-base font-semibold">Observed leaders</h2></div>
              <div className="flex items-center gap-2 font-mono text-[9px] text-muted-foreground"><Zap className="h-3.5 w-3.5 text-primary" /> {market.source}</div>
            </div>
            <div className="divide-y">
              {performers.length ? performers.map((item, index) => (
                <div key={item.symbol} className="flex items-center gap-3 px-5 py-3 transition hover:bg-primary/[0.035]">
                  <span className="w-4 font-mono text-[9px] text-muted-foreground">0{index + 1}</span>
                  <StockMark item={item} small />
                  <div className="min-w-0 flex-1"><p className="truncate text-xs font-semibold">{item.name}</p><p className="font-mono text-[9px] text-muted-foreground">{item.symbol}</p></div>
                  <p className="font-mono text-xs tabular-nums">₹{formatPrice(item.price)}</p>
                  <p className={cn("w-16 text-right font-mono text-[10px] font-semibold", item.change_percent >= 0 ? "text-success" : "text-danger")}>{item.change_percent >= 0 ? "+" : ""}{item.change_percent.toFixed(2)}%</p>
                </div>
              )) : <div className="p-7 text-sm text-muted-foreground">Waiting for a verified market snapshot.</div>}
            </div>
          </article>

          <article className="terminal-card relative min-h-[310px] overflow-hidden rounded-[20px] border bg-card/90 p-5">
            <div className="flex items-start justify-between">
              <div><p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Research signal</p><h2 className="mt-1 text-base font-semibold">Evidence coverage</h2></div>
              <Gauge className="h-5 w-5 text-primary" />
            </div>
            <div className="mt-6 grid grid-cols-3 gap-3">
              {[['Sources', 'Primary'], ['Claims', 'Traceable'], ['Models', 'Audited']].map(([label, value]) => (
                <div key={label} className="rounded-xl border bg-background/35 p-3"><p className="text-[9px] uppercase tracking-wider text-muted-foreground">{label}</p><p className="mt-1 text-xs font-semibold text-primary">{value}</p></div>
              ))}
            </div>
            <div className="relative mt-7 h-28">
              <svg className="h-full w-full overflow-visible" viewBox="0 0 560 120" preserveAspectRatio="none" aria-label="Evidence workflow activity visualization">
                <defs><linearGradient id="coverageFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="hsl(var(--primary))" stopOpacity=".28" /><stop offset="1" stopColor="hsl(var(--primary))" stopOpacity="0" /></linearGradient></defs>
                <path d="M0 102 C50 93 67 72 112 79 C157 86 174 41 222 49 C270 57 287 86 336 61 C382 38 405 51 448 29 C488 9 522 25 560 8 L560 120 L0 120 Z" fill="url(#coverageFill)" />
                <path d="M0 102 C50 93 67 72 112 79 C157 86 174 41 222 49 C270 57 287 86 336 61 C382 38 405 51 448 29 C488 9 522 25 560 8" fill="none" stroke="hsl(var(--primary))" strokeWidth="3" vectorEffect="non-scaling-stroke" />
              </svg>
            </div>
            <div className="flex items-center justify-between font-mono text-[9px] text-muted-foreground"><span>Identity</span><span>Filings</span><span>Financials</span><span>Simulation</span><span>Report</span></div>
          </article>

          <aside className="terminal-card rounded-[20px] border bg-card/90 p-5">
            <div className="flex items-center justify-between"><div><p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Current leader</p><h2 className="mt-1 text-base font-semibold">Verified snapshot</h2></div>{lead && <StockMark item={lead} />}</div>
            {lead ? (
              <div className="mt-6">
                <p className="text-3xl font-semibold tracking-tight">₹{formatPrice(lead.price)}</p>
                <p className={cn("mt-2 flex items-center gap-1.5 font-mono text-xs", lead.change_percent >= 0 ? "text-success" : "text-danger")}><TrendingUp className="h-3.5 w-3.5" /> {lead.change_percent >= 0 ? "+" : ""}{lead.change_percent.toFixed(2)}% latest session</p>
                <div className="mt-6 rounded-xl border bg-background/40 p-4"><p className="text-sm font-semibold">{lead.name}</p><p className="mt-1 font-mono text-[10px] text-muted-foreground">{lead.symbol}</p></div>
              </div>
            ) : <p className="mt-6 text-sm text-muted-foreground">No price is displayed until the market source responds.</p>}
            <button type="button" onClick={() => { if (lead) { setCompany(lead.name); setTicker(lead.symbol); } }} disabled={!lead} className="mt-5 flex w-full items-center justify-between rounded-xl border px-3 py-3 text-xs font-medium transition hover:border-primary/35 hover:bg-primary/5 disabled:opacity-40">
              Analyze this company <ChevronRight className="h-4 w-4 text-primary" />
            </button>
          </aside>
        </section>

        <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            [FileText, "Source-linked reports", "Every material claim retains its evidence trail."],
            [BarChart3, "Interactive charts", "Zoomable financial, price, equity, and risk views."],
            [ShieldCheck, "Audit artifacts", "Metrics, validation, trades, and reproducibility hashes."],
            [Zap, "Responsive workflow", "Independent loading paths keep the workspace interactive."],
          ].map(([Icon, title, copy]) => {
            const FeatureIcon = Icon as typeof FileText;
            return <div key={String(title)} className="terminal-card rounded-2xl border bg-card/70 p-4"><FeatureIcon className="h-4 w-4 text-primary" /><p className="mt-3 text-sm font-semibold">{String(title)}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{String(copy)}</p></div>;
          })}
        </section>
      </main>
    </div>
  );
}
