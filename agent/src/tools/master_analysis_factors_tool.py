"""Backend tool exposing the two-workbook analysis backbone by sector."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.analysis.master_factors import factor_pack


class MasterAnalysisFactorsTool(BaseTool):
    name = "get_master_analysis_factors"
    description = (
        "Mandatory backend backbone for every prompt. Returns the user-verified Stocks_Sector "
        "bottom-up standards and India_Macro_Market_Briefing top-down standards, including the "
        "70 common fundamentals, sector/industry KPIs, qualitative framework, current macro "
        "readings, cycle placement, linkage map, positioning, triggers, caveats, and governing "
        "workflow. Call before answering; pass a resolved sector for listed-equity requests."
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
            "code": {
                "type": "string",
                "description": "Listing symbol used to normalize provider sectors to the workbook taxonomy.",
            },
            "include_qualitative": {
                "type": "boolean",
                "description": "Include the weighted qualitative factor framework (default true).",
                "default": True,
            },
        },
        "required": [],
    }

    def execute(
        self, sector: str | None = None, include_qualitative: bool = True,
        code: str = "", **_: Any,
    ) -> str:
        return json.dumps(
            factor_pack(sector, include_qualitative=include_qualitative, code=code),
            ensure_ascii=False,
            allow_nan=False,
        )

