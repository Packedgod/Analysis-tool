"""Groww loader: free, no-auth NSE equity OHLCV via Groww's public charting API.

Groww serves its web charts from a public (login-free) endpoint,
``groww.in/v1/api/charting_service/.../chart/exchange/NSE/segment/CASH/<SYMBOL>``,
returning daily candles as ``[epoch, open, high, low, close, volume]`` rows. This
loader adapts that into the standard OHLCV frame. No API key, no broker session —
just the public charting feed the site itself uses.

Scope: NSE cash equities (project ``RELIANCE.NS`` → Groww symbol ``RELIANCE``).
BSE numeric codes (``500325.BO``) can't be mapped to Groww's symbol form, so they
are declined and left to the Moneycontrol/Yahoo fallbacks. Groww sits deep in the
india_equity chain behind Yahoo/NSE/Moneycontrol; per-symbol failures are
swallowed so one bad symbol never aborts the batch.
"""

from __future__ import annotations

import logging
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

_HOST_KEY = "groww"
_CHART_URL = (
    "https://groww.in/v1/api/charting_service/v4/chart/exchange/NSE/segment/CASH/{symbol}"
)
_MIN_INTERVAL = resolve_min_interval("VIBE_TRADING_GROWW_MIN_INTERVAL", 0.4)
_DAILY_INTERVAL_MINUTES = 1440
# Epoch magnitude cut: daily candles stamp seconds (~1.6e9); some payloads use
# milliseconds (~1.6e12). Anything above this threshold is treated as millis.
_MILLIS_THRESHOLD = 1e11


def _is_supported(code: str) -> bool:
    """Return whether *code* is an NSE symbol this loader handles."""
    return code.strip().upper().endswith(".NS")


def _groww_symbol(code: str) -> str:
    """Strip the ``.NS`` suffix, leaving Groww's bare NSE trading symbol."""
    cleaned = code.strip()
    return cleaned[:-3] if cleaned.upper().endswith(".NS") else cleaned


def _epoch_millis(date_str: str, *, end: bool = False) -> int:
    """UTC-midnight epoch milliseconds for ``date_str`` (``end`` adds a day)."""
    ts = pd.Timestamp(date_str).normalize()
    if end:
        ts += pd.Timedelta(days=1)
    return int(ts.value // 1_000_000)


def _candles_to_frame(payload: object, start_date: str, end_date: str) -> pd.DataFrame:
    """Build a clipped, midnight-indexed OHLCV frame from a Groww candles JSON."""
    if not isinstance(payload, dict):
        return pd.DataFrame()
    candles = payload.get("candles")
    if not isinstance(candles, list) or not candles:
        return pd.DataFrame()

    rows = []
    for candle in candles:
        if not isinstance(candle, (list, tuple)) or len(candle) < 5:
            continue
        ts = candle[0]
        try:
            ts_num = float(ts)
        except (TypeError, ValueError):
            continue
        unit = "ms" if ts_num >= _MILLIS_THRESHOLD else "s"
        rows.append(
            {
                "_ts": ts_num,
                "_unit": unit,
                "open": candle[1],
                "high": candle[2],
                "low": candle[3],
                "close": candle[4],
                "volume": candle[5] if len(candle) > 5 else 0.0,
            }
        )
    if not rows:
        return pd.DataFrame()

    frame = pd.DataFrame(rows)
    # All candles in one payload share a unit; normalize on the first row's unit.
    unit = frame["_unit"].iloc[0]
    index = pd.to_datetime(frame["_ts"], unit=unit, utc=True).dt.tz_convert(None)
    frame = frame.drop(columns=["_ts", "_unit"])
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
    """Groww public charting OHLCV loader (free, direct HTTP, no auth)."""

    name = "groww"
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

        Serves NSE (``.NS``) symbols only; the charting feed used here is
        daily-only, so non-daily intervals are declined rather than returned at
        the wrong granularity.
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
                logger.warning("groww failed for %s: %s", code, exc)
        return result

    def _fetch_one(
        self, code: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """Fetch and normalize one NSE symbol's daily candles."""
        symbol = _groww_symbol(code)
        try:
            payload = throttled_get_json(
                _CHART_URL.format(symbol=symbol),
                host_key=_HOST_KEY,
                min_interval=_MIN_INTERVAL,
                params={
                    "startTimeInMillis": _epoch_millis(start_date),
                    "endTimeInMillis": _epoch_millis(end_date, end=True),
                    "intervalInMinutes": _DAILY_INTERVAL_MINUTES,
                },
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("groww history failed for %s: %s", code, exc)
            return None
        frame = _candles_to_frame(payload, start_date, end_date)
        return frame if not frame.empty else None
