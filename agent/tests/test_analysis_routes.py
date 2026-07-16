"""Contract tests for the private guided-analysis entrypoint."""

from src.api.analysis_routes import AnalysisBriefRequest, build_analysis_prompt


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

