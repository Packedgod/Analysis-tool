import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import { Activity, BarChart3, BookOpen, BrainCircuit, Calculator, CandlestickChart, FlaskConical, Gauge, Layers3, Loader2, Network, Play, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { api, type QuantLabResult } from "@/lib/api";
import { cn } from "@/lib/utils";

type Field = { key: string; label: string; type?: "number" | "select"; options?: string[] };
type Lab = { id: string; name: string; eyebrow: string; description: string; icon: typeof Activity; fields: Field[]; defaults: Record<string, string | number> };

const LABS: Lab[] = [
  { id:"backtest",name:"Backtesting Engine",eyebrow:"Strategy validation",description:"Run a strategy on observed history with fees, next-bar execution, Sharpe, drawdown, win rate, and an equity curve.",icon:BarChart3,fields:[{key:"ticker",label:"Ticker"},{key:"period",label:"History",type:"select",options:["1y","2y","5y","10y"]},{key:"strategy",label:"Strategy",type:"select",options:["moving_average","rsi","buy_hold"]},{key:"fast",label:"Fast window",type:"number"},{key:"slow",label:"Slow window",type:"number"},{key:"fee_bps",label:"Fee (bps)",type:"number"}],defaults:{ticker:"SPY",period:"5y",strategy:"moving_average",fast:20,slow:50,fee_bps:5,initial_cash:100000}},
  { id:"pairs",name:"Pairs Trading",eyebrow:"Statistical arbitrage",description:"Estimate a hedge ratio, monitor the spread z-score, and test mean-reversion with explicit cointegration evidence.",icon:Network,fields:[{key:"ticker_a",label:"Ticker A"},{key:"ticker_b",label:"Ticker B"},{key:"period",label:"History",type:"select",options:["1y","2y","5y","10y"]},{key:"lookback",label:"Z-score lookback",type:"number"},{key:"entry_z",label:"Entry z",type:"number"},{key:"exit_z",label:"Exit z",type:"number"}],defaults:{ticker_a:"KO",ticker_b:"PEP",period:"5y",lookback:60,entry_z:2,exit_z:.5}},
  { id:"options",name:"Options Pricing",eyebrow:"Derivatives lab",description:"Black–Scholes from first principles, live input comparison, Greeks, and spot sensitivity curves.",icon:Calculator,fields:[{key:"spot",label:"Spot",type:"number"},{key:"strike",label:"Strike",type:"number"},{key:"expiry_days",label:"Days to expiry",type:"number"},{key:"volatility",label:"Volatility",type:"number"},{key:"risk_free_rate",label:"Risk-free rate",type:"number"},{key:"option_type",label:"Type",type:"select",options:["call","put"]},{key:"market_price",label:"Market price",type:"number"}],defaults:{spot:100,strike:100,expiry_days:30,volatility:.25,risk_free_rate:.05,option_type:"call",market_price:3}},
  { id:"order-book",name:"Order Book Simulator",eyebrow:"Market microstructure",description:"Process seeded market orders against bid and ask price levels and inspect spread, depth, and fills.",icon:BookOpen,fields:[{key:"mid_price",label:"Mid price",type:"number"},{key:"levels",label:"Book levels",type:"number"},{key:"events",label:"Market orders",type:"number"},{key:"seed",label:"Seed",type:"number"}],defaults:{mid_price:100,levels:10,events:100,seed:42}},
  { id:"sentiment",name:"Sentiment Correlation",eyebrow:"News intelligence",description:"Score current financial headlines with an auditable lexicon and expose the actual underlying headlines.",icon:BrainCircuit,fields:[{key:"ticker",label:"Ticker"},{key:"limit",label:"Headlines",type:"number"}],defaults:{ticker:"AAPL",limit:30}},
  { id:"portfolio",name:"Portfolio Optimizer",eyebrow:"Capital allocation",description:"Long-only Markowitz optimization with allocations, expected risk/return, Sharpe, and an efficient frontier.",icon:Gauge,fields:[{key:"tickers",label:"Tickers (comma separated)"},{key:"period",label:"History",type:"select",options:["1y","3y","5y","10y"]},{key:"risk_free_rate",label:"Risk-free rate",type:"number"}],defaults:{tickers:"AAPL,MSFT,GOOGL,AMZN",period:"3y",risk_free_rate:.04}},
  { id:"monte-carlo",name:"Monte Carlo",eyebrow:"Risk simulation",description:"Generate thousands of seeded portfolio paths and inspect terminal distribution, VaR, CVaR, and loss probability.",icon:FlaskConical,fields:[{key:"ticker",label:"Ticker"},{key:"period",label:"Calibration history",type:"select",options:["1y","3y","5y","10y"]},{key:"horizon_days",label:"Horizon days",type:"number"},{key:"simulations",label:"Simulations",type:"number"},{key:"initial_value",label:"Initial value",type:"number"},{key:"seed",label:"Seed",type:"number"}],defaults:{ticker:"SPY",period:"3y",horizon_days:252,simulations:2500,initial_value:100000,seed:42}},
  { id:"volatility-surface",name:"Volatility Surface",eyebrow:"Options market",description:"Pull an observed option chain and map implied volatility across strikes and expirations.",icon:Layers3,fields:[{key:"ticker",label:"Ticker"},{key:"max_expirations",label:"Expirations",type:"number"}],defaults:{ticker:"SPY",max_expirations:6}},
  { id:"factor-model",name:"Factor Model",eyebrow:"Return attribution",description:"Decompose returns into market, size, and value exposures and separate factor loading from annualized alpha.",icon:Activity,fields:[{key:"ticker",label:"Ticker"},{key:"period",label:"History",type:"select",options:["1y","3y","5y","10y"]}],defaults:{ticker:"AAPL",period:"5y"}},
  { id:"market-dashboard",name:"Market Dashboard",eyebrow:"Observed market data",description:"Interactive OHLCV, volume, and moving averages sourced from the current market feed.",icon:CandlestickChart,fields:[{key:"tickers",label:"Tickers (comma separated)"},{key:"period",label:"History",type:"select",options:["1mo","3mo","6mo","1y"]}],defaults:{tickers:"SPY,QQQ,AAPL",period:"6mo"}},
];

function normalizePayload(values: Record<string,string|number>) {
  return Object.fromEntries(Object.entries(values).map(([key,value]) => [key, key === "tickers" ? String(value).split(",").map(x=>x.trim()).filter(Boolean) : value]));
}
function formatMetric(value: number|string|null) {
  if (value === null) return "Unavailable";
  if (typeof value !== "number") return String(value);
  if (Math.abs(value) > 1000) return value.toLocaleString(undefined,{maximumFractionDigits:2});
  return value.toLocaleString(undefined,{maximumFractionDigits:4});
}

type MarketChartMode = "single" | "compare";
type MarketChartContext = { mode?: MarketChartMode; ticker?: string };
type ChartSpec = { option: echarts.EChartsOption; legends: Array<{ name: string; color: string }> };
const MARKET_COLORS = ["#a3e635", "#38bdf8", "#a78bfa", "#fb7185", "#f59e0b", "#2dd4bf"];

export function marketTickers(result: QuantLabResult): string[] {
  return [...new Set((result.series ?? []).map((row) => String(row.ticker ?? "")).filter(Boolean))];
}

export function indexedMarketSeries(result: QuantLabResult): {
  dates: string[];
  series: Array<{ ticker: string; data: Array<number | null> }>;
} {
  const rows = result.series ?? [];
  const tickers = marketTickers(result);
  const dates = [...new Set(rows.map((row) => String(row.date ?? "").slice(0, 10)).filter(Boolean))].sort();
  return {
    dates,
    series: tickers.map((ticker) => {
      const tickerRows = rows.filter((row) => String(row.ticker ?? "") === ticker);
      const firstClose = tickerRows.map((row) => Number(row.close)).find((value) => Number.isFinite(value) && value !== 0);
      const byDate = new Map(tickerRows.map((row) => [String(row.date ?? "").slice(0, 10), Number(row.close)]));
      return {
        ticker,
        data: dates.map((date) => {
          const close = byDate.get(date);
          return firstClose && close != null && Number.isFinite(close)
            ? Number(((close / firstClose) * 100).toFixed(4))
            : null;
        }),
      };
    }),
  };
}

export function buildChartSpec(result: QuantLabResult, market: MarketChartContext = {}): ChartSpec {
  const rows = result.series ?? [];
  const tickers = marketTickers(result);
  if (result.kind !== "market_dashboard") return { option: { series: [] }, legends: [] };
  if (market.mode === "compare" && tickers.length > 1) {
    const indexed = indexedMarketSeries(result);
    const legends = tickers.map((name, index) => ({ name, color: MARKET_COLORS[index % MARKET_COLORS.length] }));
    return {
      legends,
      option: {
        grid: { left: 56, right: 24, top: 64, bottom: 46 },
        legend: { type: "scroll", top: 4, data: tickers, textStyle: { color: "#7c879d" } },
        xAxis: { type: "category", data: indexed.dates },
        yAxis: { scale: true, type: "value", name: "Indexed (100)", splitLine: { lineStyle: { color: "rgba(100,116,139,.15)" } } },
        dataZoom: [{ type: "inside", filterMode: "none" }],
        series: indexed.series.map((item, index) => ({ type: "line", name: item.ticker, data: item.data, showSymbol: false, connectNulls: false, sampling: "lttb", lineStyle: { color: MARKET_COLORS[index % MARKET_COLORS.length], width: 2 } })),
      },
    };
  }
  const ticker = market.ticker && tickers.includes(market.ticker) ? market.ticker : (tickers[0] || "");
  const selected = rows.filter((row) => String(row.ticker) === ticker);
  const legends = [{ name: ticker, color: "#22c55e" }, { name: "MA20", color: MARKET_COLORS[0] }, { name: "MA50", color: MARKET_COLORS[1] }];
  return {
    legends,
    option: {
      grid: { left: 56, right: 24, top: 64, bottom: 46 },
      legend: { type: "scroll", top: 4, data: legends.map((item) => item.name), textStyle: { color: "#7c879d" } },
      xAxis: { type: "category", data: selected.map((row) => String(row.date).slice(0, 10)) },
      yAxis: { scale: true, type: "value", splitLine: { lineStyle: { color: "rgba(100,116,139,.15)" } } },
      dataZoom: [{ type: "inside", filterMode: "none" }],
      series: [
        { type: "candlestick", name: ticker, data: selected.map((row) => [Number(row.open), Number(row.close), Number(row.low), Number(row.high)]), itemStyle: { color: "#22c55e", color0: "#ef4444" } },
        { type: "line", name: "MA20", data: selected.map((row) => row.ma20 == null ? null : Number(row.ma20)), showSymbol: false, lineStyle: { color: MARKET_COLORS[0] } },
        { type: "line", name: "MA50", data: selected.map((row) => row.ma50 == null ? null : Number(row.ma50)), showSymbol: false, lineStyle: { color: MARKET_COLORS[1] } },
      ],
    },
  };
}

function ResultChart({result, marketMode="single", marketTicker}:{result:QuantLabResult; marketMode?:MarketChartMode; marketTicker?:string}) {
  const ref=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!ref.current) return;
    const chart=echarts.init(ref.current); const primary=getComputedStyle(document.documentElement).getPropertyValue("--primary").trim(); const accent=`hsl(${primary})`; const muted="#7c879d";
    let option:any={animationDuration:450,tooltip:{trigger:"axis"},grid:{left:56,right:24,top:34,bottom:46},textStyle:{fontFamily:"Inter",color:muted},xAxis:{type:"category",axisLine:{lineStyle:{color:"#334155"}}},yAxis:{type:"value",splitLine:{lineStyle:{color:"rgba(100,116,139,.15)"}}},series:[]};
    const rows=result.series||[];
    if(result.kind==="backtest") option={...option,xAxis:{type:"category",data:rows.map(x=>String(x.date).slice(0,10))},series:[{type:"line",name:"Equity",data:rows.map(x=>x.equity),showSymbol:false,smooth:true,lineStyle:{color:accent,width:2},areaStyle:{color:"rgba(163,230,53,.08)"}}]};
    else if(result.kind==="pairs") option={...option,xAxis:{type:"category",data:rows.map(x=>String(x.date).slice(0,10))},series:[{type:"line",name:"Z-score",data:rows.map(x=>x.zscore),showSymbol:false,lineStyle:{color:accent}},{type:"line",name:"Position",data:rows.map(x=>x.position),showSymbol:false,lineStyle:{color:"#a78bfa"}}]};
    else if(result.kind==="options") option={...option,xAxis:{type:"value",name:"Spot"},yAxis:[{type:"value",name:"Price"},{type:"value",name:"Delta",min:0,max:1}],series:[{type:"line",name:"Option value",data:rows.map(x=>[x.spot,x.price]),showSymbol:false,lineStyle:{color:accent,width:2}},{type:"line",name:"Delta",data:rows.map(x=>[x.spot,x.delta]),yAxisIndex:1,showSymbol:false,lineStyle:{color:"#38bdf8"}}]};
    else if(result.kind==="order_book") { const bids=result.bids||[],asks=result.asks||[]; option={...option,xAxis:{type:"value",name:"Quantity"},yAxis:{type:"category",data:[...bids,...asks].map(x=>String(x.price))},series:[{type:"bar",data:[...bids.map(x=>-x.quantity),...asks.map(x=>x.quantity)],itemStyle:{color:(p:any)=>p.value<0?"#22c55e":"#ef4444"}}]}; }
    else if(result.kind==="portfolio") option={...option,xAxis:{type:"value",name:"Risk"},yAxis:{type:"value",name:"Return"},series:[{type:"scatter",data:(result.frontier||[]).map(x=>[x.risk,x.return]),symbolSize:8,itemStyle:{color:accent}}]};
    else if(result.kind==="monte_carlo") {const h=result.histogram||[];option={...option,xAxis:{type:"category",data:h.map(x=>Number(x.from).toFixed(0))},series:[{type:"bar",data:h.map(x=>x.count),itemStyle:{color:accent}}]};}
    else if(result.kind==="volatility_surface") {const p=result.points||[]; const ex=[...new Set(p.map(x=>String(x.expiry)))]; option={...option,tooltip:{trigger:"item"},xAxis:{type:"category",data:ex,name:"Expiry"},yAxis:{type:"value",name:"Strike"},visualMap:{min:0,max:1,dimension:2,orient:"horizontal",left:"center",bottom:0,inRange:{color:["#172554","#38bdf8","#a3e635","#f59e0b"]}},series:[{type:"scatter",data:p.map(x=>[String(x.expiry),x.strike,x.implied_volatility]),symbolSize:9}]};}
    else if(result.kind==="factor_model") option={...option,xAxis:{type:"category",data:rows.map(x=>String(x.date).slice(0,10))},series:[{type:"line",name:"Actual",data:rows.map(x=>x.actual),showSymbol:false,lineStyle:{color:accent}},{type:"line",name:"Factor fitted",data:rows.map(x=>x.fitted),showSymbol:false,lineStyle:{color:"#38bdf8"}}]};
    else if(result.kind==="market_dashboard") {
      option={...option,...buildChartSpec(result,{mode:marketMode,ticker:marketTicker}).option};
    }
    else option={...option,series:[{type:"bar",data:Object.values(result.metrics||{}).filter(x=>typeof x==="number") as number[],itemStyle:{color:accent}}]};
    chart.setOption(option); const resize=()=>chart.resize(); window.addEventListener("resize",resize); return()=>{window.removeEventListener("resize",resize);chart.dispose()};
  },[result,marketMode,marketTicker]);
  return <div ref={ref} className="h-[360px] w-full" aria-label={`${result.kind} interactive chart`} />;
}

export function QuantLabs(){
  const [activeId,setActiveId]=useState("backtest"); const active=useMemo(()=>LABS.find(x=>x.id===activeId)!,[activeId]); const ActiveIcon = active.icon;
  const [values,setValues]=useState<Record<string,string|number>>(active.defaults); const [result,setResult]=useState<QuantLabResult|null>(null); const [loading,setLoading]=useState(false);
  const [marketMode,setMarketMode]=useState<MarketChartMode>("single"); const [marketTicker,setMarketTicker]=useState("");
  const resultTickers=useMemo(()=>result?.kind==="market_dashboard"?marketTickers(result):[],[result]);
  useEffect(()=>{setValues(active.defaults);setResult(null);setMarketMode("single");setMarketTicker("")},[active]);
  useEffect(()=>{if(resultTickers.length&&!resultTickers.includes(marketTicker))setMarketTicker(resultTickers[0])},[resultTickers,marketTicker]);
  useEffect(()=>{ if(activeId!=="market-dashboard") return; const timer=window.setInterval(()=>void run(),60000); return()=>window.clearInterval(timer)},[activeId,values]);
  async function run(){setLoading(true);try{setResult(await api.runQuantLab(active.id,normalizePayload(values)));}catch(e){toast.error(e instanceof Error?e.message:"Lab failed")}finally{setLoading(false)}}
  return <div className="h-full overflow-y-auto bg-background"><div className="mx-auto max-w-[1540px] px-5 py-7 lg:px-8">
    <header className="terminal-card market-grid relative overflow-hidden rounded-[24px] border p-6 lg:p-8"><div className="relative z-10 max-w-4xl"><div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[.24em] text-primary"><FlaskConical className="h-4 w-4"/>Quantitative research system</div><h1 className="mt-4 text-4xl font-bold tracking-tight lg:text-6xl">Quant Labs</h1><p className="mt-4 max-w-3xl text-base leading-7 text-muted-foreground">Ten evidence-labelled engines in one workspace. Observed market data stays distinct from seeded simulations, and every result records its source, timestamp, methodology, and caveats.</p><div className="mt-5 flex flex-wrap gap-2"><span className="rounded-full border border-success/25 bg-success/10 px-3 py-1 font-mono text-[10px] text-success">OBSERVED DATA LABELS</span><span className="rounded-full border border-primary/25 bg-primary/10 px-3 py-1 font-mono text-[10px] text-primary">REPRODUCIBLE PARAMETERS</span><span className="rounded-full border px-3 py-1 font-mono text-[10px] text-muted-foreground">NO FABRICATED FALLBACKS</span></div></div></header>
    <section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{LABS.map(l=>{const Icon=l.icon;return <button key={l.id} onClick={()=>setActiveId(l.id)} className={cn("rounded-2xl border p-4 text-left transition-all",activeId===l.id?"border-primary/40 bg-primary/10 shadow-[0_0_30px_hsl(var(--primary)/0.08)]":"bg-card/70 hover:border-primary/25 hover:bg-card")}><Icon className={cn("h-5 w-5",activeId===l.id?"text-primary":"text-muted-foreground")}/><div className="mt-3 text-sm font-semibold">{l.name}</div><div className="mt-1 font-mono text-[9px] uppercase tracking-wider text-muted-foreground">{l.eyebrow}</div></button>})}</section>
    <section className="mt-6 grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]"><aside className="terminal-card h-fit rounded-[22px] border p-5 xl:sticky xl:top-5"><div className="font-mono text-[10px] uppercase tracking-[.2em] text-primary">Configure engine</div><h2 className="mt-2 text-xl font-semibold">{active.name}</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">{active.description}</p><div className="mt-5 space-y-3">{active.fields.map(f=><label key={f.key} className="block"><span className="mb-1.5 block text-xs text-muted-foreground">{f.label}</span>{f.type==="select"?<select value={values[f.key]} onChange={e=>setValues(v=>({...v,[f.key]:e.target.value}))} className="h-10 w-full rounded-xl border bg-background px-3 text-sm">{f.options?.map(o=><option key={o}>{o}</option>)}</select>:<input type={f.type==="number"?"number":"text"} step="any" value={values[f.key]??""} onChange={e=>setValues(v=>({...v,[f.key]:f.type==="number"?Number(e.target.value):e.target.value}))} className="h-10 w-full rounded-xl border bg-background px-3 text-sm outline-none focus:border-primary/50"/>}</label>)}</div><button onClick={()=>void run()} disabled={loading} className="mt-5 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-primary font-semibold text-primary-foreground transition hover:brightness-110 disabled:opacity-60">{loading?<Loader2 className="h-4 w-4 animate-spin"/>:<Play className="h-4 w-4 fill-current"/>}{loading?"Running evidence pipeline…":"Run analysis"}</button></aside>
      <main className="min-w-0 space-y-5">{!result?<div className="terminal-card grid min-h-[560px] place-items-center rounded-[22px] border p-8 text-center"><div><ActiveIcon className="mx-auto h-12 w-12 text-primary"/><h3 className="mt-4 text-xl font-semibold">Ready to run {active.name}</h3><p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-muted-foreground">Configure the evidence window and model assumptions. Results and interactive visualizations will appear here without using the language model.</p></div></div>:<><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{Object.entries({...result.metrics,...(result.comparison||{})}).map(([key,value])=><article key={key} className="terminal-card rounded-2xl border p-4"><div className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">{key.replace(/_/g," ")}</div><div className="mt-2 text-xl font-semibold tabular-nums">{formatMetric(value)}</div></article>)}</div><div className="terminal-card rounded-[22px] border p-4 lg:p-6"><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="font-mono text-[10px] uppercase tracking-[.18em] text-primary">Interactive result</div><h3 className="mt-1 font-semibold">{active.name} visualization</h3></div><span className={cn("rounded-full border px-3 py-1 font-mono text-[9px] uppercase",result.evidence.data_class==="observed"?"border-success/30 bg-success/10 text-success":"border-warning/30 bg-warning/10 text-warning")}>{result.evidence.data_class}</span></div>{result.kind==="market_dashboard"&&resultTickers.length>1&&<div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-4"><div className="flex rounded-xl border bg-background/70 p-1"><button onClick={()=>setMarketMode("single")} className={cn("rounded-lg px-3 py-1.5 text-xs transition",marketMode==="single"?"bg-primary text-primary-foreground":"text-muted-foreground hover:text-foreground")}>Single</button><button onClick={()=>setMarketMode("compare")} className={cn("rounded-lg px-3 py-1.5 text-xs transition",marketMode==="compare"?"bg-primary text-primary-foreground":"text-muted-foreground hover:text-foreground")}>Compare all</button></div>{marketMode==="single"&&<div className="flex flex-wrap gap-1.5">{resultTickers.map(ticker=><button key={ticker} onClick={()=>setMarketTicker(ticker)} className={cn("rounded-full border px-3 py-1.5 font-mono text-[10px] transition",marketTicker===ticker?"border-primary/50 bg-primary/10 text-primary":"text-muted-foreground hover:border-primary/30 hover:text-foreground")}>{ticker}</button>)}</div>}<span className="ml-auto text-[10px] text-muted-foreground">Compare mode indexes every series to 100.</span></div>}<ResultChart result={result} marketMode={marketMode} marketTicker={marketTicker}/></div>{result.weights&&<div className="terminal-card rounded-[22px] border p-5"><h3 className="font-semibold">Optimal allocation</h3><div className="mt-4 space-y-3">{result.weights.map(w=><div key={w.ticker}><div className="mb-1 flex justify-between text-xs"><span>{w.ticker}</span><span>{(w.weight*100).toFixed(2)}%</span></div><div className="h-2 rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{width:`${w.weight*100}%`}}/></div></div>)}</div></div>}{result.headlines&&<div className="terminal-card rounded-[22px] border p-5"><h3 className="font-semibold">Source headlines</h3><div className="mt-3 divide-y">{result.headlines.map((h,i)=><div key={i} className="grid gap-2 py-3 sm:grid-cols-[1fr_auto]"><span className="text-sm">{String(h.title)}</span><span className={cn("font-mono text-xs",Number(h.score)>0?"text-success":Number(h.score)<0?"text-danger":"text-muted-foreground")}>{Number(h.score).toFixed(2)}</span></div>)}</div></div>}<div className="terminal-card rounded-[22px] border p-5"><div className="flex items-start gap-3"><ShieldCheck className="mt-0.5 h-5 w-5 text-primary"/><div><div className="font-semibold">Evidence record</div><div className="mt-2 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2"><span>Source: <b className="text-foreground">{result.evidence.source}</b></span><span>As of: <b className="text-foreground">{new Date(result.evidence.observed_at).toLocaleString()}</b></span></div><p className="mt-3 text-sm leading-6 text-muted-foreground">{result.evidence.method}</p>{result.evidence.caveats.length>0&&<ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-warning">{result.evidence.caveats.map(c=><li key={c}>{c}</li>)}</ul>}</div></div></div></>}</main>
    </section></div></div>;
}
