import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Building2,
  Check,
  Database,
  FileSearch,
  FileText,
  Loader2,
  Paperclip,
  Search,
  ShieldCheck,
  TrendingUp,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import { api, type UploadResult } from "@/lib/api";

const DEFAULT_FACTORS =
  "Revenue growth, margins, cash generation, balance-sheet strength, valuation, management execution, competitive position, catalysts, and key risks.";

const SOURCE_MARKS = ["NSE / BSE", "Yahoo Finance", "Google Finance", "Reuters", "Company IR"];

const COVERAGE_CARDS = [
  { label: "Evidence", value: "Cited", icon: Database },
  { label: "Pricing", value: "Fallback", icon: TrendingUp },
  { label: "Backtest", value: "Included", icon: BarChart3 },
];

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

  const periodLabel = useMemo(
    () => `${historyYears + 1} fiscal years`,
    [historyYears],
  );

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
    <div className="min-h-full bg-background">
      <div className="market-grid border-b border-border/70">
        <div className="mx-auto flex max-w-7xl items-center gap-5 overflow-hidden px-5 py-2 text-[11px] uppercase tracking-[0.16em] text-muted-foreground md:px-8">
          <span className="flex shrink-0 items-center gap-2 font-semibold text-success">
            <span className="h-1.5 w-1.5 rounded-full bg-success shadow-[0_0_10px_hsl(var(--success))]" />
            Research engine online
          </span>
          <span className="h-3 w-px shrink-0 bg-border" />
          {SOURCE_MARKS.map((source) => (
            <span key={source} className="shrink-0">{source}</span>
          ))}
        </div>
      </div>

      <div className="mx-auto max-w-7xl px-5 py-7 md:px-8 md:py-10">
        <section className="mb-7 grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
          <div>
            <div className="mb-4 inline-flex items-center gap-2 rounded-md border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.14em] text-primary">
              <Activity className="h-3.5 w-3.5" /> Equity intelligence workspace
            </div>
            <h1 className="max-w-4xl text-4xl font-semibold leading-[1.02] tracking-[-0.04em] md:text-6xl">
              Turn filings and market data into an investment view.
            </h1>
            <p className="mt-4 max-w-3xl text-base leading-relaxed text-muted-foreground md:text-lg">
              Research listed companies, reconcile evidence, retrieve resilient price history,
              and complete a historical simulation in one focused workspace.
            </p>
          </div>
          <div className="stock-panel grid grid-cols-3 gap-px overflow-hidden rounded-xl border bg-border">
            {COVERAGE_CARDS.map(({ label, value, icon: Icon }) => (
              <div key={label} className="bg-card p-4">
                <Icon className="mb-3 h-4 w-4 text-primary" />
                <p className="text-[10px] uppercase tracking-[0.16em] text-muted-foreground">{label}</p>
                <p className="mt-1 text-sm font-semibold">{value}</p>
              </div>
            ))}
          </div>
        </section>

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
          <form onSubmit={submit} className="stock-panel overflow-hidden rounded-xl border bg-card shadow-2xl shadow-black/5">
            <div className="flex items-center justify-between border-b bg-muted/25 px-5 py-3.5 md:px-6">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">New analysis</p>
                <p className="mt-1 text-sm text-muted-foreground">Define the company and decision lens.</p>
              </div>
              <span className="rounded-md border bg-background px-2.5 py-1 font-mono text-[11px] text-muted-foreground">{periodLabel}</span>
            </div>

            <div className="space-y-5 p-5 md:p-6">
              <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_240px]">
                <label className="space-y-2">
                  <span className="field-label"><Building2 className="h-3.5 w-3.5" /> Company</span>
                  <input
                    value={company}
                    onChange={(event) => setCompany(event.target.value)}
                    placeholder="Reliance Industries"
                    autoComplete="organization"
                    className="stock-input"
                  />
                </label>
                <label className="space-y-2">
                  <span className="field-label"><TrendingUp className="h-3.5 w-3.5" /> Ticker <em>optional</em></span>
                  <input
                    value={ticker}
                    onChange={(event) => setTicker(event.target.value.toUpperCase())}
                    placeholder="RELIANCE.NS"
                    className="stock-input font-mono uppercase"
                  />
                </label>
              </div>

              <label className="block space-y-2">
                <span className="field-label"><Search className="h-3.5 w-3.5" /> Analysis focus</span>
                <textarea
                  value={factors}
                  onChange={(event) => setFactors(event.target.value)}
                  rows={4}
                  className="stock-input resize-y leading-relaxed"
                />
              </label>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-2">
                  <span className="field-label"><FileText className="h-3.5 w-3.5" /> Financial history</span>
                  <select
                    value={historyYears}
                    onChange={(event) => setHistoryYears(Number(event.target.value))}
                    className="stock-input"
                  >
                    {[1, 2, 3, 4, 5, 7, 10].map((years) => (
                      <option key={years} value={years}>Current + {years} prior year{years === 1 ? "" : "s"}</option>
                    ))}
                  </select>
                </label>

                <label className="space-y-2">
                  <span className="field-label"><Paperclip className="h-3.5 w-3.5" /> Verified user source <em>optional</em></span>
                  <input
                    type="file"
                    accept=".pdf,.doc,.docx,.txt,.md,.csv,.tsv,.xlsx,.xls,.json,.pine"
                    onChange={(event) => selectFile(event.target.files?.[0] ?? null)}
                    className="block w-full rounded-md border bg-background text-xs text-muted-foreground file:mr-3 file:border-0 file:border-r file:bg-muted file:px-3 file:py-3 file:text-xs file:font-semibold file:text-foreground"
                  />
                </label>
              </div>

              {strategyFile && (
                <div className="flex items-center gap-3 rounded-lg border border-success/30 bg-success/5 px-3 py-2.5 text-sm">
                  <ShieldCheck className="h-4 w-4 shrink-0 text-success" />
                  <span className="min-w-0 flex-1 truncate"><strong>{strategyFile.name}</strong> will be treated as a verified user source.</span>
                  {uploadedSource && <span className="flex items-center gap-1 text-xs text-success"><Check className="h-3.5 w-3.5" /> Hashed</span>}
                </div>
              )}

              <div className="flex flex-col gap-4 border-t pt-5 sm:flex-row sm:items-center sm:justify-between">
                <label className="flex cursor-pointer items-center gap-2.5 text-sm">
                  <input
                    type="checkbox"
                    checked={useTeam}
                    onChange={(event) => setUseTeam(event.target.checked)}
                    className="h-4 w-4 accent-primary"
                  />
                  <Users className="h-4 w-4 text-muted-foreground" />
                  <span>Use shadow analyst team</span>
                </label>

                <button type="submit" disabled={submitting} className="primary-action">
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />}
                  {submitting ? "Opening research workspaceâ€¦" : "Start analysis"}
                </button>
              </div>
            </div>
          </form>

          <aside className="space-y-5">
            <div className="stock-panel rounded-xl border bg-card p-5">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Output coverage</p>
                <ShieldCheck className="h-4 w-4 text-success" />
              </div>
              <ul className="mt-4 space-y-3">
                {[
                  "Issuer filings and financial trends",
                  "Resolved identity and current price",
                  "Source-linked qualitative evidence",
                  "Historical simulation and risk diagnostics",
                ].map((item) => (
                  <li key={item} className="flex gap-2.5 text-sm text-muted-foreground">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" /> {item}
                  </li>
                ))}
              </ul>
            </div>

            <div className="stock-panel rounded-xl border bg-card p-5">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Data posture</p>
              <div className="mt-4 space-y-3 text-sm">
                <div className="flex items-center justify-between"><span className="text-muted-foreground">Uploaded files</span><span className="font-medium text-success">Verified</span></div>
                <div className="flex items-center justify-between"><span className="text-muted-foreground">Price fallback</span><span className="font-medium">Active</span></div>
                <div className="flex items-center justify-between"><span className="text-muted-foreground">Simulation</span><span className="font-medium">Always included</span></div>
                <div className="flex items-center justify-between"><span className="text-muted-foreground">Broker access</span><span className="font-medium">Disabled</span></div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

