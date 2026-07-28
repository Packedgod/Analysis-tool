"""Sector resolution: GICS/global names and ticker overrides map to the workbook.

The two-workbook backbone uses NSE-style sector names (e.g. "Financial
Services", "Telecommunication", "Oil, Gas & Consumable Fuels"). Analysts and
data providers routinely use GICS/global names ("Banking", "Telecommunications",
"Materials", "Conglomerates"). These must resolve rather than block the whole
run — a single unmatched sector otherwise sinks a multi-company backtest.
"""

import pytest

from src.analysis.master_factors import factor_pack

# (requested_sector, code, expected_matched_sector)
_ALIAS_CASES = [
    ("Banking", "", "Financial Services"),
    ("Telecommunications", "", "Telecommunication"),
    ("Telecom Services", "", "Telecommunication"),
    ("Pharmaceuticals", "", "Healthcare"),
    ("Automobiles", "", "Automobile & Auto Components"),
    ("Utilities", "", "Utilities"),
    ("Real Estate", "", "Realty"),
    ("Materials", "", "Metals & Mining"),
    ("Consumer Staples", "", "Fast Moving Consumer Goods (FMC"),
]

# Ticker overrides win even when the model supplies a vague/wrong sector name.
_OVERRIDE_CASES = [
    ("Conglomerates", "RELIANCE.NS", "Oil, Gas & Consumable Fuels"),
    ("Unknown", "RELIANCE.NS", "Oil, Gas & Consumable Fuels"),
    ("Banking", "ICICIBANK.NS", "Financial Services"),
    ("Banking", "SBIN.NS", "Financial Services"),
    ("Telecommunications", "BHARTIARTL.NS", "Telecommunication"),
    ("Materials", "ULTRACEMCO.NS", "Construction Materials"),
]


@pytest.mark.parametrize("sector,code,expected", _ALIAS_CASES + _OVERRIDE_CASES)
def test_sector_resolves(sector, code, expected) -> None:
    pack = factor_pack(sector, code=code)
    assert pack["status"] == "ok", pack.get("available_sectors")
    assert pack["matched_sector"] == expected
    assert pack["sector_factors"]


def test_unmatched_sector_exposes_valid_names() -> None:
    """A truly unknown sector still lists the valid options so callers recover."""
    pack = factor_pack("Totally Made Up Sector", code="NOSUCH.NS")
    assert pack["status"] == "sector_not_matched"
    assert "Financial Services" in pack["available_sectors"]
