"""Agent tools for verified issuer reports and dated evidence."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.tools import _sources
from src.tools._pit import parse_window


class ResolveOfficialDomainTool(BaseTool):
    name = "resolve_official_domain"
    description = "Resolve and verify a company's own website. Refuses aggregators and unverified namesakes."
    repeatable = True
    parameters = {"type": "object", "properties": {
        "company": {"type": "string"},
        "code": {"type": "string", "description": "Listing symbol used for deterministic issuer matching."},
    }, "required": ["company"]}

    def execute(self, **kwargs: Any) -> str:
        return json.dumps(
            _sources.resolve_official_domain(str(kwargs["company"]), str(kwargs.get("code") or "")),
            ensure_ascii=False,
        )


class CompanyDocumentsTool(BaseTool):
    name = "get_company_documents"
    description = (
        "Built-in financial-report search engine. Searches the verified company investor-relations "
        "site first for every requested fiscal year, then fills gaps from NSE/BSE, SEBI, "
        "Moneycontrol, and a public annual-report archive. Returns source precedence, exact "
        "year coverage, missing years, and a complete attempt ledger."
    )
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "company": {"type": "string"},
            "code": {"type": "string", "description": "Resolved listing symbol, e.g. RELIANCE.NS or 500325.BO."},
            "history_years": {"type": "integer", "minimum": 5, "maximum": 60, "default": 5},
            "start_year": {"type": "integer", "description": "First fiscal-report year required (inclusive)."},
            "end_year": {"type": "integer", "description": "Last fiscal-report year required (inclusive)."},
        },
        "required": ["company"],
    }

    def execute(self, **kwargs: Any) -> str:
        result = _sources.company_documents(
            str(kwargs["company"]),
            code=str(kwargs.get("code") or ""),
            history_years=int(kwargs.get("history_years", 5)),
            start_year=kwargs.get("start_year"),
            end_year=kwargs.get("end_year"),
        )
        return json.dumps(result, ensure_ascii=False)


class OfficialEvidenceTool(BaseTool):
    name = "get_official_evidence"
    description = "Search the fixed evidence-source ladder for dated, in-window evidence with strict domain attribution."
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"}, "year": {"type": "integer"},
            "start_date": {"type": "string"}, "end_date": {"type": "string"},
            "sweep": {"type": "boolean", "default": False},
        },
        "required": ["query"],
    }

    def execute(self, **kwargs: Any) -> str:
        window = parse_window(
            year=kwargs.get("year"), start_date=kwargs.get("start_date"), end_date=kwargs.get("end_date")
        )
        return json.dumps(
            _sources.search_ladder(str(kwargs["query"]), window, sweep=bool(kwargs.get("sweep", False))),
            ensure_ascii=False,
        )
