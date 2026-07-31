"""Agent tool: Indian promoter shareholding & pledge risk.

Promoter pledging is the highest-signal India-specific governance red flag, and
it is chronically under-covered: most tools show one stale percentage, if any.
This tool surfaces the *trend* — pledge intensity, quarter-on-quarter direction,
promoter stake erosion and institutional flow — plus the escalation pattern
(pledging up while promoters sell down) that has preceded India's most notable
blow-ups.

Two input modes:

* ``records`` — supply normalised quarterly shareholding rows directly (from a
  filing, a screener, or another tool). Fully offline, no network.
* ``symbol`` — best-effort fetch from NSE's public corporate-filings API,
  reusing the shared throttled/cookie-primed session the NSE loader already
  establishes.

The fetch adapter is deliberately thin and defensive: NSE's corporate endpoints
are undocumented and their JSON shape drifts, so a schema change degrades to a
clean ``status="unavailable"`` telling the caller to supply ``records`` — it
never fabricates or guesses a pledge level. All analysis lives in the
provider-agnostic :mod:`src.analysis.promoter_risk` core.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from src.agent.tools import BaseTool
from src.analysis.promoter_risk import analyze_promoter_risk

logger = logging.getLogger(__name__)

_BASE = "https://www.nseindia.com"
_SHAREHOLDING_URL = f"{_BASE}/api/corporate-share-holdings-master"

# Field aliases seen across NSE payloads / screener exports, mapped to the
# analysis core's canonical names. Matching is case/space/underscore-insensitive.
_FIELD_ALIASES: Dict[str, str] = {
    "period": "period", "date": "period", "quarter": "period", "asondate": "period",
    "promoterpct": "promoter_pct", "promoterandpromotergroup": "promoter_pct",
    "promoterholding": "promoter_pct", "promoters": "promoter_pct",
    # NSE's corporate-share-holdings-master spells the promoter and public
    # columns this way; verified against live payloads for NSE equities.
    "prandprgrp": "promoter_pct", "publicval": "public_pct",
    "pledgedpctofpromoter": "pledged_pct_of_promoter",
    "pledgedpromoter": "pledged_pct_of_promoter",
    "pledged": "pledged_pct_of_promoter",
    "pledgedpctoftotal": "pledged_pct_of_total",
    "fiipct": "fii_pct", "fii": "fii_pct", "foreign": "fii_pct",
    "diipct": "dii_pct", "dii": "dii_pct",
    "publicpct": "public_pct", "public": "public_pct",
}


def _canonical_key(key: str) -> str:
    return str(key).strip().lower().replace("_", "").replace(" ", "").replace("%", "")


def normalize_payload_rows(rows: Any) -> List[Dict[str, Any]]:
    """Map arbitrary provider rows onto the analysis core's field names.

    Unknown keys are dropped rather than guessed; a row that yields no
    recognisable period is skipped entirely.
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        mapped: Dict[str, Any] = {}
        for key, value in row.items():
            canon = _FIELD_ALIASES.get(_canonical_key(key))
            if canon and (canon not in mapped or mapped[canon] in (None, "")):
                mapped[canon] = value
        if mapped.get("period"):
            out.append(mapped)
    return out


def _fetch_nse_shareholding(symbol: str) -> List[Dict[str, Any]]:
    """Best-effort NSE fetch; returns [] on any failure (never raises)."""
    try:
        from backtest.loaders._http import resolve_min_interval, throttled_get
        from backtest.loaders.nse_loader import _prime_session  # reuse primed cookie jar
    except Exception as exc:  # noqa: BLE001 — optional dependency path
        logger.debug("promoter pledge: NSE client unavailable: %s", exc)
        return []

    bare = symbol.strip().upper()
    bare = bare[:-3] if bare.endswith(".NS") else bare
    min_interval = resolve_min_interval("VANTAGE_NSE_MIN_INTERVAL", 1.0)
    for attempt in range(2):
        try:
            _prime_session(force=attempt > 0)
            resp = throttled_get(
                _SHAREHOLDING_URL,
                host_key="nse",
                min_interval=min_interval,
                params={"index": "equities", "symbol": bare},
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": f"{_BASE}/get-quotes/equity",
                },
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001 — network is best-effort
            logger.debug("promoter pledge fetch failed for %s: %s", bare, exc)
            return []
        if resp.status_code in (401, 403) and attempt == 0:
            continue  # stale anti-bot cookie — re-prime once
        if resp.status_code != 200:
            return []
        try:
            payload = resp.json()
        except ValueError:
            return []
        # Accept either a bare list or the common {"data": [...]} envelope.
        if isinstance(payload, dict):
            for key in ("data", "records", "shareholdings"):
                if isinstance(payload.get(key), list):
                    return normalize_payload_rows(payload[key])
            return []
        return normalize_payload_rows(payload)
    return []


def get_promoter_pledge(symbol: str | None, records: Any) -> str:
    """Analyse promoter pledge risk from supplied records or an NSE fetch."""
    rows = normalize_payload_rows(records) if records else []
    source = "supplied_records"
    if not rows and symbol:
        rows = _fetch_nse_shareholding(symbol)
        source = "nse_corporate_api"
    if not rows:
        return json.dumps({
            "status": "unavailable",
            "symbol": symbol,
            "error": (
                "No shareholding records available. NSE's corporate endpoint is "
                "undocumented and may have changed shape or blocked the request; "
                "supply quarterly rows via `records` "
                "([{period, promoter_pct, pledged_pct_of_promoter, ...}]) to analyse."
            ),
        }, ensure_ascii=False)

    result = analyze_promoter_risk(rows)
    return json.dumps(
        {"status": "ok", "symbol": symbol, "source": source, **result}, ensure_ascii=False
    )


class PromoterPledgeTool(BaseTool):
    """Indian promoter shareholding / pledge governance-risk analysis."""

    name = "get_promoter_pledge"
    description = (
        "Analyse Indian promoter shareholding and share-pledge risk — the "
        "highest-signal India-specific governance red flag (rising pledges "
        "preceded Zee/DHFL/Yes Bank). Returns pledge severity, quarter-on-quarter "
        "pledge and promoter-stake changes, FII/DII trend, discrete risk flags "
        "(including the escalating pattern of pledging up while promoters sell "
        "down), and a written assessment. Pass `symbol` (e.g. 'RELIANCE.NS') for a "
        "best-effort NSE fetch, or `records` with quarterly rows to analyse "
        "filing data directly. Pledge is reported both as % of promoter holding "
        "(the filing convention) and % of total equity."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "NSE symbol, e.g. 'RELIANCE.NS' or 'RELIANCE'.",
            },
            "records": {
                "type": "array",
                "items": {"type": "object"},
                "description": (
                    "Quarterly shareholding rows: {period, promoter_pct, "
                    "pledged_pct_of_promoter or pledged_pct_of_total, fii_pct, "
                    "dii_pct}. Takes precedence over symbol; use for filing data."
                ),
            },
        },
        "required": [],
    }
    is_readonly = True
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        """Run the pledge-risk analysis and return a JSON envelope."""
        try:
            return get_promoter_pledge(kwargs.get("symbol"), kwargs.get("records"))
        except Exception as exc:  # noqa: BLE001 — surface a clean tool error
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
