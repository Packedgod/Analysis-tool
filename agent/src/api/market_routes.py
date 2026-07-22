"""Market research HTTP routes backing the Market Pulse workspace.

Mounted by ``src/api/system_routes.py`` via ``register_market_routes(app, require_auth)``.

Every response here is source-labelled and never fabricates a fallback price,
quote, or headline: when the upstream provider is unavailable the endpoint
degrades to an explicit empty/``unavailable`` payload (or a 502) rather than
returning invented figures. This mirrors ``_load_market_overview`` in
``system_routes`` and is the rule the whole research product depends on --
a fabricated number that reaches a report is worse than a missing panel.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SOURCE = "Yahoo Finance + Moneycontrol"
YAHOO_SOURCE = "Yahoo Finance"
MONEYCONTROL_SOURCE = "Moneycontrol"

# Range -> (yfinance period, interval). Intraday intervals are capped by the
# provider to recent windows, so each range pins the finest interval it allows.
_RANGE_SPEC: Dict[str, Tuple[str, str]] = {
    "1D": ("1d", "5m"),
    "5D": ("5d", "15m"),
    "1M": ("1mo", "1d"),
    "3M": ("3mo", "1d"),
    "6M": ("6mo", "1d"),
    "1Y": ("1y", "1d"),
    "5Y": ("5y", "1wk"),
    "MAX": ("max", "1mo"),
}

# Fundamentals surfaced in the detail panel. Kept to an explicit allow-list:
# `.info` carries ~159 loosely-typed fields and passing it through wholesale
# would leak provider churn straight into the UI contract.
_INFO_FIELDS: Tuple[str, ...] = (
    "longName", "shortName", "sector", "industry", "country", "website",
    "longBusinessSummary", "currency", "exchange", "quoteType",
    "regularMarketPrice", "regularMarketChangePercent", "regularMarketPreviousClose",
    "regularMarketOpen", "regularMarketDayHigh", "regularMarketDayLow",
    "regularMarketVolume", "averageVolume", "marketCap", "enterpriseValue",
    "trailingPE", "forwardPE", "priceToBook", "priceToSalesTrailing12Months",
    "pegRatio", "beta", "dividendYield", "payoutRatio", "bookValue",
    "earningsGrowth", "revenueGrowth", "profitMargins", "grossMargins",
    "operatingMargins", "returnOnEquity", "returnOnAssets", "debtToEquity",
    "currentRatio", "quickRatio", "totalRevenue", "totalDebt", "totalCash",
    "freeCashflow", "operatingCashflow", "trailingEps", "forwardEps",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage",
    "twoHundredDayAverage", "sharesOutstanding", "floatShares",
    "heldPercentInsiders", "heldPercentInstitutions",
    "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    "recommendationKey", "numberOfAnalystOpinions", "fullTimeEmployees",
)

_CACHE_TTL = {"search": 300.0, "quote": 30.0, "candles": 60.0, "news": 300.0}
_cache: Dict[str, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()
_CACHE_MAX_ENTRIES = 512


def _cache_get(key: str) -> Optional[Any]:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.monotonic() < entry[0]:
            return entry[1]
        if entry:
            _cache.pop(key, None)
        return None


def _cache_put(key: str, value: Any, ttl: float) -> None:
    with _cache_lock:
        # Unbounded growth is a real risk here: cache keys include a
        # user-supplied symbol, so an attacker (or a typo loop) could otherwise
        # pin arbitrary memory. Evict oldest-expiry first when over budget.
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            for stale_key in sorted(_cache, key=lambda k: _cache[k][0])[: _CACHE_MAX_ENTRIES // 4]:
                _cache.pop(stale_key, None)
        _cache[key] = (time.monotonic() + ttl, value)


def _finite(value: Any) -> Optional[float]:
    """Coerce to a JSON-safe float, or None. NaN/Inf must never reach the UI."""
    try:
        if value is None:
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _clean_symbol(symbol: str) -> str:
    """Validate a ticker before it reaches the provider or a cache key.

    Rejects anything outside the ticker character set so a symbol can neither
    poison the cache namespace nor be used to probe the provider with
    arbitrary strings.
    """
    candidate = (symbol or "").strip().upper()
    if not candidate or len(candidate) > 24:
        raise HTTPException(400, "Symbol must be 1-24 characters")
    if not all(char.isalnum() or char in ".-^=" for char in candidate):
        raise HTTPException(400, "Symbol contains unsupported characters")
    return candidate


def _import_yf():
    try:
        import yfinance as yf  # noqa: PLC0415 - optional heavy dependency, imported per request
        return yf
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise HTTPException(503, "Market data provider is not installed") from exc


def _moneycontrol_frame(symbol: str, window: str):
    """Return an India-equity Moneycontrol frame for a UI range, or None."""
    if not symbol.endswith((".NS", ".BO")):
        return None
    from backtest.loaders.moneycontrol_loader import DataLoader  # noqa: PLC0415

    now = datetime.now(timezone.utc).date()
    days = {"1D": 7, "5D": 14, "1M": 40, "3M": 120, "6M": 220,
            "1Y": 400, "5Y": 1900, "MAX": 7300}[window]
    result = DataLoader().fetch(
        [symbol], (now - timedelta(days=days)).isoformat(), now.isoformat(), interval="1D"
    )
    frame = result.get(symbol)
    return frame if frame is not None and not frame.empty else None


def _moneycontrol_quote(symbol: str) -> Dict[str, Any] | None:
    """Build a source-labelled quote from Moneycontrol's last verified bars."""
    frame = _moneycontrol_frame(symbol, "1M")
    if frame is None or frame.empty:
        return None
    last = frame.iloc[-1]
    previous = frame.iloc[-2] if len(frame) > 1 else None
    price = _finite(last.get("close"))
    previous_close = _finite(previous.get("close")) if previous is not None else None
    change = ((price / previous_close) - 1.0) * 100.0 if price is not None and previous_close else None
    return {
        "symbol": symbol, "name": symbol, "price": price,
        "change_percent": change, "previous_close": previous_close,
        "currency": "INR", "exchange": "BSE" if symbol.endswith(".BO") else "NSE",
        "quote_type": "EQUITY", "source": MONEYCONTROL_SOURCE,
        "observed_at": datetime.now(timezone.utc).isoformat(), "fundamentals": {},
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ScreenRequest(BaseModel):
    """Batch-quote request for the screener and watchlist grid."""
    symbols: List[str] = Field(default_factory=list, max_length=60)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_market_routes(app: FastAPI, require_auth: Callable[..., Any]) -> None:
    """Mount the market research routes onto ``app``."""
    dep = [Depends(require_auth)]

    def _quote_payload(symbol: str) -> Dict[str, Any]:
        """Build one symbol's quote. Raises on provider failure; never invents."""
        cache_key = f"quote:{symbol}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        info: Dict[str, Any] = {}
        yahoo_error: Exception | None = None
        try:
            yf = _import_yf()
            info = yf.Ticker(symbol).info or {}
        except Exception as exc:  # noqa: BLE001 - Moneycontrol is the India fallback
            yahoo_error = exc
        if not info.get("symbol") and not info.get("regularMarketPrice") and not info.get("shortName"):
            fallback = _moneycontrol_quote(symbol)
            if fallback is None:
                if yahoo_error:
                    raise yahoo_error
                raise HTTPException(404, f"No market data found for {symbol}")
            _cache_put(cache_key, fallback, _CACHE_TTL["quote"])
            return fallback

        fundamentals = {
            key: (_finite(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value)
            for key, value in ((field, info.get(field)) for field in _INFO_FIELDS)
            if value is not None
        }

        price = _finite(info.get("regularMarketPrice"))
        previous = _finite(info.get("regularMarketPreviousClose"))
        change_percent = _finite(info.get("regularMarketChangePercent"))
        if price is None:
            fallback = _moneycontrol_quote(symbol)
            if fallback is not None:
                fallback["fundamentals"] = fundamentals
                fallback["name"] = info.get("longName") or info.get("shortName") or symbol
                _cache_put(cache_key, fallback, _CACHE_TTL["quote"])
                return fallback
        # Derive the delta only when the provider omitted it — computing from a
        # missing previous close would silently produce a fake 0%.
        if change_percent is None and price is not None and previous:
            change_percent = ((price / previous) - 1.0) * 100.0

        payload = {
            "symbol": symbol,
            "name": info.get("longName") or info.get("shortName") or symbol,
            "price": price,
            "change_percent": change_percent,
            "previous_close": previous,
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
            "quote_type": info.get("quoteType"),
            "source": YAHOO_SOURCE,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "fundamentals": fundamentals,
        }
        _cache_put(cache_key, payload, _CACHE_TTL["quote"])
        return payload

    @app.get("/market/search", dependencies=dep)
    async def market_search(
        q: str = Query(..., min_length=1, max_length=64, description="Company name or ticker"),
        limit: int = Query(10, ge=1, le=25),
    ):
        """Resolve a free-text query to candidate securities."""
        query = q.strip()
        if not query:
            return {"source": SOURCE, "query": q, "results": []}

        cache_key = f"search:{query.lower()}:{limit}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        yf = _import_yf()
        try:
            quotes = yf.Search(query, max_results=limit).quotes or []
        except Exception as exc:  # noqa: BLE001 - provider degrades independently
            logger.info("Market search unavailable for %r: %s", query, exc)
            raise HTTPException(502, "Symbol search is temporarily unavailable") from exc

        results = [
            {
                "symbol": row.get("symbol"),
                "name": row.get("shortname") or row.get("longname") or row.get("symbol"),
                "exchange": row.get("exchange"),
                "quote_type": row.get("quoteType"),
            }
            for row in quotes
            if row.get("symbol")
        ]
        payload = {"source": SOURCE, "query": query, "results": results}
        _cache_put(cache_key, payload, _CACHE_TTL["search"])
        return payload

    @app.get("/market/quote/{symbol}", dependencies=dep)
    async def market_quote(symbol: str):
        """Full quote and fundamentals for one security."""
        clean = _clean_symbol(symbol)
        try:
            return _quote_payload(clean)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.info("Quote unavailable for %s: %s", clean, exc)
            raise HTTPException(502, f"Quote data unavailable for {clean}") from exc

    @app.get("/market/candles/{symbol}", dependencies=dep)
    async def market_candles(
        symbol: str,
        range: str = Query("6M", description="One of 1D,5D,1M,3M,6M,1Y,5Y,MAX"),
    ):
        """OHLCV series for the chart, in the shape the candlestick chart expects."""
        clean = _clean_symbol(symbol)
        window = (range or "6M").upper()
        if window not in _RANGE_SPEC:
            raise HTTPException(400, f"range must be one of {','.join(_RANGE_SPEC)}")

        cache_key = f"candles:{clean}:{window}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        period, interval = _RANGE_SPEC[window]
        yf = _import_yf()
        frame = None
        try:
            frame = yf.Ticker(clean).history(period=period, interval=interval, auto_adjust=False)
        except Exception as exc:  # noqa: BLE001
            logger.info("Candles unavailable for %s: %s", clean, exc)
        provider = YAHOO_SOURCE
        if frame is None or frame.empty:
            frame = _moneycontrol_frame(clean, window)
            if frame is not None:
                provider = MONEYCONTROL_SOURCE
                interval = "1d"

        bars: List[Dict[str, Any]] = []
        if frame is not None and not frame.empty:
            intraday = interval.endswith(("m", "h"))
            stamp = "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d"
            for index, row in frame.iterrows():
                close = _finite(row.get("Close") if "Close" in row else row.get("close"))
                if close is None:
                    continue  # a gap must stay a gap, not be forward-filled
                bars.append({
                    "time": index.strftime(stamp),
                    "open": _finite(row.get("Open") if "Open" in row else row.get("open")) or close,
                    "high": _finite(row.get("High") if "High" in row else row.get("high")) or close,
                    "low": _finite(row.get("Low") if "Low" in row else row.get("low")) or close,
                    "close": close,
                    "volume": _finite(row.get("Volume") if "Volume" in row else row.get("volume")) or 0.0,
                })

        payload = {
            "symbol": clean,
            "range": window,
            "interval": interval,
            "source": provider,
            "status": "live" if bars else "unavailable",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "bars": bars,
        }
        if bars:
            _cache_put(cache_key, payload, _CACHE_TTL["candles"])
        return payload

    @app.get("/market/news/{symbol}", dependencies=dep)
    async def market_news(symbol: str, limit: int = Query(12, ge=1, le=30)):
        """Recent headlines for one security."""
        clean = _clean_symbol(symbol)
        cache_key = f"news:{clean}:{limit}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        yf = _import_yf()
        try:
            raw = yf.Ticker(clean).news or []
        except Exception as exc:  # noqa: BLE001
            logger.info("News unavailable for %s: %s", clean, exc)
            raise HTTPException(502, f"News unavailable for {clean}") from exc

        items: List[Dict[str, Any]] = []
        for entry in raw[:limit]:
            # yfinance >= 1.x nests the article under `content`; older payloads
            # were flat. Accept both so a provider bump does not blank the feed.
            content = entry.get("content") if isinstance(entry.get("content"), dict) else entry
            title = content.get("title")
            if not title:
                continue
            url = (
                (content.get("canonicalUrl") or {}).get("url")
                if isinstance(content.get("canonicalUrl"), dict)
                else content.get("canonicalUrl")
            ) or (
                (content.get("clickThroughUrl") or {}).get("url")
                if isinstance(content.get("clickThroughUrl"), dict)
                else content.get("link")
            )
            provider = content.get("provider")
            items.append({
                "id": entry.get("id") or content.get("id") or title,
                "title": title,
                "summary": content.get("summary") or content.get("description"),
                "published_at": content.get("pubDate") or content.get("displayTime"),
                "publisher": provider.get("displayName") if isinstance(provider, dict) else provider,
                "url": url,
            })

        payload = {
            "symbol": clean,
            "source": SOURCE,
            "status": "live" if items else "unavailable",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        }
        if items:
            _cache_put(cache_key, payload, _CACHE_TTL["news"])
        return payload

    @app.post("/market/screen", dependencies=dep)
    async def market_screen(body: ScreenRequest):
        """Batch quotes for the screener grid, watchlist, and comparison table.

        Filtering and ranking stay client-side: the criteria are user-authored
        and change per keystroke, so round-tripping them would add latency
        without adding capability. Symbols that fail resolve are reported in
        ``unavailable`` rather than dropped, so the UI can say *which* ones.
        """
        symbols: List[str] = []
        for raw in body.symbols:
            try:
                clean = _clean_symbol(raw)
            except HTTPException:
                continue
            if clean not in symbols:
                symbols.append(clean)

        rows: List[Dict[str, Any]] = []
        unavailable: List[str] = []
        for symbol in symbols:
            try:
                quote = _quote_payload(symbol)
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not fail the grid
                logger.info("Screen row unavailable for %s: %s", symbol, exc)
                unavailable.append(symbol)
                continue
            fundamentals = quote.get("fundamentals") or {}
            rows.append({
                "symbol": quote["symbol"],
                "name": quote["name"],
                "source": quote.get("source"),
                "price": quote["price"],
                "change_percent": quote["change_percent"],
                "currency": quote.get("currency"),
                "exchange": quote.get("exchange"),
                "sector": fundamentals.get("sector"),
                "industry": fundamentals.get("industry"),
                "market_cap": fundamentals.get("marketCap"),
                "trailing_pe": fundamentals.get("trailingPE"),
                "forward_pe": fundamentals.get("forwardPE"),
                "price_to_book": fundamentals.get("priceToBook"),
                "dividend_yield": fundamentals.get("dividendYield"),
                "beta": fundamentals.get("beta"),
                "return_on_equity": fundamentals.get("returnOnEquity"),
                "profit_margins": fundamentals.get("profitMargins"),
                "debt_to_equity": fundamentals.get("debtToEquity"),
                "revenue_growth": fundamentals.get("revenueGrowth"),
                "fifty_two_week_high": fundamentals.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": fundamentals.get("fiftyTwoWeekLow"),
                "average_volume": fundamentals.get("averageVolume"),
            })

        return {
            "source": SOURCE,
            "status": "live" if rows else "unavailable",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "rows": rows,
            "unavailable": unavailable,
        }
