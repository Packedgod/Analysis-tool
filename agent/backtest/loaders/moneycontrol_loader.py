"""Moneycontrol loader: free, no-auth India equity OHLCV via the public techcharts.

Moneycontrol exposes a TradingView-compatible datafeed at
``priceapi.moneycontrol.com/techCharts/indianMarket/stock`` — the same public
(login-free) feed that powers its own web charts. Two calls: ``/search`` maps a
project symbol to Moneycontrol's internal ticker, then ``/history`` returns the
OHLCV arrays. Covers both NSE (``RELIANCE.NS``) and BSE (``500325.BO``) cash
equities, so it also backstops BSE symbols the NSE-only feed declines.

It sits deep in the india_equity fallback chain behind Yahoo and the official
NSE feed: a best-effort public source used to fill gaps, never the primary. Any
per-symbol failure (unresolved ticker, ``no_data``, transport error) is swallowed
so one bad symbol never aborts the batch.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders._http import resolve_min_interval, throttled_get_json
from backtest.loaders.base import (
    cached_loader_fetch,
    validate_date_range,
    validate_ohlc,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")

_HOST_KEY = "moneycontrol"
_BASE = "https://priceapi.moneycontrol.com/techCharts/indianMarket/stock"
_SEARCH_URL = f"{_BASE}/search"
_HISTORY_URL = f"{_BASE}/history"
_MIN_INTERVAL = resolve_min_interval("VIBE_TRADING_MONEYCONTROL_MIN_INTERVAL", 0.4)

# Symbol -> resolved Moneycontrol ticker (or None when it can't be resolved),
# memoized for the process so repeated fetches skip the search round-trip.
_TICKER_CACHE: dict[str, Optional[str]] = {}
_CACHE_LOCK = threading.Lock()


def _is_supported(code: str) -> bool:
    """Return whether *code* is an India NSE/BSE symbol this loader handles."""
    return code.strip().upper().endswith((".NS", ".BO"))


def _exchange_for(code: str) -> str:
    """Map the project suffix to Moneycontrol's exchange code (NSE / BSE)."""
    return "BSE" if code.strip().upper().endswith(".BO") else "NSE"


def _base_symbol(code: str) -> str:
    """Strip the ``.NS`` / ``.BO`` suffix, leaving the bare exchange symbol."""
    cleaned = code.strip()
    return cleaned[:-3] if cleaned.upper().endswith((".NS", ".BO")) else cleaned


def _epoch_seconds(date_str: str, *, end: bool = False) -> int:
    """UTC-midnight epoch seconds for ``date_str`` (``end`` adds a day, exclusive)."""
    day = pd.Timestamp(date_str).normalize().date()
    moment = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    if end:
        moment += dt.timedelta(days=1)
    return int(moment.timestamp())


def _resolve_ticker(symbol: str, exchange: str) -> Optional[str]:
    """Resolve a bare exchange symbol to Moneycontrol's internal ticker, cached."""
    key = f"{exchange}:{symbol}".upper()
    with _CACHE_LOCK:
        if key in _TICKER_CACHE:
            return _TICKER_CACHE[key]

    ticker: Optional[str] = None
    try:
        results = throttled_get_json(
            _SEARCH_URL,
            host_key=_HOST_KEY,
            min_interval=_MIN_INTERVAL,
            params={
                "query": symbol,
                "limit": 20,
                "type": "stock",
                "exchange": exchange,
            },
            timeout=15.0,
        )
    except Exception as exc:  # noqa: BLE001 — resolution is best-effort
        logger.debug("moneycontrol search failed for %s: %s", symbol, exc)
        results = None

    if isinstance(results, list):
        target = symbol.strip().upper()
        # Prefer an exact symbol match on the right exchange; else first hit.
        best = None
        for rec in results:
            if not isinstance(rec, dict):
                continue
            rec_symbol = str(rec.get("symbol", "")).strip().upper()
            rec_exchange = str(rec.get("exchange", "")).strip().upper()
            candidate = rec.get("ticker") or rec.get("symbol")
            if rec_symbol == target and rec_exchange == exchange.upper():
                best = candidate
                break
            if best is None and candidate:
                best = candidate
        ticker = str(best) if best else None

    with _CACHE_LOCK:
        _TICKER_CACHE[key] = ticker
    return ticker


def _history_to_frame(payload: object, start_date: str, end_date: str) -> pd.DataFrame:
    """Build a clipped, midnight-indexed OHLCV frame from a techcharts history JSON."""
    if not isinstance(payload, dict) or str(payload.get("s")) != "ok":
        return pd.DataFrame()
    times = payload.get("t") or []
    if not isinstance(times, list) or not times:
        return pd.DataFrame()

    frame = pd.DataFrame(
        {
            "open": payload.get("o") or [],
            "high": payload.get("h") or [],
            "low": payload.get("l") or [],
            "close": payload.get("c") or [],
            "volume": payload.get("v") or [0.0] * len(times),
        }
    )
    if frame.empty or len(frame) != len(times):
        return pd.DataFrame()

    index = pd.to_datetime(pd.Series(times), unit="s", utc=True).dt.tz_convert(None)
    frame.index = pd.DatetimeIndex(index).normalize()
    frame.index.name = "trade_date"

    frame = frame.loc[:, list(_OHLCV_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    frame["volume"] = frame["volume"].fillna(0.0)
    frame = frame.dropna(subset=["open", "high", "low", "close"])

    lower = pd.Timestamp(start_date).normalize()
    upper = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)
    frame = frame[(frame.index >= lower) & (frame.index < upper)]
    if frame.empty:
        return frame
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return validate_ohlc(frame.astype(float))


@register
class DataLoader:
    """Moneycontrol public techcharts OHLCV loader (free, direct HTTP, no auth)."""

    name = "moneycontrol"
    markets = {"india_equity"}
    requires_auth = False

    def is_available(self) -> bool:
        """Always available — uses the throttled public HTTP client."""
        return True

    def __init__(self) -> None:
        """Initialize the loader (no credentials needed for public data)."""
        pass

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch daily OHLCV history keyed by the original project symbols.

        Serves NSE/BSE symbols only; the techcharts daily feed is daily-only, so
        non-daily intervals are declined rather than returned at the wrong
        granularity.
        """
        del fields
        if not codes:
            return {}
        validate_date_range(start_date, end_date)
        if str(interval or "1D").strip().upper() not in {"1D", "1DAY", "D"}:
            return {}

        result: Dict[str, pd.DataFrame] = {}
        for code in codes:
            if not _is_supported(code):
                continue
            try:
                df = cached_loader_fetch(
                    source=self.name,
                    symbol=code,
                    timeframe="1D",
                    start_date=start_date,
                    end_date=end_date,
                    fields=None,
                    fetch=lambda code=code: self._fetch_one(code, start_date, end_date),
                )
                if df is not None and not df.empty:
                    result[code] = df
            except Exception as exc:  # noqa: BLE001 — one bad symbol never aborts
                logger.warning("moneycontrol failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """Resolve the ticker, fetch its history window, and normalize the frame."""
        ticker = _resolve_ticker(_base_symbol(code), _exchange_for(code))
        if not ticker:
            return None
        try:
            payload = throttled_get_json(
                _HISTORY_URL,
                host_key=_HOST_KEY,
                min_interval=_MIN_INTERVAL,
                params={
                    "symbol": ticker,
                    "resolution": "1D",
                    "from": _epoch_seconds(start_date),
                    "to": _epoch_seconds(end_date, end=True),
                },
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("moneycontrol history failed for %s: %s", code, exc)
            return None
        frame = _history_to_frame(payload, start_date, end_date)
        return frame if not frame.empty else None
