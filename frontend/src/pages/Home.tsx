import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  BarChart3,
  Building2,
  FileSearch,
  FileText,
  Loader2,
  Paperclip,
  Search,
  ShieldCheck,
  Users,
} from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api";

export interface AnalysisBrief {
  company: string;
  ticker?: string;
  factors: string;
  historyYears: number;
  strategyPath?: string;
  strategyName?: string;
  useTeam: boolean;
}

export function buildAnalysisPrompt(brief: AnalysisBrief): string {
  const strategy = brief.strategyPath
    ? `\nUploaded strategy: ${brief.strategyName || "strategy document"} at ${brief.strategyPath}. Read it first, extract explicit rules, state any ambiguity, and use those rules for a historical simulation. Never execute uploaded code.`
    : "\nNo strategy document was supplied. Do not invent a strategy or run a strategy simulation unless the requested factors require one.";
  const team = brief.useTeam
    ? "\nUse the multi-agent investment committee for independent financial, qualitative, risk, and strategy review, then reconcile disagreements in the final answer."
    : "";

  return `Perform a complete, evidence-backed company analysis.

Company: ${brief.company}
Ticker or exchange symbol: ${brief.ticker?.trim() || "Resolve it and show the resolution."}
Analysis factors requested by the user: ${brief.factors.trim()}
History: current reporting year plus the previous ${brief.historyYears} year(s).
${strategy}${team}

Required workflow:
1. Resolve and verify the company's official website. Fetch annual reports, quarterly results, investor presentations, and material filings for the requested years from that official website. Use exchange/regulator filings when they are the authoritative primary source.
2. Extract comparable income statement, balance sheet, cash-flow, and per-share metrics. Show year-over-year trends and clearly label fiscal periods, currency, units, restatements, and missing data.
3. Fetch market data through public non-broker sources such as yfinance/Yahoo Finance and Google Finance where available. Do not connect to a brokerage account.
4. Gather dated qualitative evidence from verified sources including Reuters, Mint, Economic Times, Times of India, Moneycontrol, regulators, exchanges, and rating agencies. Prefer primary documents over news summaries and cite every material claim with its source URL and date.
5. Analyze only the factors requested above. Separate facts, calculations, interpretation, risks, and unknowns. Do not fill missing values with estimates unless explicitly marked as an estimate with its formula.
6. If a strategy was uploaded, convert it into transparent rules and run a historical simulation with data availability, look-ahead, survivorship, costs, and overfitting checks. This is research only; never place or prepare an order.
7. Finish with a concise conclusion, key evidence table, financial trend table, risks, data limitations, and reproducible simulation assumptions when applicable.`;
}

export function Home() {
  const navigate = useNavigate();
  const [company, setCompany] = useState("");
  const [ticker, setTicker] = useState("");
  const [factors, setFactors] = useState(
    "Revenue growth, margins, cash generation, balance-sheet strength, valuation, management execution, competitive position, catalysts, and key risks.",
  );
  const [historyYears, setHistoryYears] = useState(3);
  const [strategyFile, setStrategyFile] = useState<File | null>(null);
  const [useTeam, setUseTeam] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const periodLabel = useMemo(
    () => `Current year + ${historyYears} previous year${historyYears === 1 ? "" : "s"}`,
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
      let uploaded: Awaited<ReturnType<typeof api.uploadFile>> | undefined;
      if (strategyFile) uploaded = await api.uploadFile(strategyFile);

      const session = await api.createSession(`${company.trim()} analysis`);
      await api.sendMessage(
        session.session_id,
        buildAnalysisPrompt({
          company: company.trim(),
          ticker: ticker.trim(),
          factors,
          historyYears,
          strategyPath: uploaded?.file_path,
          strategyName: uploaded?.filename,
          useTeam,
        }),
      );
      navigate(`/agent?session=${encodeURIComponent(session.session_id)}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "The analysis could not be started.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-full bg-gradient-to-b from-primary/[0.06] via-background to-background px-5 py-10 md:px-8">
      <div className="mx-auto max-w-6xl">
        <div className="mb-8 max-w-3xl">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border bg-background/80 px-3 py-1 text-xs font-medium text-primary">
            <ShieldCheck className="h-3.5 w-3.5" /> Evidence-first, analysis-only
          </div>
          <h1 className="text-3xl font-bold tracking-tight md:text-5xl">Company research without the trading clutter.</h1>
          <p className="mt-3 text-base leading-relaxed text-muted-foreground md:text-lg">
            Give the tool a company and your decision factors. It gathers primary reports, checks reliable news,
            analyzes the numbers, and can test an uploaded strategy—all without connecting to a broker.
          </p>
        </div>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <form onSubmit={submit} className="space-y-5 rounded-2xl border bg-card p-5 shadow-sm md:p-7">
            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2">
                <span className="flex items-center gap-2 text-sm font-medium"><Building2 className="h-4 w-4 text-primary" /> Company</span>
                <input
                  value={company}
                  onChange={(event) => setCompany(event.target.value)}
                  placeholder="e.g. Reliance Industries"
                  className="w-full rounded-lg border bg-background px-3 py-2.5 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
                />
              </label>
              <label className="space-y-2">
                <span className="flex items-center gap-2 text-sm font-medium"><BarChart3 className="h-4 w-4 text-primary" /> Ticker <span className="font-normal text-muted-foreground">optional</span></span>
                <input
                  value={ticker}
                  onChange={(event) => setTicker(event.target.value)}
                  placeholder="e.g. RELIANCE.NS"
                  className="w-full rounded-lg border bg-background px-3 py-2.5 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
                />
              </label>
            </div>

            <label className="block space-y-2">
              <span className="flex items-center gap-2 text-sm font-medium"><Search className="h-4 w-4 text-primary" /> What should the analysis focus on?</span>
              <textarea
                value={factors}
                onChange={(event) => setFactors(event.target.value)}
                rows={5}
                className="w-full resize-y rounded-lg border bg-background px-3 py-2.5 text-sm leading-relaxed outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
              />
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="space-y-2">
                <span className="flex items-center gap-2 text-sm font-medium"><FileText className="h-4 w-4 text-primary" /> Reporting history</span>
                <select
                  value={historyYears}
                  onChange={(event) => setHistoryYears(Number(event.target.value))}
                  className="w-full rounded-lg border bg-background px-3 py-2.5 text-sm outline-none focus:border-primary"
                >
                  {[1, 2, 3, 4, 5].map((years) => <option key={years} value={years}>Current + {years} prior year{years === 1 ? "" : "s"}</option>)}
                </select>
              </label>

              <label className="space-y-2">
                <span className="flex items-center gap-2 text-sm font-medium"><Paperclip className="h-4 w-4 text-primary" /> Strategy document <span className="font-normal text-muted-foreground">optional</span></span>
                <input
                  type="file"
                  accept=".pdf,.doc,.docx,.txt,.md,.csv,.tsv,.xlsx,.xls,.json,.pine"
                  onChange={(event) => setStrategyFile(event.target.files?.[0] ?? null)}
                  className="block w-full rounded-lg border bg-background text-sm text-muted-foreground file:mr-3 file:border-0 file:border-r file:bg-muted file:px-3 file:py-2.5 file:text-sm file:font-medium file:text-foreground"
                />
              </label>
            </div>

            <label className="flex cursor-pointer items-start gap-3 rounded-lg border bg-muted/25 p-3">
              <input
                type="checkbox"
                checked={useTeam}
                onChange={(event) => setUseTeam(event.target.checked)}
                className="mt-0.5 h-4 w-4 accent-primary"
              />
              <span>
                <span className="flex items-center gap-1.5 text-sm font-medium"><Users className="h-4 w-4" /> Use the shadow analysis team</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">Adds independent financial, qualitative, risk, and strategy reviews. Slower, but useful for high-stakes research.</span>
              </span>
            </label>

            <button
              type="submit"
              disabled={submitting}
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60 md:w-auto"
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSearch className="h-4 w-4" />}
              {submitting ? "Starting analysis…" : "Run complete analysis"}
            </button>
          </form>

          <aside className="space-y-4">
            <div className="rounded-2xl border bg-card p-5">
              <h2 className="text-sm font-semibold">Research package</h2>
              <ul className="mt-3 space-y-3 text-sm text-muted-foreground">
                <li className="flex gap-2"><FileText className="mt-0.5 h-4 w-4 shrink-0 text-primary" /> Official annual and quarterly reports</li>
                <li className="flex gap-2"><BarChart3 className="mt-0.5 h-4 w-4 shrink-0 text-primary" /> Financial trends and market data</li>
                <li className="flex gap-2"><Search className="mt-0.5 h-4 w-4 shrink-0 text-primary" /> Dated, source-linked qualitative evidence</li>
                <li className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" /> Risks, unknowns, and data-quality checks</li>
              </ul>
            </div>
            <div className="rounded-2xl border bg-card p-5">
              <h2 className="text-sm font-semibold">Evidence sources</h2>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                {[
                  "Company filings", "Reuters", "Mint", "Economic Times", "TOI",
                  "Moneycontrol", "Yahoo Finance", "Google Finance", "NSE/BSE", "SEBI/RBI",
                ].map((source) => <span key={source} className="rounded-full border bg-muted/40 px-2.5 py-1">{source}</span>)}
              </div>
              <p className="mt-4 text-xs leading-relaxed text-muted-foreground">Period: {periodLabel}. Sources are attributed; missing evidence is reported instead of silently guessed.</p>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
