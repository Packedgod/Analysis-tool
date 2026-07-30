"""suggest_stocks: rank a candidate universe on the backend's quantitative factors.

This screens a supplied list of tickers on transparent, verifiable price-based
factors (risk-adjusted return, 12-1 momentum, trend vs. 200-day average,
drawdown control, volatility), cross-sectionally scores them, and returns a
ranked suggestion set. Every figure is computed from real fetched OHLCV — the
tool never invents a ranking. It complements (does not replace) the full
factor-workbook analysis and is not investment advice.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from typing import Any

from src.agent.tools import BaseTool

# Composite weights — quality of signal over raw return: reward risk-adjusted
# momentum and trend, penalise drawdown and volatility.
_FACTOR_WEIGHTS = {
    "risk_adjusted_return": 0.30,
    "momentum_12_1": 0.25,
    "trend_vs_200dma": 0.20,
    "max_drawdown": 0.15,   # less-negative is better (handled in scoring)
    "volatility": 0.10,     # lower is better (handled in scoring)
}
_LOWER_IS_BETTER = {"volatility"}  # max_drawdown handled as "less negative"


def _closes(records: list[dict[str, Any]]) -> list[float]:
    rows = sorted(
        (r for r in records if r.get("close") is not None),
        key=lambda r: str(r.get("trade_date") or r.get("date") or ""),
    )
    out: list[float] = []
    for r in rows:
        try:
            value = float(r["close"])
        except (TypeError, ValueError):
            continue
        if value > 0:
            out.append(value)
    return out


def _factors(closes: list[float]) -> dict[str, float] | None:
    """Compute price factors from a close series; None when too short."""
    n = len(closes)
    if n < 60:  # need a meaningful history to rank on
        return None
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, n)]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    daily_vol = math.sqrt(var)
    ann_vol = daily_vol * math.sqrt(252)
    total_return = closes[-1] / closes[0] - 1.0
    base = max(1.0 + total_return, 1e-9)
    ann_return = base ** (252.0 / n) - 1.0
    risk_adjusted = ann_return / ann_vol if ann_vol > 1e-9 else 0.0

    peak = closes[0]
    max_dd = 0.0
    for price in closes:
        peak = max(peak, price)
        max_dd = min(max_dd, price / peak - 1.0)

    # 12-1 momentum: return from ~12 months ago to ~1 month ago (skip last month).
    look_12 = min(n - 1, 252)
    look_1 = min(21, look_12 - 1)
    mom = closes[-1 - look_1] / closes[-1 - look_12] - 1.0 if look_12 > look_1 >= 0 else 0.0

    sma_window = min(200, n)
    sma200 = sum(closes[-sma_window:]) / sma_window
    trend = closes[-1] / sma200 - 1.0 if sma200 > 0 else 0.0

    dist_high = closes[-1] / max(closes) - 1.0

    return {
        "risk_adjusted_return": round(risk_adjusted, 4),
        "momentum_12_1": round(mom, 4),
        "trend_vs_200dma": round(trend, 4),
        "max_drawdown": round(max_dd, 4),
        "volatility": round(ann_vol, 4),
        "annual_return": round(ann_return, 4),
        "total_return": round(total_return, 4),
        "distance_from_52w_high": round(dist_high, 4),
    }


def _rank_scores(rows: list[dict[str, Any]]) -> None:
    """Min-max normalise each factor across candidates and set a composite score."""
    for factor, weight in _FACTOR_WEIGHTS.items():
        values = [r["factors"][factor] for r in rows]
        if factor == "max_drawdown":
            values = [v for v in values]  # less-negative better -> higher raw = better
        lo, hi = min(values), max(values)
        span = hi - lo
        for r in rows:
            raw = r["factors"][factor]
            norm = 0.5 if span == 0 else (raw - lo) / span
            if factor in _LOWER_IS_BETTER:
                norm = 1.0 - norm
            r.setdefault("_score", 0.0)
            r["_score"] += weight * norm
    rows.sort(key=lambda r: r["_score"], reverse=True)
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        r["score"] = round(r.pop("_score") * 100, 1)


def _sector_benchmark(sector: str) -> str | None:
    try:
        from src.analysis.master_factors import factor_pack
        pack = factor_pack(sector)
        for item in pack.get("sector_map", []):
            if item.get("Sector Name") == pack.get("matched_sector"):
                return item.get("Benchmark Index")
    except Exception:  # noqa: BLE001
        return None
    return None


class SuggestStocksTool(BaseTool):
    """Rank a candidate universe on the backend's quantitative factors."""

    name = "suggest_stocks"
    description = (
        "Suggest the best stocks from a candidate list by scoring each on the "
        "backend's quantitative factors (risk-adjusted return, 12-1 momentum, "
        "trend vs 200-day average, drawdown control, volatility) computed from "
        "real fetched OHLCV, then ranking cross-sectionally. Use for 'which of "
        "these are best to buy now' style screens. Returns ranked suggestions "
        "with a transparent per-factor breakdown. Not investment advice; pair "
        "with prepare_analysis_backbone for a full workbook-driven analysis. "
        'Example: {"codes": ["RELIANCE.NS","TCS.NS","HDFCBANK.NS"], "top_n": 3}.'
    )
    repeatable = True
    is_readonly = True
    parameters = {
        "type": "object",
        "properties": {
            "codes": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "description": "Candidate tickers with market suffix (e.g. 'RELIANCE.NS', 'TCS.NS').",
            },
            "top_n": {"type": "integer", "default": 5, "description": "How many suggestions to return."},
            "sector": {
                "type": "string",
                "description": "Optional workbook sector for benchmark context (e.g. 'Financial Services').",
            },
            "lookback_days": {
                "type": "integer",
                "default": 500,
                "description": "Calendar days of price history to score on (default ~2y).",
            },
        },
        "required": ["codes"],
    }

    def execute(self, **kwargs: Any) -> str:
        codes = kwargs.get("codes") or []
        codes = [str(c).strip() for c in codes if str(c).strip()]
        codes = list(dict.fromkeys(codes))  # de-dup, preserve order
        if len(codes) < 2:
            return json.dumps({"status": "error", "error": "provide at least 2 candidate codes"}, ensure_ascii=False)
        top_n = max(1, int(kwargs.get("top_n", 5)))
        sector = str(kwargs.get("sector") or "").strip()
        lookback = max(120, int(kwargs.get("lookback_days", 500)))

        end = date.today()
        start = end - timedelta(days=lookback)
        from src.market_data import fetch_market_data

        try:
            fetched = fetch_market_data(
                codes=codes, start_date=start.isoformat(), end_date=end.isoformat(),
                source="auto", max_rows=0,  # 0 = full series (no down-sampling)
            )
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"status": "error", "error": f"market-data fetch failed: {exc}"}, ensure_ascii=False)

        rows: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        for code in codes:
            value = fetched.get(code)
            # fetch_market_data returns a bare record list, or a capped envelope
            # {rows, returned, truncated, data:[...]} when the series is large.
            records = value.get("data") if isinstance(value, dict) else value
            if not isinstance(records, list) or not records:
                excluded.append({"code": code, "reason": "no price data available"})
                continue
            closes = _closes(records)
            factors = _factors(closes)
            if factors is None:
                excluded.append({"code": code, "reason": "insufficient price history to score"})
                continue
            rows.append({"code": code, "factors": factors})

        if len(rows) < 2:
            return json.dumps({
                "status": "unavailable",
                "reason": "fewer than 2 candidates had scorable data",
                "excluded": excluded,
            }, ensure_ascii=False)

        _rank_scores(rows)
        suggestions = [
            {"rank": r["rank"], "code": r["code"], "score": r["score"], "factors": r["factors"]}
            for r in rows[:top_n]
        ]
        payload = {
            "status": "ok",
            "sector": sector or None,
            "benchmark": _sector_benchmark(sector) if sector else None,
            "evaluated": len(rows),
            "candidates_supplied": len(codes),
            "weights": _FACTOR_WEIGHTS,
            "methodology": (
                "Each factor is computed from fetched OHLCV, min-max normalised across the "
                "evaluated candidates, and combined with the shown weights into a 0-100 score. "
                "Higher is better; volatility and drawdown are penalised."
            ),
            "suggestions": suggestions,
            "excluded": excluded,
            "disclaimer": "Quantitative screen on verifiable price factors. Not investment advice.",
        }
        return json.dumps(payload, ensure_ascii=False)
