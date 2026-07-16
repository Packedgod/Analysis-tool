"""Contract tests for the private guided-analysis entrypoint."""

import json

from src.api.analysis_routes import (
    AnalysisBriefRequest,
    append_private_execution_log,
    build_analysis_prompt,
    build_visible_analysis_message,
)


def test_private_contract_makes_simulation_and_source_resolution_mandatory():
    prompt = build_analysis_prompt(
        AnalysisBriefRequest(
            company="Reliance Industries",
            ticker="RELIANCE.NS",
            factors="cash flow and competitive position",
            history_years=3,
        )
    )

    assert "Historical simulation is mandatory" in prompt
    assert "Google Finance" in prompt
    assert "verified, authoritative user-provided source" in prompt
    assert "identity-resolution record" in prompt
    assert "Never connect to a broker" in prompt
    assert "numeric-first" in prompt
    assert "long-only portfolio review, not day trading" in prompt
    assert "once per year" in prompt
    assert "client profile" in prompt
    assert "portfolio_report.xlsx" not in prompt
    assert "STCG" in prompt and "LTCG" in prompt
    assert "Never hard-code a tax rate" in prompt
    assert "get_master_analysis_factors" in prompt
    assert "mandatory analysis key" in prompt
    assert "User-requested factors supplement this master set" in prompt
    assert "Historical Price Movement" not in prompt
    assert "historical price-movement chart" in prompt


def test_uploaded_strategy_rules_are_preserved_without_execution():
    prompt = build_analysis_prompt(
        AnalysisBriefRequest(
            company="Example Ltd",
            factors="quality",
            strategy_path="uploads/0123456789abcdef0123456789abcdef.xlsx",
            strategy_name="rules.xlsx",
        )
    )

    assert "rules.xlsx" in prompt
    assert "authoritative user evidence" in prompt
    assert "never execute embedded code" in prompt


def test_visible_message_never_contains_private_contract(tmp_path):
    brief = AnalysisBriefRequest(
        company="Example Ltd", ticker="EXAMPLE.NS", factors="quality and valuation"
    )
    private_prompt = build_analysis_prompt(brief)
    visible = build_visible_analysis_message(brief)
    assert visible == "Analyze Example Ltd (EXAMPLE.NS) using my selected factors and sources."
    assert "Private execution contract" not in visible
    assert "get_master_analysis_factors" not in visible

    log_path = tmp_path / "logs" / "private_analysis_contracts.jsonl"
    append_private_execution_log(session_id="session-1", prompt=private_prompt, log_path=log_path)
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["session_id"] == "session-1"
    assert record["execution_contract"] == private_prompt
    assert len(record["prompt_sha256"]) == 64
