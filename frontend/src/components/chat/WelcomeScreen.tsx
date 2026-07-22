import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Building2,
  FileCheck2,
  Files,
  FlaskConical,
  LayoutDashboard,
  Network,
  PieChart,
  Search,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";

interface ResearchMode {
  title: string;
  eyebrow: string;
  description: string;
  prompt: string;
  icon: ReactNode;
  tone: string;
}

const RESEARCH_MODES: ResearchMode[] = [
  {
    title: "Company Research",
    eyebrow: "Single security",
    description: "Build a source-linked view of the business, financials, valuation, management, catalysts, and risks.",
    prompt: "Research a listed company as an evidence-first equity analyst. Resolve the exact security, use primary sources where possible, analyze the business, financial history, valuation, management, catalysts, and risks, and clearly separate verified facts from inference.",
    icon: <Building2 className="h-5 w-5" />,
    tone: "text-primary bg-primary/10 border-primary/20",
  },
  {
    title: "Investment Team",
    eyebrow: "Committee review",
    description: "Assemble long, short, valuation, forensic, and risk perspectives into one investment decision.",
    prompt: "[Swarm Team Mode] Assemble an investment committee for my next request: include a fundamental analyst, valuation analyst, forensic skeptic, industry specialist, and risk chair. Require evidence for material claims and synthesize consensus, disagreements, and open questions.",
    icon: <Users className="h-5 w-5" />,
    tone: "text-violet-400 bg-violet-500/10 border-violet-500/20",
  },
  {
    title: "Analysis Swarm",
    eyebrow: "Parallel specialists",
    description: "Run independent specialists in parallel for broad, complex, or cross-market research questions.",
    prompt: "[Swarm Team Mode] Use the best analysis swarm for my next research question. Divide the work into independent evidence, financial, industry, competitive, valuation, and risk workstreams, then reconcile contradictions before answering.",
    icon: <Network className="h-5 w-5" />,
    tone: "text-sky-400 bg-sky-500/10 border-sky-500/20",
  },
  {
    title: "Portfolio Lab",
    eyebrow: "Multi-asset view",
    description: "Study holdings, concentration, correlations, scenarios, allocation, drawdowns, and portfolio-level risk.",
    prompt: "Analyze my portfolio as a research and risk problem. Review each holding's role, concentration, factor and sector exposures, correlations, downside scenarios, and diversification gaps. Do not suggest trades without supporting evidence.",
    icon: <PieChart className="h-5 w-5" />,
    tone: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
  },
  {
    title: "Evidence Desk",
    eyebrow: "Documents & sources",
    description: "Interrogate filings, reports, spreadsheets, transcripts, and web evidence with a traceable audit trail.",
    prompt: "Use the files attached to this conversation as primary evidence. Extract the important claims and figures, reconcile inconsistencies, identify what is missing, and produce a citation-ready research brief without filling gaps with assumptions.",
    icon: <FileCheck2 className="h-5 w-5" />,
    tone: "text-amber-400 bg-amber-500/10 border-amber-500/20",
  },
  {
    title: "Strategy Lab",
    eyebrow: "Optional quant path",
    description: "Test an investment rule or hypothesis with reproducible backtests, benchmarks, and validation artifacts.",
    prompt: "Help me turn an investment hypothesis into a reproducible test. Define the universe, signal, rebalance logic, benchmark, transaction-cost assumptions, validation checks, and failure conditions before running any backtest.",
    icon: <FlaskConical className="h-5 w-5" />,
    tone: "text-rose-400 bg-rose-500/10 border-rose-500/20",
  },
];

const CAPABILITIES = [
  "Primary-source research",
  "Company & sector analysis",
  "Investment committees",
  "Parallel analysis swarms",
  "Portfolio diagnostics",
  "Document intelligence",
  "Valuation & scenarios",
  "Reproducible strategy tests",
];

interface Props {
  onExample: (prompt: string) => void;
}

export function WelcomeScreen({ onExample }: Props) {
  return (
    <div className="space-y-5 pb-8 text-left">
      <section className="terminal-card market-grid relative overflow-hidden rounded-[24px] border bg-card/75 p-5 sm:p-7 lg:p-9">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_82%_26%,hsl(var(--primary)/0.15),transparent_30rem)]" />
        <div className="relative z-10">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              <Link to="/" className="transition hover:text-primary">Dashboard</Link>
              <span>/</span>
              <span className="text-primary">Analysis workspace</span>
            </div>
            <span className="inline-flex items-center gap-2 rounded-full border border-success/25 bg-success/10 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-success">
              <span className="h-2 w-2 animate-pulse rounded-full bg-success" /> Evidence system online
            </span>
          </div>

          <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1.3fr)_minmax(300px,.7fr)] lg:items-end">
            <div>
              <div className="mb-5 grid h-14 w-14 place-items-center rounded-2xl border border-primary/25 bg-primary/10 shadow-[0_0_45px_hsl(var(--primary)/0.12)]">
                <Search className="h-7 w-7 text-primary" />
              </div>
              <p className="font-mono text-[11px] uppercase tracking-[0.24em] text-primary">Research intelligence</p>
              <h1 className="mt-2 text-4xl font-semibold tracking-[-0.045em] sm:text-5xl lg:text-6xl">Analysis</h1>
              <p className="mt-4 max-w-3xl text-base leading-7 text-muted-foreground">
                Ask about a company, sector, portfolio, document, market, or investment question. Analysis assembles the right evidence and specialists, then returns a transparent research view—not just a trade idea.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <Link to="/" className="group rounded-2xl border bg-background/45 p-4 transition hover:border-primary/35 hover:bg-primary/5">
                <LayoutDashboard className="h-5 w-5 text-primary" />
                <p className="mt-5 text-sm font-semibold">Research dashboard</p>
                <p className="mt-1 text-[11px] leading-4 text-muted-foreground">Markets, leaders, and launch controls</p>
                <ArrowRight className="mt-4 h-4 w-4 text-muted-foreground transition group-hover:translate-x-1 group-hover:text-primary" />
              </Link>
              <Link to="/reports" className="group rounded-2xl border bg-background/45 p-4 transition hover:border-primary/35 hover:bg-primary/5">
                <Files className="h-5 w-5 text-primary" />
                <p className="mt-5 text-sm font-semibold">Research archive</p>
                <p className="mt-1 text-[11px] leading-4 text-muted-foreground">Reports, runs, and evidence history</p>
                <ArrowRight className="mt-4 h-4 w-4 text-muted-foreground transition group-hover:translate-x-1 group-hover:text-primary" />
              </Link>
            </div>
          </div>

          <div className="mt-8 flex flex-wrap gap-2 border-t border-border/70 pt-5">
            {CAPABILITIES.map((capability) => (
              <span key={capability} className="rounded-full border bg-background/40 px-3 py-1.5 text-[10px] font-medium text-muted-foreground">
                {capability}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className="terminal-card rounded-[24px] border bg-card/65 p-4 sm:p-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-primary">
              <Sparkles className="h-4 w-4" />
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em]">Choose a research mode</p>
            </div>
            <h2 className="mt-1.5 text-2xl font-semibold tracking-tight">How do you want to work?</h2>
            <p className="mt-1 text-sm text-muted-foreground">Pick a starting structure, then make the conversation your own.</p>
          </div>
          <span className="font-mono text-[10px] text-muted-foreground">6 flexible workspaces</span>
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {RESEARCH_MODES.map((mode) => (
            <button
              key={mode.title}
              type="button"
              onClick={() => onExample(mode.prompt)}
              className="group min-h-[180px] rounded-2xl border bg-background/35 p-4 text-left transition hover:-translate-y-0.5 hover:border-primary/30 hover:bg-primary/[0.04]"
            >
              <div className="flex items-start justify-between gap-3">
                <span className={`grid h-10 w-10 place-items-center rounded-xl border ${mode.tone}`}>{mode.icon}</span>
                <ArrowRight className="h-4 w-4 text-muted-foreground transition group-hover:translate-x-1 group-hover:text-primary" />
              </div>
              <p className="mt-5 font-mono text-[9px] uppercase tracking-[0.16em] text-muted-foreground">{mode.eyebrow}</p>
              <h3 className="mt-1 text-base font-semibold">{mode.title}</h3>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">{mode.description}</p>
            </button>
          ))}
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-3">
        {[
          { number: "01", title: "Ask freely", text: "Start with a question, ticker, file, portfolio, or research objective.", icon: <Search className="h-4 w-4" /> },
          { number: "02", title: "Choose the team", text: "Work with one analyst, an investment committee, or a parallel swarm.", icon: <Users className="h-4 w-4" /> },
          { number: "03", title: "Audit the answer", text: "Inspect evidence, calculations, validation, reports, and unresolved gaps.", icon: <ShieldCheck className="h-4 w-4" /> },
        ].map((item) => (
          <div key={item.number} className="rounded-2xl border bg-card/45 p-4">
            <div className="flex items-center justify-between text-primary">
              {item.icon}
              <span className="font-mono text-[9px] text-muted-foreground">{item.number}</span>
            </div>
            <p className="mt-4 text-sm font-semibold">{item.title}</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">{item.text}</p>
          </div>
        ))}
      </section>

      <div className="flex items-center justify-center gap-2 py-2 text-[10px] text-muted-foreground">
        <BarChart3 className="h-3.5 w-3.5" /> Strategy and trading tools remain available inside Strategy Lab when your research calls for them.
      </div>
    </div>
  );
}
