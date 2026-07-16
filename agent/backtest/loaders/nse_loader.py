"""Official NSE India loader: free, no-auth NSE equity OHLCV via the public API.

Pulls daily bars straight from the National Stock Exchange of India's own public
endpoint (``www.nseindia.com/api/historical/cm/equity``) — the authoritative
source for NSE-listed cash-segment prices. No API key or broker login: the only
requirement is a primed browser-like cookie, which NSE hands out on a plain GET
of its home page. The shared throttled HTTP session persists that cookie across
requests, and a single re-prime is attempted if NSE rotates it mid-run.

Scope: NSE cash equities only (project ``RELIANCE.NS`` → NSE symbol ``RELIANCE``,
series ``EQ``). BSE symbols (``500325.BO``) are declined here and left to the
Moneycontrol/Yahoo fallbacks. NSE caps each request to a bounded date window, so
long ranges are fetched in chunks and stitched together; very deep history may
come back short — for that prefer Yahoo, which leads the india_equity chain.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders._http import resolve_min_interval, throttled_get
from backtest.loaders.base import (
    cached_loader_fetch,
    validate_date_range,
    validate_ohlc,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")

_HOST_KEY = "nse"
_BASE = "https://www.nseindia.com"
_HISTORY_URL = f"{_BASE}/api/historical/cm/equity"
# NSE bans bursts hard; keep a polite floor between calls (override via env).
_MIN_INTERVAL = resolve_min_interval("VIBE_TRADING_NSE_MIN_INTERVAL", 1.0)
# NSE returns a bounded window per request; walk the range in ~150-day chunks.
_CHUNK_DAYS = 150
_MAX_CHUNKS = 12  # ~5y of daily history; a hard bound so one call can't spin.

# Browser-like headers NSE's edge requires; the API rejects bare clients.
_NSE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{_BASE}/get-quotes/equity",
}

_prime_lock = threading.Lock()
_primed = False


def _prime_session(force: bool = False) -> None:
    """Seed NSE's anti-bot cookie into the shared throttled session.

    NSE's API returns 401/403 without the cookies its home page sets. Because
    :func:`throttled_get` reuses one :class:`requests.Session` per host key, a
    single GET of the home page primes the cookie jar for every later API call.
    Guarded so concurrent workers prime at most once; ``force`` re-primes after
    a rejection when NSE rotates the cookie mid-run.
    """
    global _primed
    if _primed and not force:
        return
    with _prime_lock:
        if _primed and not force:
            return
        try:
            throttled_get(
                _BASE + "/",
                host_key=_HOST_KEY,
                min_interval=_MIN_INTERVAL,
                headers={"Accept": "text/html,application/xhtml+xml"},
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001 — priming is best-effort
            logger.debug("nse cookie prime failed: %s", exc)
        _primed = True


def _is_supported(code: str) -> bool:
    """Return whether *code* is an NSE symbol this loader handles."""
    return code.strip().upper().endswith(".NS")


def _nse_symbol(code: str) -> str:
    """Strip the ``.NS`` suffix, leaving NSE's bare trading symbol."""
    cleaned = code.strip()
    return cleaned[:-3] if cleaned.upper().endswith(".NS") else cleaned


def _chunks(start_date: str, end_date: str) -> List[tuple[pd.Timestamp, pd.Timestamp]]:
    """Split ``[start, end]`` into ascending <= ``_CHUNK_DAYS`` windows (bounded)."""
    lower = pd.Timestamp(start_date).normalize()
    upper = pd.Timestamp(end_date).normalize()
    windows: List[tuple[pd.Timestamp, pd.Timestamp]] = []
    cursor = lower
    step = pd.Timedelta(days=_CHUNK_DAYS)
    while cursor <= upper and len(windows) < _MAX_CHUNKS:
        window_end = min(cursor + step - pd.Timedelta(days=1), upper)
        windows.append((cursor, window_end))
        cursor = window_end + pd.Timedelta(days=1)
    return windows


def _fetch_chunk(symbol: str, lower: pd.Timestamp, upper: pd.Timestamp) -> list[dict]:
    """Fetch one date-window's raw ``data`` records, priming/retrying once on 401/403."""
    params = {
        "symbol": symbol,
        "series": '["EQ"]',
        "from": lower.strftime("%d-%m-%Y"),
        "to": upper.strftime("%d-%m-%Y"),
    }
    for attempt in range(2):
        _prime_session(force=attempt > 0)
        try:
            resp = throttled_get(
                _HISTORY_URL,
                host_key=_HOST_KEY,
                min_interval=_MIN_INTERVAL,
                params=params,
                headers=_NSE_HEADERS,
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001 — one bad window never aborts
            logger.debug("nse fetch failed for %s: %s", symbol, exc)
            return []
        if resp.status_code in (401, 403) and attempt == 0:
            continue  # cookie stale — force a re-prime and retry once
        if resp.status_code != 200:
            logger.debug("nse %s returned HTTP %s", symbol, resp.status_code)
            return []
        try:
            payload = resp.json()
        except ValueError:
            return []
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, list) else []
    return []


def _records_to_frame(
    records: list[dict], start_date: str, end_date: str
) -> pd.DataFrame:
    """Build a clipped, midnight-indexed OHLCV frame from NSE ``data`` records."""
    rows = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        ts = rec.get("CH_TIMESTAMP") or rec.get("mTIMESTAMP")
        if not ts:
            continue
        rows.append(
            {
                "trade_date": ts,
                "open": rec.get("CH_OPENING_PRICE"),
                "high": rec.get("CH_TRADE_HIGH_PRICE"),
                "low": rec.get("CH_TRADE_LOW_PRICE"),
                "close": rec.get("CH_CLOSING_PRICE"),
                "volume": rec.get("CH_TOT_TRADED_QTY"),
            }
        )
    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows)
    index = pd.to_datetime(frame["trade_date"], errors="coerce").dt.normalize()
    frame = frame.drop(columns=["trade_date"])
    frame.index = pd.DatetimeIndex(index)
    frame.index.name = "trade_date"

    frame = frame.loc[:, list(_OHLCV_COLUMNS)].apply(pd.to_numeric, errors="coerce")
    frame["volume"] = frame["volume"].fillna(0.0)
    frame = frame.dropna(subset=["open", "high", "low", "close"])
    frame = frame[~frame.index.isna()]

    lower = pd.Timestamp(start_date).normalize()
    upper = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)
    frame = frame[(frame.index >= lower) & (frame.index < upper)]
    if frame.empty:
        return frame
    frame = frame[~frame.index.duplicated(keep="last")].sort_index()
    return validate_ohlc(frame.astype(float))


@register
class DataLoader:
    """Official NSE India cash-equity OHLCV loader (free, direct HTTP, no auth)."""

    name = "nse"
    markets = {"india_equity"}
    requires_auth = False

    def is_available(self) -> bool:
        """Always available — uses the throttled public HTTP session."""
        return True

    def __init__(self) -> None:
        """Initialize the loader (no credentials needed for public NSE data)."""
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

        Only NSE (``.NS``) symbols are served; anything else is skipped so the
        india_equity fallback chain can route it elsewhere. NSE publishes daily
        bars only, so non-daily intervals are declined rather than silently
        returned at the wrong granularity.
        """
        del fields
        if not codes:
            return {}
        validate_date_range(start_date, end_date)
        if str(interval or "1D").strip().upper() not in {"1D", "1DAY", "D"}:
            return {}  # NSE public history is daily-only

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
                logger.warning("nse failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """Fetch and normalize one NSE symbol across bounded date chunks."""
        symbol = _nse_symbol(code)
        records: list[dict] = []
        for lower, upper in _chunks(start_date, end_date):
            records.extend(_fetch_chunk(symbol, lower, upper))
        frame = _records_to_frame(records, start_date, end_date)
        return frame if not frame.empty else None
