"""Tool that performs the non-bypassable research preflight for company runs."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.analysis.execution_backbone import prepare_company_backbone
from src.tools.path_utils import safe_run_dir


class PrepareAnalysisBackboneTool(BaseTool):
    name = "prepare_analysis_backbone"
    description = (
        "Mandatory before any listed-company analysis or backtest. Runs the built-in report "
        "search for every fiscal year in the requested span: issuer website first, then "
        "NSE/BSE, SEBI, Moneycontrol, and a public report archive. It reads and stores the "
        "evidence, records gaps and attempted fallbacks, loads both authoritative workbook "
        "packs, and writes analysis_backbone.json. A backtest is rejected without it."
    )
    repeatable = True
    is_readonly = False
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {"type": "string"},
            "companies": {
                "type": "array", "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "company": {"type": "string"}, "code": {"type": "string"},
                        "sector": {"type": "string"},
                        "start_year": {"type": "integer"},
                        "end_year": {"type": "integer"},
                    },
                    "required": ["company", "code", "sector"],
                },
            },
            "history_years": {"type": "integer", "minimum": 1, "maximum": 60, "default": 5},
            "start_year": {"type": "integer", "description": "First required report year, inclusive."},
            "end_year": {"type": "integer", "description": "Last required report year, inclusive."},
        },
        "required": ["run_dir", "companies"],
    }

    def execute(self, **kwargs: Any) -> str:
        try:
            run_path = safe_run_dir(str(kwargs["run_dir"]))
            result = prepare_company_backbone(
                run_path=run_path,
                companies=list(kwargs["companies"]),
                history_years=int(kwargs.get("history_years", 5)),
                start_year=kwargs.get("start_year"),
                end_year=kwargs.get("end_year"),
            )
        except Exception as exc:  # noqa: BLE001 - return a recoverable tool envelope
            result = {"status": "blocked", "error": str(exc)}
        return json.dumps(result, ensure_ascii=False)
