"""Read-only access to the authoritative user-supplied factor registry."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "master_analysis_factors.json"

_SECTOR_ALIASES = {
    "financials": "Financial Services",
    "banks": "Financial Services",
    "consumerstaples": "Fast Moving Consumer Goods (FMC",
    "fmcg": "Fast Moving Consumer Goods (FMC",
    "healthcare": "Healthcare",
    "healthcareequipmentservices": "Healthcare",
    "industrials": "Capital Goods",
    "capitalgoods": "Capital Goods",
    "consumerdiscretionary": "Consumer Durables",
    "energy": "Oil, Gas & Consumable Fuels",
    "oilgas": "Oil, Gas & Consumable Fuels",
    "technology": "Information Technology",
    "communicationservices": "Telecommunication",
}

_COMPANY_SECTOR_OVERRIDES = {
    "LT.NS": "Capital Goods",
    "HDFCBANK.NS": "Financial Services",
    "ITC.NS": "Fast Moving Consumer Goods (FMC",
    "DIVISLAB.NS": "Healthcare",
    "JSWSTEEL.NS": "Metals & Mining",
    "TATAPOWER.NS": "Power",
    "ASIANPAINT.NS": "Chemicals",
    "MARUTI.NS": "Automobile & Auto Components",
    "HINDPETRO.NS": "Oil, Gas & Consumable Fuels",
    "IRFC.NS": "Financial Services",
    "INFY.NS": "Information Technology",
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


@lru_cache(maxsize=1)
def load_master_factor_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    sources = payload.get("sources", [])
    if payload.get("schema_version") != 2 or len(sources) != 2:
        raise ValueError("Analysis backbone must contain both authoritative workbooks")
    if any(item.get("verification_status") != "user_verified_authoritative" for item in sources):
        raise ValueError("Analysis backbone contains a source that is not marked authoritative")
    if {item.get("role") for item in sources} != {
        "bottom_up_stock_sector_framework",
        "top_down_india_macro_framework",
    }:
        raise ValueError("Analysis backbone source roles are incomplete")
    if not payload.get("governance", {}).get("applies_to_every_prompt"):
        raise ValueError("Analysis backbone is not configured to govern every prompt")
    if len(payload.get("common_parameters", [])) != 70:
        raise ValueError("Master factor registry must contain all 70 common parameters")
    missing_macro = {
        "Dashboard",
        "Indicator Dashboard",
        "Global Overlay",
        "Cycle Placement",
        "Linkage Map",
        "Positioning",
        "Triggers & Caveats",
    } - set(payload.get("macro_market_briefing", {}))
    if missing_macro:
        raise ValueError(f"Analysis backbone is missing macro sheets: {sorted(missing_macro)}")
    return payload


def _sector_sheet(registry: dict[str, Any], sector: str) -> str | None:
    wanted = _key(sector)
    sheets = registry["sector_factors"]
    exact = next((name for name in sheets if _key(name) == wanted), None)
    if exact:
        return exact
    for item in registry["sector_map"]:
        mapped = str(item.get("Sector Name") or "")
        if _key(mapped) != wanted:
            continue
        return next(
            (name for name in sheets if _key(name).startswith(wanted[:24]) or wanted.startswith(_key(name)[:24])),
            None,
        )
    return None


def normalize_sector(sector: str, *, code: str = "") -> str:
    """Map provider-level sectors to the workbook's authoritative taxonomy."""
    override = _COMPANY_SECTOR_OVERRIDES.get(code.strip().upper())
    if override:
        return override
    return _SECTOR_ALIASES.get(_key(sector), sector)


def factor_pack(
    sector: str | None = None, *, include_qualitative: bool = True, code: str = ""
) -> dict[str, Any]:
    """Return the global factor core plus the selected sector's factor rows."""
    registry = load_master_factor_registry()
    pack: dict[str, Any] = {
        "status": "ok",
        "authority": registry["source"],
        "authoritative_sources": registry["sources"],
        "governance": registry["governance"],
        "common_parameters": registry["common_parameters"],
        "sector_map": registry["sector_map"],
        "macro_market_briefing": registry["macro_market_briefing"],
        "factor_policy": {
            "common_parameter_count": 70,
            "common_category_weight": 0.75,
            "sector_and_industry_weight": 0.25,
            "qualitative_sector_layer_weight": 0.40,
            "qualitative_industry_layer_weight": 0.60,
            "score_min": 1,
            "score_max": 10,
            "macro_source_policy": "Use the supplied macro workbook for every macro figure, regime, stance, linkage, and trigger; missing means missing, never substitute an outside number.",
            "evidence_policy": "Every material output must trace to an authoritative workbook cell or explicit verified evidence. Keep calculations separate and label unavailable inputs.",
        },
    }
    if include_qualitative:
        pack["qualitative_framework"] = registry["qualitative_framework"]
    if sector:
        normalized_sector = normalize_sector(sector, code=code)
        sheet = _sector_sheet(registry, normalized_sector)
        pack["requested_sector"] = sector
        pack["normalized_sector"] = normalized_sector
        pack["matched_sector"] = sheet
        pack["sector_factors"] = registry["sector_factors"].get(sheet, []) if sheet else []
        if sheet is None:
            pack["status"] = "sector_not_matched"
            pack["available_sectors"] = list(registry["sector_factors"])
    return pack

