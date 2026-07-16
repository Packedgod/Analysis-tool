"""Backend tool exposing the authoritative factor workbook by sector."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.analysis.master_factors import factor_pack


class MasterAnalysisFactorsTool(BaseTool):
    name = "get_master_analysis_factors"
    description = (
        "Mandatory factor source for every listed-equity analysis. Returns the 70 authoritative "
        "common fundamentals, sector mapping/benchmark, weighted qualitative framework, and the "
        "relevant sector/industry KPI block from the user-verified master workbook. Call after "
        "resolving the issuer sector and use these factors as the primary analysis key."
    )
    repeatable = True
    is_readonly = True
    parameters = {
        "type": "object",
        "properties": {
            "sector": {
                "type": "string",
                "description": "Resolved sector name. Omit to retrieve the common core and sector index.",
            },
            "include_qualitative": {
                "type": "boolean",
                "description": "Include the weighted qualitative factor framework (default true).",
                "default": True,
            },
        },
        "required": [],
    }

    def execute(self, sector: str | None = None, include_qualitative: bool = True, **_: Any) -> str:
        return json.dumps(
            factor_pack(sector, include_qualitative=include_qualitative),
            ensure_ascii=False,
            allow_nan=False,
        )

