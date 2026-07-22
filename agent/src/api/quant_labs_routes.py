"""Evidence-labelled quantitative research labs exposed to the local UI.

The module deliberately separates observed market data from simulations. Every
response includes source, as-of time, methodology, and caveats so generated
paths can never be mistaken for observed prices.
"""

from __future__ import annotations

import io
import math
import random
import zipfile
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from scipy.optimize import minimize
from scipy.stats import norm


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence(source: str, method: str, *, observed: bool = True, caveats: list[str] | None = None) -> dict[str, Any]:
    return {"source": source, "observed_at": _now(), "method": method, "data_class": "observed" if observed else "simulation", "caveats": caveats or []}


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _history(tickers: list[str], period: str = "2y", interval: str = "1d") -> dict[str, pd.DataFrame]:
    import yfinance as yf

    names = [t.strip().upper() for t in tickers if t.strip()]
    if not names or len(names) > 20:
        raise ValueError("Provide between 1 and 20 tickers")
    raw = yf.download(names, period=period, interval=interval, auto_adjust=True, progress=False, threads=True, timeout=12)
    if raw.empty:
        raise ValueError("Yahoo Finance returned no market data")
    result: dict[str, pd.DataFrame] = {}
    for symbol in names:
        frame = raw.xs(symbol, axis=1, level=1, drop_level=True) if isinstance(raw.columns, pd.MultiIndex) else raw.copy()
        frame = frame.rename(columns={str(c): str(c).title() for c in frame.columns}).dropna(how="all")
        if "Close" in frame and len(frame) >= 10:
            result[symbol] = frame
    if not result:
        raise ValueError("No ticker had enough valid historical observations")
    return result


def _series_rows(series: pd.Series, name: str = "value", limit: int = 700) -> list[dict[str, Any]]:
    tail = series.dropna().iloc[-limit:]
    return [{"date": pd.Timestamp(idx).isoformat(), name: round(float(value), 6)} for idx, value in tail.items()]


class BacktestRequest(BaseModel):
    ticker: str = "SPY"
    period: str = "5y"
    strategy: str = "moving_average"
    fast: int = Field(20, ge=2, le=200)
    slow: int = Field(50, ge=3, le=400)
    initial_cash: float = Field(100000, gt=0)
    fee_bps: float = Field(5, ge=0, le=500)


class PairsRequest(BaseModel):
    ticker_a: str = "KO"
    ticker_b: str = "PEP"
    period: str = "5y"
    lookback: int = Field(60, ge=20, le=252)
    entry_z: float = Field(2.0, gt=0.5, le=5)
    exit_z: float = Field(0.5, ge=0, le=2)


class OptionsRequest(BaseModel):
    spot: float = Field(100, gt=0)
    strike: float = Field(100, gt=0)
    expiry_days: float = Field(30, ge=0)
    volatility: float = Field(0.25, gt=0, le=5)
    risk_free_rate: float = Field(0.05, ge=-0.2, le=1)
    option_type: str = "call"
    market_price: float | None = Field(None, ge=0)


class OrderBookRequest(BaseModel):
    mid_price: float = Field(100, gt=0)
    levels: int = Field(8, ge=3, le=30)
    events: int = Field(80, ge=10, le=500)
    seed: int = 42


class TickersRequest(BaseModel):
    tickers: list[str] = ["AAPL", "MSFT", "GOOGL", "AMZN"]
    period: str = "3y"


class PortfolioRequest(TickersRequest):
    target_return: float | None = Field(None, ge=-1, le=5)
    risk_free_rate: float = Field(0.04, ge=-0.2, le=1)


class MonteCarloRequest(BaseModel):
    ticker: str = "SPY"
    period: str = "3y"
    horizon_days: int = Field(252, ge=5, le=1260)
    simulations: int = Field(2500, ge=100, le=20000)
    initial_value: float = Field(100000, gt=0)
    seed: int = 42


class SurfaceRequest(BaseModel):
    ticker: str = "SPY"
    max_expirations: int = Field(6, ge=1, le=12)


class SentimentRequest(BaseModel):
    ticker: str = "AAPL"
    limit: int = Field(30, ge=5, le=100)


class FactorRequest(BaseModel):
    ticker: str = "AAPL"
    period: str = "5y"


def _backtest(req: BacktestRequest) -> dict[str, Any]:
    frame = _history([req.ticker], req.period)[req.ticker.upper()]
    close = frame["Close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    if req.strategy == "buy_hold":
        signal = pd.Series(1.0, index=close.index)
    elif req.strategy == "rsi":
        delta = close.diff(); gain = delta.clip(lower=0).rolling(14).mean(); loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
        signal = pd.Series(np.where(rsi < 35, 1.0, np.where(rsi > 65, 0.0, np.nan)), index=close.index).ffill().fillna(0.0)
    else:
        if req.fast >= req.slow:
            raise ValueError("Fast window must be smaller than slow window")
        signal = (close.rolling(req.fast).mean() > close.rolling(req.slow).mean()).astype(float)
    turnover = signal.diff().abs().fillna(signal.abs())
    strategy_returns = signal.shift(1).fillna(0) * returns - turnover * req.fee_bps / 10000
    equity = req.initial_cash * (1 + strategy_returns).cumprod()
    drawdown = equity / equity.cummax() - 1
    vol = float(strategy_returns.std())
    sharpe = float(strategy_returns.mean() / vol * np.sqrt(252)) if vol > 0 else 0.0
    entries = signal.diff().fillna(signal).eq(1)
    exits = signal.diff().eq(-1)
    entry_prices = close[entries].tolist(); exit_prices = close[exits].tolist()
    if len(entry_prices) > len(exit_prices): exit_prices.append(float(close.iloc[-1]))
    pnls = [(b / a - 1) for a, b in zip(entry_prices, exit_prices) if a > 0]
    metrics = {"total_return": float(equity.iloc[-1] / req.initial_cash - 1), "sharpe_ratio": sharpe, "max_drawdown": float(drawdown.min()), "win_rate": float(sum(p > 0 for p in pnls) / len(pnls)) if pnls else 0.0, "trades": len(pnls), "annual_volatility": vol * np.sqrt(252)}
    return {"kind":"backtest", "ticker":req.ticker.upper(), "strategy":req.strategy, "metrics":_clean(metrics), "series":_series_rows(equity, "equity"), "price":_series_rows(close, "price"), "evidence":_evidence("Yahoo Finance", f"Close-to-close {req.strategy} backtest; signal shifted one bar; {req.fee_bps:g} bps turnover cost")}


def _pairs(req: PairsRequest) -> dict[str, Any]:
    data = _history([req.ticker_a, req.ticker_b], req.period)
    a, b = req.ticker_a.upper(), req.ticker_b.upper()
    prices = pd.concat([data[a]["Close"], data[b]["Close"]], axis=1, keys=[a,b]).dropna()
    loga, logb = np.log(prices[a]), np.log(prices[b])
    beta, intercept = np.polyfit(logb, loga, 1)
    spread = loga - (intercept + beta * logb)
    mean = spread.rolling(req.lookback).mean(); std = spread.rolling(req.lookback).std(); z = (spread - mean) / std
    position = pd.Series(np.where(z > req.entry_z, -1, np.where(z < -req.entry_z, 1, np.nan)), index=z.index)
    position = position.mask(z.abs() < req.exit_z, 0).ffill().fillna(0)
    spread_ret = prices[a].pct_change() - beta * prices[b].pct_change()
    pnl = position.shift(1).fillna(0) * spread_ret.fillna(0); equity = (1+pnl).cumprod()
    try:
        from statsmodels.tsa.stattools import coint
        coint_p = float(coint(loga, logb)[1])
    except Exception:
        coint_p = None
    metrics = {"correlation": float(prices.pct_change().corr().iloc[0,1]), "hedge_ratio": float(beta), "cointegration_p_value": coint_p, "sharpe_ratio": float(pnl.mean()/pnl.std()*np.sqrt(252)) if pnl.std()>0 else 0, "max_drawdown": float((equity/equity.cummax()-1).min()), "spread_return":float(equity.iloc[-1]-1)}
    rows=[{"date":pd.Timestamp(i).isoformat(),"zscore":_clean(float(zv)),"spread":_clean(float(sv)),"position":int(pv)} for i,zv,sv,pv in zip(z.index[-700:],z.iloc[-700:],spread.iloc[-700:],position.iloc[-700:])]
    return {"kind":"pairs", "pair":[a,b], "metrics":_clean(metrics), "series":rows, "evidence":_evidence("Yahoo Finance", f"Log-price OLS hedge ratio; {req.lookback}-bar rolling z-score; next-bar spread returns", caveats=[] if coint_p is not None else ["statsmodels unavailable: cointegration p-value omitted"])}


def _options(req: OptionsRequest) -> dict[str, Any]:
    from src.tools.options_pricing_tool import _bs_price_and_greeks
    if req.option_type not in {"call","put"}: raise ValueError("option_type must be call or put")
    result=_bs_price_and_greeks(req.spot,req.strike,req.expiry_days/365,req.risk_free_rate,req.volatility,req.option_type)
    comparison=None if req.market_price is None else {"market_price":req.market_price,"model_difference":result["price"]-req.market_price,"model_difference_percent":(result["price"]/req.market_price-1)*100 if req.market_price else None}
    curve=[]
    for spot in np.linspace(req.spot*.65,req.spot*1.35,80):
        curve.append({"spot":round(float(spot),4),**_bs_price_and_greeks(float(spot),req.strike,req.expiry_days/365,req.risk_free_rate,req.volatility,req.option_type)})
    return {"kind":"options","metrics":result,"comparison":_clean(comparison),"series":curve,"evidence":_evidence("User inputs", "Black-Scholes closed-form price and analytic Greeks", observed=False, caveats=["Model assumes constant volatility and frictionless European exercise"])}


def _order_book(req: OrderBookRequest) -> dict[str, Any]:
    rng=random.Random(req.seed); tick=max(round(req.mid_price*.0005,2),.01)
    bids={round(req.mid_price-tick*(i+1),2):rng.randint(20,200) for i in range(req.levels)}
    asks={round(req.mid_price+tick*(i+1),2):rng.randint(20,200) for i in range(req.levels)}
    trades=[]
    for n in range(req.events):
        side="buy" if rng.random()>.5 else "sell"; qty=rng.randint(1,50)
        book=asks if side=="buy" else bids
        price=min(book) if side=="buy" else max(book); filled=min(qty,book[price]); book[price]-=filled
        if book[price]<=0: del book[price]
        if not book:
            price=round(req.mid_price+(tick if side=="buy" else -tick),2); book[price]=rng.randint(40,180)
        trades.append({"sequence":n+1,"side":side,"price":price,"quantity":filled})
    bid_rows=[{"price":p,"quantity":q} for p,q in sorted(bids.items(),reverse=True)]; ask_rows=[{"price":p,"quantity":q} for p,q in sorted(asks.items())]
    best_bid=bid_rows[0]["price"]; best_ask=ask_rows[0]["price"]
    return {"kind":"order_book","metrics":{"best_bid":best_bid,"best_ask":best_ask,"spread":best_ask-best_bid,"trades_processed":len(trades)},"bids":bid_rows,"asks":ask_rows,"trades":trades[-40:],"evidence":_evidence("Seeded simulator", "Price-time style market-order matching against bounded limit levels", observed=False)}


def _portfolio(req: PortfolioRequest) -> dict[str, Any]:
    data=_history(req.tickers,req.period); prices=pd.concat({k:v["Close"] for k,v in data.items()},axis=1).dropna(); returns=prices.pct_change().dropna(); mu=returns.mean().values*252; cov=returns.cov().values*252; names=list(prices.columns); n=len(names)
    def vol(w): return float(np.sqrt(w@cov@w))
    cons=[{"type":"eq","fun":lambda w:np.sum(w)-1}]
    if req.target_return is not None: cons.append({"type":"eq","fun":lambda w:w@mu-req.target_return})
    else: cons.append({"type":"ineq","fun":lambda w:w@mu-req.risk_free_rate})
    res=minimize(vol,np.ones(n)/n,bounds=[(0,1)]*n,constraints=cons,method="SLSQP")
    if not res.success: raise ValueError(f"Optimization failed: {res.message}")
    w=res.x; ret=float(w@mu); risk=vol(w)
    frontier=[]
    for target in np.linspace(float(mu.min()),float(mu.max()),35):
        fr=minimize(vol,np.ones(n)/n,bounds=[(0,1)]*n,constraints=[{"type":"eq","fun":lambda x:np.sum(x)-1},{"type":"eq","fun":lambda x,t=target:x@mu-t}],method="SLSQP")
        if fr.success: frontier.append({"return":target,"risk":vol(fr.x)})
    return {"kind":"portfolio","metrics":{"expected_return":ret,"volatility":risk,"sharpe_ratio":(ret-req.risk_free_rate)/risk if risk else 0},"weights":[{"ticker":name,"weight":float(weight)} for name,weight in zip(names,w)],"frontier":frontier,"evidence":_evidence("Yahoo Finance", "Long-only Markowitz annualized mean-variance optimization; weights sum to 1")}


def _monte_carlo(req: MonteCarloRequest) -> dict[str, Any]:
    frame=_history([req.ticker],req.period)[req.ticker.upper()]; ret=frame["Close"].pct_change().dropna(); mu=float(ret.mean()); sigma=float(ret.std()); rng=np.random.default_rng(req.seed); shocks=rng.normal(mu,sigma,(req.simulations,req.horizon_days)); terminal=req.initial_value*np.prod(1+shocks,axis=1); paths=req.initial_value*np.cumprod(1+shocks[:80],axis=1)
    q=np.quantile(terminal,[.01,.05,.25,.5,.75,.95,.99]); histogram,edges=np.histogram(terminal,bins=40)
    return {"kind":"monte_carlo","metrics":{"median_terminal":q[3],"var_95":req.initial_value-q[1],"cvar_95":req.initial_value-float(terminal[terminal<=q[1]].mean()),"probability_of_loss":float(np.mean(terminal<req.initial_value))},"quantiles":{"p01":q[0],"p05":q[1],"p25":q[2],"p50":q[3],"p75":q[4],"p95":q[5],"p99":q[6]},"histogram":[{"from":edges[i],"to":edges[i+1],"count":int(histogram[i])} for i in range(len(histogram))],"paths":paths[:,::max(1,req.horizon_days//100)].tolist(),"evidence":_evidence("Yahoo Finance calibrated simulation", f"IID Gaussian daily returns; {req.simulations} seeded paths", observed=False, caveats=["Simulated outcomes are not forecasts and may understate tail dependence"])}


def _surface(req: SurfaceRequest) -> dict[str, Any]:
    import yfinance as yf
    ticker=yf.Ticker(req.ticker.upper()); expiries=list(ticker.options)[:req.max_expirations]; points=[]
    for expiry in expiries:
        chain=ticker.option_chain(expiry)
        for kind,frame in (("call",chain.calls),("put",chain.puts)):
            for row in frame[["strike","impliedVolatility","lastPrice"]].dropna().itertuples(index=False):
                if 0<float(row.impliedVolatility)<5: points.append({"expiry":expiry,"strike":float(row.strike),"implied_volatility":float(row.impliedVolatility),"last_price":float(row.lastPrice),"type":kind})
    if not points: raise ValueError("No valid live options chain observations were returned")
    return {"kind":"volatility_surface","metrics":{"expirations":len(expiries),"contracts":len(points)},"points":points,"evidence":_evidence("Yahoo Finance options chain", "Provider-reported implied volatility by strike and expiry", caveats=["Quotes may be delayed or stale; verify liquidity and timestamps before decisions"])}


POSITIVE={"beat","beats","growth","gain","gains","surge","record","strong","upgrade","profit","profits","bullish","outperform","rally","innovation"}
NEGATIVE={"miss","misses","loss","losses","fall","falls","drop","downgrade","weak","fraud","probe","lawsuit","bearish","cut","cuts","risk"}
def _sentiment(req: SentimentRequest) -> dict[str, Any]:
    import yfinance as yf
    items=(yf.Ticker(req.ticker.upper()).news or [])[:req.limit]; rows=[]
    for item in items:
        content=item.get("content",item); title=str(content.get("title") or item.get("title") or ""); words={w.strip(".,:;!?()[]\"'").lower() for w in title.split()}; score=(len(words&POSITIVE)-len(words&NEGATIVE))/max(1,len(words&POSITIVE)+len(words&NEGATIVE)); rows.append({"title":title,"score":score,"publisher":content.get("provider",{}).get("displayName") or item.get("publisher"),"published":content.get("pubDate") or item.get("providerPublishTime"),"url":(content.get("canonicalUrl") or {}).get("url") or item.get("link")})
    if not rows: raise ValueError("No current headlines were returned")
    return {"kind":"sentiment","metrics":{"headline_count":len(rows),"average_sentiment":float(np.mean([r["score"] for r in rows])),"positive":sum(r["score"]>0 for r in rows),"negative":sum(r["score"]<0 for r in rows)},"headlines":rows,"evidence":_evidence("Yahoo Finance news metadata", "Transparent finance lexicon score on headline tokens", caveats=["Headline sentiment is contextual and is not equivalent to transformer-based document sentiment"])}


def _factor(req: FactorRequest) -> dict[str, Any]:
    data=_history([req.ticker,"SPY","IWM","IWD","IWF"],req.period); prices=pd.concat({k:v["Close"] for k,v in data.items()},axis=1).dropna(); ret=prices.pct_change().dropna(); y=ret[req.ticker.upper()]; X=pd.DataFrame({"market":ret["SPY"],"size":ret["IWM"]-ret["SPY"],"value":ret["IWD"]-ret["IWF"]}).dropna(); joined=pd.concat([y,X],axis=1).dropna(); design=np.column_stack([np.ones(len(joined)),joined[["market","size","value"]].values]); coef=np.linalg.lstsq(design,joined.iloc[:,0].values,rcond=None)[0]; pred=design@coef; resid=joined.iloc[:,0].values-pred; r2=1-float(np.sum(resid**2)/np.sum((joined.iloc[:,0].values-joined.iloc[:,0].mean())**2)); metrics={"annualized_alpha":float(coef[0]*252),"market_beta":float(coef[1]),"size_beta":float(coef[2]),"value_beta":float(coef[3]),"r_squared":r2}
    return {"kind":"factor_model","metrics":metrics,"series":[{"date":pd.Timestamp(i).isoformat(),"actual":float(a),"fitted":float(p)} for i,a,p in zip(joined.index[-500:],joined.iloc[-500:,0],pred[-500:])],"evidence":_evidence("Yahoo Finance", "OLS three-factor proxy: SPY market, IWM-SPY size, IWD-IWF value", caveats=["Uses liquid ETF proxies rather than the official Ken French research factors"])}


def _market(req: TickersRequest) -> dict[str, Any]:
    data=_history(req.tickers,req.period if req.period else "1mo", "1d"); series=[]
    for ticker,frame in data.items():
        f=frame.dropna(subset=["Close"]).iloc[-260:]; ma20=f["Close"].rolling(20).mean(); ma50=f["Close"].rolling(50).mean()
        for idx,row in f.iterrows(): series.append({"ticker":ticker,"date":pd.Timestamp(idx).isoformat(),"open":float(row.get("Open",row["Close"])),"high":float(row.get("High",row["Close"])),"low":float(row.get("Low",row["Close"])),"close":float(row["Close"]),"volume":float(row.get("Volume",0)),"ma20":_clean(float(ma20.loc[idx])) if pd.notna(ma20.loc[idx]) else None,"ma50":_clean(float(ma50.loc[idx])) if pd.notna(ma50.loc[idx]) else None})
    return {"kind":"market_dashboard","series":series,"evidence":_evidence("Yahoo Finance", "Adjusted OHLCV with 20/50-session simple moving averages")}


def register_quant_lab_routes(app: FastAPI, require_auth: Callable[..., Any]) -> None:
    dep=[Depends(require_auth)]
    catalog=[("backtest","Backtesting Engine"),("pairs","Pairs Trading"),("options","Options Pricing"),("order-book","Order Book Simulator"),("sentiment","Sentiment Correlation"),("portfolio","Portfolio Optimizer"),("monte-carlo","Monte Carlo"),("volatility-surface","Volatility Surface"),("factor-model","Factor Model"),("market-dashboard","Market Dashboard")]
    @app.get("/quant/labs", dependencies=dep)
    async def labs(): return {"labs":[{"id":i,"name":n} for i,n in catalog],"principle":"Observed data and simulations are explicitly separated"}
    def mount(path:str, model:Any, fn:Callable[[Any],dict[str,Any]]):
        async def endpoint(body):
            try: return _clean(fn(body))
            except ValueError as exc: raise HTTPException(400,str(exc)) from exc
            except Exception as exc: raise HTTPException(502,f"{path} data or computation unavailable: {type(exc).__name__}") from exc
        endpoint.__annotations__={"body":model}
        endpoint.__name__="quant_"+path.replace("-","_")
        app.post("/quant/"+path,dependencies=dep)(endpoint)
    for args in [("backtest",BacktestRequest,_backtest),("pairs",PairsRequest,_pairs),("options",OptionsRequest,_options),("order-book",OrderBookRequest,_order_book),("sentiment",SentimentRequest,_sentiment),("portfolio",PortfolioRequest,_portfolio),("monte-carlo",MonteCarloRequest,_monte_carlo),("volatility-surface",SurfaceRequest,_surface),("factor-model",FactorRequest,_factor),("market-dashboard",TickersRequest,_market)]: mount(*args)
