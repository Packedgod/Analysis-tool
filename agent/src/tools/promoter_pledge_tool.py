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
# Pledge disclosures live on a separate endpoint from the shareholding pattern.
_PLEDGE_URL = f"{_BASE}/api/corporate-pledgedata"

# Field aliases seen across NSE payloads / screener exports, mapped to the
# analysis core's canonical names. Matching is case/space/underscore-insensitive.
_FIELD_ALIASES: Dict[str, str] = {
    "period": "period", "date": "period", "quarter": "period", "asondate": "period",
    "promoterpct": "promoter_pct", "promoterandpromotergroup": "promoter_pct",
    "promoterholding": "promoter_pct", "promoters": "promoter_pct",
    # NSE's corporate-share-holdings-master spells the promoter and public
    # columns this way; verified against live payloads for NSE equities.
    "prandprgrp": "promoter_pct", "publicval": "public_pct",
    # NSE's corporate-pledgedata. `shp` is the shareholding-pattern quarter and
    # `percSharesPledged` is pledged as a percentage of TOTAL issued shares —
    # verified arithmetically (numSharesPledged / totIssuedShares), not of
    # promoter holding. Mapping it to the wrong convention would understate
    # pledge risk by roughly the inverse of the promoter stake (~2x).
    "shp": "period", "percpromoterholding": "promoter_pct",
    "percsharespledged": "pledged_pct_of_total",
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
    """Best-effort NSE shareholding-pattern fetch; [] on any failure."""
    return _fetch_nse_endpoint(symbol, _SHAREHOLDING_URL)


def _fetch_nse_endpoint(symbol: str, url: str) -> List[Dict[str, Any]]:
    """Best-effort fetch of one NSE corporate endpoint; [] on any failure.

    Never raises: these endpoints are undocumented and rate-limited, and a gap
    must degrade to "unknown" rather than break the caller.
    """
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
                url,
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
        raw = payload
        if isinstance(payload, dict):
            raw = next(
                (payload[key] for key in ("data", "records", "shareholdings")
                 if isinstance(payload.get(key), list)),
                None,
            )
            if raw is None:
                return []
        rows = normalize_payload_rows(raw)
        # Loud on drift: rows that parse structurally but carry no recognised
        # value column mean the provider renamed something. Log the offending
        # keys so a rename is a one-line fix instead of a re-probe.
        if rows and not has_mapped_values(rows):
            logger.warning(
                "possible schema drift at %s for %s: no recognised value columns; "
                "unmapped keys seen: %s",
                url, symbol, unmapped_keys(raw),
            )
        return rows
    return []


# The fields that carry actual signal. A payload that yields periods but none
# of these has not "returned no pledging" — it has failed to parse, and saying
# so is the difference between a safe degradation and a false clean reading.
_VALUE_FIELDS = (
    "promoter_pct", "pledged_pct_of_promoter", "pledged_pct_of_total",
    "fii_pct", "dii_pct", "public_pct",
)


def has_mapped_values(rows: List[Dict[str, Any]]) -> bool:
    """Whether any row carries at least one usable value field."""
    return any(row.get(field) is not None for row in rows for field in _VALUE_FIELDS)


def unmapped_keys(raw_rows: Any, limit: int = 12) -> List[str]:
    """Keys present in the provider payload that no alias recognises.

    Surfaced in the drift diagnostic so a rename is immediately actionable
    rather than requiring someone to re-probe the endpoint by hand.
    """
    seen: List[str] = []
    if not isinstance(raw_rows, list):
        return seen
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            if _FIELD_ALIASES.get(_canonical_key(key)) is None and key not in seen:
                seen.append(key)
    return seen[:limit]


def _period_key(period: Any) -> str:
    """Normalise a quarter label so the two NSE feeds can be joined.

    Shareholding quotes ``30-JUN-2026`` and pledge quotes ``30-Jun-2026``; a
    case-sensitive join would silently never match and drop every pledge value.
    """
    return str(period).strip().upper()


def _fetch_nse_pledge(symbol: str) -> List[Dict[str, Any]]:
    """Best-effort NSE pledge-disclosure fetch; [] on any failure."""
    return _fetch_nse_endpoint(symbol, _PLEDGE_URL)


def _merge_pledge(
    shareholding: List[Dict[str, Any]], pledge: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Overlay pledge disclosures onto the shareholding series by quarter.

    The two NSE feeds are separate: shareholding carries many quarters, pledge
    typically only the latest disclosure. Quarters without a pledge row keep a
    ``None`` pledge — deliberately *not* zero, since "not disclosed" and "no
    pledging" are different claims and conflating them is the failure mode this
    whole panel exists to prevent.
    """
    by_period = {_period_key(row.get("period")): row for row in pledge if row.get("period")}
    if not by_period:
        return shareholding
    merged: List[Dict[str, Any]] = []
    for row in shareholding:
        match = by_period.get(_period_key(row.get("period")))
        if match:
            row = {**row, **{k: v for k, v in match.items() if k != "period" and v is not None}}
        merged.append(row)
    # A pledge disclosure for a quarter absent from the shareholding series is
    # still evidence; keep it rather than discarding the newest datapoint.
    known = {_period_key(r.get("period")) for r in shareholding}
    merged.extend(row for key, row in by_period.items() if key not in known)
    return merged


def get_promoter_pledge(symbol: str | None, records: Any) -> str:
    """Analyse promoter pledge risk from supplied records or an NSE fetch."""
    rows = normalize_payload_rows(records) if records else []
    source = "supplied_records"
    if not rows and symbol:
        rows = _merge_pledge(_fetch_nse_shareholding(symbol), _fetch_nse_pledge(symbol))
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

    # Rows arrived but nothing mapped: the provider renamed its columns. This
    # must NOT read as a successful analysis with empty values — that is the
    # failure mode that silently reports "unknown" pledging on a live company.
    if not has_mapped_values(rows):
        return json.dumps({
            "status": "schema_drift",
            "symbol": symbol,
            "source": source,
            "periods_seen": len(rows),
            "error": (
                f"Fetched {len(rows)} period(s) but no recognised value columns — the "
                "upstream schema has changed. Treat pledge and shareholding as UNKNOWN, "
                "not as zero. Update _FIELD_ALIASES in promoter_pledge_tool (the "
                "unmapped keys are in the warning log) or supply `records` directly."
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
