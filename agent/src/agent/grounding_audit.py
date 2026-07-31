"""Numeric-provenance audit: is every figure in an answer traceable to a source?

An analyst-grade research tool must never emit a number it cannot source. LLMs
will confidently state figures from training data or invention, and a single
wrong number in front of a professional destroys trust. This module is the
*output-side* complement to :mod:`src.swarm.grounding` (which feeds real data
*in*): it extracts the numeric claims from a generated answer and checks each
against the material the agent actually fetched, producing an auditable
grounding report.

Design stance (v1): **observe, do not censor.** The report scores grounding and
lists un-sourced figures so a caller can log, flag, or gate on it — but this
module never mutates an answer. It is deliberately conservative about what
counts as a "claim" (years, list indices and enumeration markers are excluded)
and tolerant when matching (rounding and thousands separators are normalised),
so the ungrounded list is high-signal rather than noisy. Derived numbers
(computed from two sourced figures) can still show as ungrounded — that is a
known limitation of a purely lexical check and precisely why v1 observes
rather than blocks.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

# Magnitude words → multiplier. Indian (crore/lakh) and Western scales both
# appear in this product's outputs.
_MAGNITUDES: Dict[str, float] = {
    "k": 1e3,
    "thousand": 1e3,
    "lakh": 1e5,
    "lac": 1e5,
    "mn": 1e6,
    "million": 1e6,
    "m": 1e6,
    "cr": 1e7,
    "crore": 1e7,
    "bn": 1e9,
    "billion": 1e9,
    "b": 1e9,
    "trillion": 1e12,
    "tn": 1e12,
}

# A number: optional currency, digits with thousands separators / decimals,
# optional magnitude word, optional percent / multiple marker. Currency symbols
# and the Indian "Rs"/"INR" prefixes are recognised so "₹4,500 cr" parses.
_NUMBER_RE = re.compile(
    r"""
    (?P<currency>₹|\$|€|£|Rs\.?|INR|USD)?\s?
    (?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    \s?(?P<mag>crore|cr|lakh|lac|billion|bn|million|mn|trillion|tn|thousand|k)?
    \s?(?P<suffix>%|x|bps)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Standalone calendar years (1900–2099) are almost never a "claim" worth
# sourcing; excluding them keeps the ungrounded list high-signal.
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


@dataclass(frozen=True)
class NumericClaim:
    """One numeric figure extracted from text."""

    raw: str
    value: float          # magnitude-normalised absolute value (percent kept as-is, e.g. 23.0)
    kind: str             # 'percent' | 'currency' | 'multiple' | 'bps' | 'plain'
    start: int
    end: int


def _to_float(num: str) -> Optional[float]:
    try:
        return float(num.replace(",", ""))
    except (TypeError, ValueError):
        return None


def extract_numeric_claims(text: str, *, include_years: bool = False) -> List[NumericClaim]:
    """Extract numeric claims from *text*.

    Percent and multiple ('x') values keep their face value (23% → 23.0, 1.5x →
    1.5); currency/plain values are scaled by any magnitude word (₹4,500 cr →
    4.5e10). Standalone years are excluded unless ``include_years`` is set.
    """
    claims: List[NumericClaim] = []
    if not text:
        return claims
    for m in _NUMBER_RE.finditer(text):
        base = _to_float(m.group("num"))
        if base is None:
            continue
        raw_num = m.group("num")
        suffix = (m.group("suffix") or "").lower()
        mag = (m.group("mag") or "").lower()
        currency = m.group("currency")

        if not include_years and not mag and not suffix and not currency and _YEAR_RE.match(raw_num.replace(",", "")):
            continue

        if suffix == "%":
            kind, value = "percent", base
        elif suffix == "x":
            kind, value = "multiple", base
        elif suffix == "bps":
            kind, value = "bps", base
        else:
            value = base * _MAGNITUDES.get(mag, 1.0)
            kind = "currency" if currency else "plain"
        claims.append(
            NumericClaim(raw=m.group(0).strip(), value=value, kind=kind, start=m.start(), end=m.end())
        )
    return claims


def _matches(claim_value: float, source_value: float, rel_tol: float, abs_tol: float) -> bool:
    if math.isclose(claim_value, source_value, rel_tol=rel_tol, abs_tol=abs_tol):
        return True
    # Percent-as-fraction equivalence (23 vs 0.23) — common between prose and data.
    if source_value != 0 and math.isclose(claim_value / 100.0, source_value, rel_tol=rel_tol, abs_tol=abs_tol):
        return True
    if claim_value != 0 and math.isclose(claim_value, source_value / 100.0, rel_tol=rel_tol, abs_tol=abs_tol):
        return True
    return False


def audit_grounding(
    answer: str,
    sources: Iterable[str],
    *,
    rel_tol: float = 0.01,
    abs_tol: float = 1e-9,
    include_years: bool = False,
) -> Dict[str, Any]:
    """Audit numeric grounding of *answer* against *sources*.

    A figure in the answer is "grounded" when a figure within ``rel_tol`` of it
    (or its percent/fraction equivalent) appears anywhere in the concatenated
    source material. Returns a JSON-safe report; never raises on odd input.

    Returns keys: ``n_claims``, ``n_grounded``, ``n_ungrounded``,
    ``grounding_ratio`` (1.0 when there are no claims), ``ungrounded`` (list of
    raw un-sourced figures) and ``claims`` (per-figure detail).
    """
    claims = extract_numeric_claims(answer or "", include_years=include_years)
    source_text = "\n".join(s for s in sources if s)
    source_claims = extract_numeric_claims(source_text, include_years=True)
    source_values = [c.value for c in source_claims]

    details: List[Dict[str, Any]] = []
    ungrounded: List[str] = []
    n_grounded = 0
    for c in claims:
        grounded = any(_matches(c.value, sv, rel_tol, abs_tol) for sv in source_values)
        if grounded:
            n_grounded += 1
        else:
            ungrounded.append(c.raw)
        details.append({"raw": c.raw, "value": c.value, "kind": c.kind, "grounded": grounded})

    n = len(claims)
    return {
        "n_claims": n,
        "n_grounded": n_grounded,
        "n_ungrounded": n - n_grounded,
        "grounding_ratio": round(n_grounded / n, 4) if n else 1.0,
        "ungrounded": ungrounded,
        "claims": details,
    }
