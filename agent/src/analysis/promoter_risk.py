"""Promoter shareholding & pledge risk analysis (India equities).

Why this matters
----------------
Promoter pledging is the highest-signal, most India-specific governance red flag
there is: promoters borrow against their own shares, and when the price falls the
lender sells the collateral into the fall. Zee, DHFL and Yes Bank all telegraphed
their collapse through rising pledge levels quarters before the price broke. It
is barely covered by global research tools, and where it is covered it is shown
as a single stale percentage rather than a *trend* with an escalation signal.

This module is the provider-agnostic analysis core: it takes normalised
quarterly shareholding records and derives the risk view an analyst actually
needs — pledge intensity, direction of travel, promoter stake erosion, and
institutional flow. It performs no I/O, so it is exhaustively testable and
outlives any one data source's schema.

Record shape (all fields optional except ``period``)::

    {"period": "2024-03-31",       # quarter end (any parseable date)
     "promoter_pct": 54.2,          # promoter+group holding, % of total equity
     "pledged_pct_of_promoter": 12.5,   # pledged as % of PROMOTER holding
     "pledged_pct_of_total": 6.8,       # pledged as % of TOTAL equity (derived if absent)
     "fii_pct": 18.1, "dii_pct": 12.4, "public_pct": 15.3}

The two pledge conventions are the classic reporting trap — Indian filings quote
pledge as a percentage of *promoter* holding while screeners often show it as a
percentage of *total* equity, and confusing them understates risk by ~2x. This
module keeps both explicit and derives whichever is missing.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

# Pledge as % of promoter holding. Thresholds reflect market convention:
# any pledge invites scrutiny, >25% is a recognised governance concern, and
# >50% means a moderate drawdown can trigger forced lender selling.
PLEDGE_WATCH = 10.0
PLEDGE_HIGH = 25.0
PLEDGE_SEVERE = 50.0

# Quarter-on-quarter change (percentage points) that counts as a real move
# rather than rounding noise in the filing.
PLEDGE_MATERIAL_DELTA = 2.0
STAKE_MATERIAL_DELTA = 1.0


def _num(value: Any) -> Optional[float]:
    """Coerce to a finite float, else None (filings carry '-', '', NA)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("%", "")
        if not cleaned or cleaned in {"-", "--", "NA", "N.A.", "nan"}:
            return None
        try:
            value = float(cleaned)
        except ValueError:
            return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def normalize_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clean, derive and chronologically order shareholding records.

    Derives whichever pledge convention is missing from the other using the
    promoter stake, so downstream logic can always rely on
    ``pledged_pct_of_promoter``.
    """
    out: List[Dict[str, Any]] = []
    for raw in records or []:
        if not isinstance(raw, dict):
            continue
        period = raw.get("period") or raw.get("date") or raw.get("quarter")
        if not period:
            continue
        promoter = _num(raw.get("promoter_pct"))
        of_promoter = _num(raw.get("pledged_pct_of_promoter"))
        of_total = _num(raw.get("pledged_pct_of_total"))

        # Derive the missing convention (needs a non-zero promoter stake).
        if of_promoter is None and of_total is not None and promoter:
            of_promoter = of_total / promoter * 100.0
        if of_total is None and of_promoter is not None and promoter is not None:
            of_total = of_promoter * promoter / 100.0

        out.append({
            "period": str(period),
            "promoter_pct": promoter,
            "pledged_pct_of_promoter": of_promoter,
            "pledged_pct_of_total": of_total,
            "fii_pct": _num(raw.get("fii_pct")),
            "dii_pct": _num(raw.get("dii_pct")),
            "public_pct": _num(raw.get("public_pct")),
        })
    out.sort(key=lambda r: _sort_key(r["period"]))
    return out


# Filings quote quarter ends in several shapes; ``30-JUN-2026`` sorted as a
# string lands before ``31-MAR-2026``, which silently mislabels the latest
# quarter and inverts every quarter-on-quarter delta. Parse to a real date.
_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


def _sort_key(period: Any) -> tuple:
    """Chronological sort key; unparseable periods sort last but stay stable."""
    text = str(period).strip()
    # ISO first: 2024-03-31
    try:
        parts = text.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return (0, int(parts[0]), int(parts[1]), int(parts[2]))
        # DD-MON-YYYY: 31-MAR-2024
        if len(parts) == 3 and parts[1].upper()[:3] in _MONTHS:
            return (0, int(parts[2]), _MONTHS[parts[1].upper()[:3]], int(parts[0]))
    except (ValueError, KeyError):
        pass
    return (1, 0, 0, 0)


def _severity(pledge_of_promoter: Optional[float]) -> str:
    if pledge_of_promoter is None:
        return "unknown"
    if pledge_of_promoter >= PLEDGE_SEVERE:
        return "severe"
    if pledge_of_promoter >= PLEDGE_HIGH:
        return "high"
    if pledge_of_promoter >= PLEDGE_WATCH:
        return "watch"
    if pledge_of_promoter > 0:
        return "low"
    return "none"


def _trend(series: List[Optional[float]]) -> Optional[float]:
    """Change from the first to the last non-null observation."""
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return None
    return vals[-1] - vals[0]


def analyze_promoter_risk(records: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive the promoter pledge / shareholding risk view.

    Returns a JSON-safe dict with the latest snapshot, quarter-on-quarter and
    full-window trends, discrete risk flags, and a plain-language assessment.
    Never raises: missing or malformed fields degrade to ``None``/``unknown``.
    """
    rows = normalize_records(records)
    if not rows:
        return {"status": "no_data", "flags": [], "assessment": "No shareholding records supplied."}

    latest = rows[-1]
    prior = rows[-2] if len(rows) > 1 else None
    pledge = latest.get("pledged_pct_of_promoter")
    severity = _severity(pledge)

    pledge_qoq = None
    stake_qoq = None
    if prior:
        if pledge is not None and prior.get("pledged_pct_of_promoter") is not None:
            pledge_qoq = pledge - prior["pledged_pct_of_promoter"]
        if latest.get("promoter_pct") is not None and prior.get("promoter_pct") is not None:
            stake_qoq = latest["promoter_pct"] - prior["promoter_pct"]

    flags: List[str] = []
    if severity in ("high", "severe"):
        flags.append(f"pledge_{severity}")
    elif severity == "watch":
        flags.append("pledge_watch")
    if pledge_qoq is not None and pledge_qoq >= PLEDGE_MATERIAL_DELTA:
        flags.append("pledge_rising")
    if stake_qoq is not None and stake_qoq <= -STAKE_MATERIAL_DELTA:
        flags.append("promoter_stake_falling")
    # The classic pre-blowup combination: promoters both pledging more and
    # selling down — leverage rising exactly as commitment falls.
    if "pledge_rising" in flags and "promoter_stake_falling" in flags:
        flags.append("escalating_governance_risk")

    pledge_trend = _trend([r.get("pledged_pct_of_promoter") for r in rows])
    stake_trend = _trend([r.get("promoter_pct") for r in rows])
    fii_trend = _trend([r.get("fii_pct") for r in rows])
    dii_trend = _trend([r.get("dii_pct") for r in rows])

    return {
        "status": "ok",
        "periods_analyzed": len(rows),
        "latest_period": latest["period"],
        "latest": latest,
        "pledge_severity": severity,
        "pledge_pct_of_promoter": pledge,
        "pledge_pct_of_total_equity": latest.get("pledged_pct_of_total"),
        "pledge_qoq_change": pledge_qoq,
        "promoter_stake_qoq_change": stake_qoq,
        "pledge_trend_window": pledge_trend,
        "promoter_stake_trend_window": stake_trend,
        "fii_trend_window": fii_trend,
        "dii_trend_window": dii_trend,
        "flags": flags,
        "assessment": _assessment(severity, pledge, pledge_qoq, stake_qoq, flags),
    }


def _assessment(
    severity: str,
    pledge: Optional[float],
    pledge_qoq: Optional[float],
    stake_qoq: Optional[float],
    flags: List[str],
) -> str:
    """One paragraph an analyst can paste into a note."""
    if severity == "unknown":
        return "Pledge level not disclosed in the supplied records; treat as unverified rather than zero."
    if severity == "none":
        base = "No promoter pledging reported"
    else:
        base = f"Promoters have pledged {pledge:.1f}% of their holding ({severity} by market convention)"
    moves: List[str] = []
    if pledge_qoq is not None and abs(pledge_qoq) >= PLEDGE_MATERIAL_DELTA:
        moves.append(f"pledge {'rose' if pledge_qoq > 0 else 'fell'} {abs(pledge_qoq):.1f}pp QoQ")
    if stake_qoq is not None and abs(stake_qoq) >= STAKE_MATERIAL_DELTA:
        moves.append(f"promoter stake {'rose' if stake_qoq > 0 else 'fell'} {abs(stake_qoq):.1f}pp QoQ")
    tail = f"; {', '.join(moves)}" if moves else ""
    if "escalating_governance_risk" in flags:
        tail += (
            ". Promoters are pledging more while selling down — historically the "
            "combination that precedes forced lender selling. Treat as a primary risk."
        )
    elif severity == "severe":
        tail += ". At this level a moderate drawdown can trigger forced sales by lenders."
    return base + tail + ("." if not tail.endswith(".") else "")
