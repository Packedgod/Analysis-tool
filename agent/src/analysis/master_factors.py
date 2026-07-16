"""Read-only access to the authoritative user-supplied factor registry."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "master_analysis_factors.json"


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


@lru_cache(maxsize=1)
def load_master_factor_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if payload.get("source", {}).get("verification_status") != "user_verified_authoritative":
        raise ValueError("Master factor registry is not marked authoritative")
    if len(payload.get("common_parameters", [])) != 70:
        raise ValueError("Master factor registry must contain all 70 common parameters")
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


def factor_pack(sector: str | None = None, *, include_qualitative: bool = True) -> dict[str, Any]:
    """Return the global factor core plus the selected sector's factor rows."""
    registry = load_master_factor_registry()
    pack: dict[str, Any] = {
        "status": "ok",
        "authority": registry["source"],
        "common_parameters": registry["common_parameters"],
        "sector_map": registry["sector_map"],
        "factor_policy": {
            "common_parameter_count": 70,
            "common_category_weight": 0.75,
            "sector_and_industry_weight": 0.25,
            "qualitative_sector_layer_weight": 0.40,
            "qualitative_industry_layer_weight": 0.60,
            "score_min": 1,
            "score_max": 10,
        },
    }
    if include_qualitative:
        pack["qualitative_framework"] = registry["qualitative_framework"]
    if sector:
        sheet = _sector_sheet(registry, sector)
        pack["requested_sector"] = sector
        pack["matched_sector"] = sheet
        pack["sector_factors"] = registry["sector_factors"].get(sheet, []) if sheet else []
        if sheet is None:
            pack["status"] = "sector_not_matched"
            pack["available_sectors"] = list(registry["sector_factors"])
    return pack

