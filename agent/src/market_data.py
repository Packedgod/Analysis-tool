"""Shared market data helpers for MCP and local agent tools."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROWS = 250
_CACHE_ROOT = Path(
    os.getenv(
        "VIBE_ANALYSIS_MARKET_CACHE",
        str(Path.home() / ".vibe-analysis" / "cache" / "market-data"),
    )
)

# Symbol -> preferred source. The matched source is the head of its market's
# fallback chain (registry.FALLBACK_CHAINS), so an unavailable preferred source
# still degrades gracefully to the rest of the chain. US/HK equities route to
# the throttle-tolerant Yahoo public endpoint first (lower IP-ban risk than the
# yfinance SDK), A-shares to the Tencent quote endpoint.
_SOURCE_PATTERNS = [
    (re.compile(r"^local:", re.I), "local"),
    # Yahoo's public chart API carries index tickers such as ^NSEI unchanged.
    (re.compile(r"^\^", re.I), "yahoo"),
    (re.compile(r"^\d{6}\.(SZ|SH|BJ)$", re.I), "tencent"),
    (re.compile(r"^[A-Z]+\.US$", re.I), "yahoo"),
    (re.compile(r"^\d{3,5}\.HK$", re.I), "yahoo"),
    # India: NSE (RELIANCE.NS) / BSE (500325.BO). Tickers may carry '&' and '-'
    # (e.g. M&M.NS, BAJAJ-AUTO.NS). Served by Yahoo's public chart endpoint.
    (re.compile(r"^[A-Z0-9&.\-]+\.(NS|BO)$", re.I), "yahoo"),
    (re.compile(r"^[A-Z]+-USDT$", re.I), "okx"),
    (re.compile(r"^[A-Z]+/USDT$", re.I), "ccxt"),
]


def detect_source(code: str) -> str:
    """Infer the best loader source for a normalized symbol."""
    from backtest.engines._market_hooks import normalize_market_symbol

    code = normalize_market_symbol(code)
    for pattern, source in _SOURCE_PATTERNS:
        if pattern.match(code):
            return source
    return "tushare"


def get_loader(source: str):
    """Get loader class via registry with fallback support."""
    from backtest.loaders.registry import get_loader_cls_with_fallback

    return get_loader_cls_with_fallback(source)


def cap_rows(records: list, max_rows: int) -> list | dict[str, object]:
    """Bound a per-symbol row list to keep tool payloads within budget."""
    n = len(records)
    if max_rows < 0:
        max_rows = DEFAULT_MAX_ROWS
    if max_rows == 0 or n <= max_rows:
        return records
    step = math.ceil(n / max_rows)
    sampled = records[::step]
    if sampled[-1] is not records[-1]:
        sampled = sampled + [records[-1]]
    return {
        "rows": n,
        "returned": len(sampled),
        "truncated": True,
        "policy": f"every-{step}th-row (even stride; last bar pinned)",
        "hint": "narrow the date range, coarsen interval, or set max_rows=0 for all rows",
        "data": sampled,
    }


def _json_safe(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _usable_frame(frame: Any) -> bool:
    """Return whether a loader frame contains at least one row."""
    return frame is not None and not bool(getattr(frame, "empty", False))


def _latest_price(records: list[dict[str, Any]]) -> tuple[float | None, str | None]:
    """Return the newest finite close/price and its best available timestamp."""
    for row in reversed(records):
        raw = row.get("close", row.get("price"))
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            stamp = next(
                (str(row[key]) for key in ("trade_date", "date", "datetime", "timestamp") if row.get(key)),
                None,
            )
            return value, stamp
    return None, None


def _cache_file(symbol: str, interval: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{symbol}_{interval}")
    return _CACHE_ROOT / f"{safe}.json"


def _write_cache(symbol: str, interval: str, records: list[dict[str, Any]], source: str) -> None:
    """Atomically retain the last verified non-empty provider response."""
    price, as_of = _latest_price(records)
    if price is None:
        return
    payload = {
        "symbol": symbol,
        "interval": interval,
        "source": source,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of,
        "price": price,
        "records": records,
    }
    try:
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        target = _cache_file(symbol, interval)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=_CACHE_ROOT, delete=False, suffix=".tmp"
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
            temp_name = handle.name
        Path(temp_name).replace(target)
    except OSError:
        logger.debug("could not write market-data cache for %s", symbol, exc_info=True)


def _read_cache(symbol: str, interval: str) -> dict[str, Any] | None:
    """Load the most recent verified cache entry, if it remains readable."""
    try:
        payload = json.loads(_cache_file(symbol, interval).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("symbol") != symbol:
        return None
    if not isinstance(payload.get("records"), list) or not payload["records"]:
        return None
    try:
        price = float(payload.get("price"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None
    return payload


def _google_finance_candidates(symbol: str) -> list[str]:
    """Translate project symbols into Google Finance quote identifiers."""
    upper = symbol.upper()
    if upper.endswith(".NS"):
        return [f"{upper[:-3]}:NSE"]
    if upper.endswith(".BO"):
        return [f"{upper[:-3]}:BOM"]
    if upper.endswith(".HK"):
        return [f"{upper[:-3].lstrip('0') or '0'}:HKG"]
    if upper.endswith(".US"):
        ticker = upper[:-3]
        return [f"{ticker}:NASDAQ", f"{ticker}:NYSE"]
    if upper.startswith("^"):
        return []
    return []


def _google_finance_snapshot(symbol: str) -> dict[str, Any] | None:
    """Fetch a current public quote snapshot when historical feeds are empty."""
    for quote_id in _google_finance_candidates(symbol):
        url = f"https://www.google.com/finance/quote/{quote_id}?hl=en"
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            html = urllib.request.urlopen(request, timeout=6).read().decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001 - continue to the next exchange/provider
            continue
        match = re.search(r'data-last-price="([0-9]+(?:\.[0-9]+)?)"', html)
        if match is None:
            match = re.search(r'class="YMlKec fxKbKc"[^>]*>[^0-9]*([0-9][0-9,]*(?:\.[0-9]+)?)<', html)
        if match is None:
            continue
        try:
            price = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if price > 0 and math.isfinite(price):
            return {
                "price": price,
                "source": "google_finance",
                "as_of": datetime.now(timezone.utc).isoformat(),
                "freshness": "live_snapshot",
                "url": url,
            }
    return None


def fetch_market_data(
    *,
    codes: list[str],
    start_date: str,
    end_date: str,
    source: str = "auto",
    interval: str = "1D",
    max_rows: int = DEFAULT_MAX_ROWS,
    loader_resolver: Callable[[str], type] = get_loader,
) -> dict[str, Any]:
    """Fetch normalized OHLCV data through the repository loader layer."""
    from backtest.engines._market_hooks import normalize_market_symbol

    codes = [normalize_market_symbol(code) for code in codes]
    results: dict[str, Any] = {}
    source_by_symbol: dict[str, str] = {}
    use_resilient_fallbacks = loader_resolver is get_loader

    if source == "auto":
        groups: dict[str, list[str]] = {}
        for code in codes:
            src = detect_source(code)
            groups.setdefault(src, []).append(code)
    else:
        groups = {source: list(codes)}

    for src, src_codes in groups.items():
        data_map: dict[str, Any] = {}
        primary_name = src
        try:
            loader_cls = loader_resolver(src)
            loader = loader_cls()
            primary_name = str(getattr(loader, "name", src))
            data_map = loader.fetch(src_codes, start_date, end_date, interval=interval) or {}
            for symbol, frame in data_map.items():
                if _usable_frame(frame):
                    source_by_symbol[symbol] = primary_name
        except Exception:
            logger.exception(
                "market-data loader %r failed for %s; codes remain unresolved",
                src,
                src_codes,
            )
            data_map = {}

        # A loader can be importable/credential-free yet return nothing when
        # its endpoint is blocked or a symbol is unsupported.  The registry's
        # normal fallback only covers construction/is_available(), so continue
        # through same-market providers at runtime for unresolved symbols too.
        # Injected resolvers used by tests/callers keep their exact behavior.
        if use_resilient_fallbacks and src not in {"local", "qveris"}:
            missing = [code for code in src_codes if not _usable_frame(data_map.get(code))]
            if missing:
                from backtest.engines._market_hooks import _detect_market
                from backtest.loaders import registry

                registry._ensure_registered()
                by_market: dict[str, list[str]] = {}
                for code in missing:
                    by_market.setdefault(_detect_market(code), []).append(code)
                for market, market_codes in by_market.items():
                    remaining = list(market_codes)
                    for fallback_name in registry.FALLBACK_CHAINS.get(market, []):
                        if not remaining:
                            break
                        if fallback_name in {src, primary_name}:
                            continue
                        fallback_cls = registry.LOADER_REGISTRY.get(fallback_name)
                        if fallback_cls is None:
                            continue
                        try:
                            fallback_loader = fallback_cls()
                            if not fallback_loader.is_available():
                                continue
                            fallback_data = fallback_loader.fetch(
                                remaining,
                                start_date,
                                end_date,
                                interval=interval,
                            )
                        except Exception as exc:  # noqa: BLE001 - keep walking the chain
                            logger.debug(
                                "market-data runtime fallback %r failed for %s: %s",
                                fallback_name,
                                remaining,
                                exc,
                            )
                            continue
                        if fallback_data:
                            for symbol, frame in fallback_data.items():
                                if _usable_frame(frame):
                                    data_map[symbol] = frame
                                    source_by_symbol[symbol] = fallback_name
                            remaining = [code for code in remaining if not _usable_frame(data_map.get(code))]

        for symbol, df in data_map.items():
            if not _usable_frame(df):
                continue
            records = df.reset_index().to_dict(orient="records")
            for row in records:
                for key, value in row.items():
                    row[key] = _json_safe(value)
            results[symbol] = cap_rows(records, max_rows)
            if use_resilient_fallbacks:
                _write_cache(symbol, interval, records, source_by_symbol.get(symbol, primary_name))

    unresolved = [code for code in codes if code not in results]
    price_points: dict[str, dict[str, Any]] = {}
    for code in codes:
        visible = results.get(code)
        rows = visible.get("data", []) if isinstance(visible, dict) else visible
        rows = rows if isinstance(rows, list) else []
        price, as_of = _latest_price(rows)
        if price is not None:
            price_points[code] = {
                "status": "ok",
                "price": price,
                "source": source_by_symbol.get(code, source),
                "as_of": as_of,
                "freshness": "provider_history",
            }
            continue

        snapshot = _google_finance_snapshot(code) if use_resilient_fallbacks else None
        if snapshot is not None:
            price_points[code] = {"status": "ok", **snapshot}
            continue

        cached = _read_cache(code, interval) if use_resilient_fallbacks else None
        if cached is not None:
            cached_rows = cached["records"]
            results[code] = cap_rows(cached_rows, max_rows)
            price_points[code] = {
                "status": "ok",
                "price": cached["price"],
                "source": f"cached:{cached.get('source', 'public_provider')}",
                "as_of": cached.get("as_of") or cached.get("retrieved_at"),
                "freshness": "stale_verified_cache",
                "retrieved_at": cached.get("retrieved_at"),
            }
            continue

        price_points[code] = {
            "status": "unavailable",
            "price": None,
            "source": "public_fallback_chain",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "freshness": "unavailable",
            "note": "No provider or verified cache returned a positive price; field is explicit, never blank.",
        }

    unresolved = [code for code in codes if code not in results]
    if unresolved:
        results["_unresolved"] = unresolved
    results["_price_points"] = price_points
    results["_source_policy"] = {
        "order": [
            "market-specific public history chain",
            "Google Finance quote snapshot",
            "last verified local cache",
        ],
        "blank_price_fields": False,
    }

    return results


def fetch_market_data_json(**kwargs: Any) -> str:
    """Fetch market data and return strict JSON."""
    return json.dumps(fetch_market_data(**kwargs), ensure_ascii=False, indent=2, allow_nan=False)

