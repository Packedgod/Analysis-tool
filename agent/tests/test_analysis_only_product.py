"""Product-boundary tests for the analysis-only fork."""

from __future__ import annotations

from src.config.accessor import brokerage_enabled
from src.tools import build_registry


def test_brokerage_cannot_be_enabled(monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ENABLE_BROKERAGE", "true")
    assert brokerage_enabled() is False


def test_registry_has_analysis_and_shadow_tools_but_no_broker_tools(monkeypatch) -> None:
    monkeypatch.setenv("VIBE_TRADING_ENABLE_BROKERAGE", "true")
    registry = build_registry(include_shell_tools=False)
    names = set(registry._tools)

    assert "get_company_documents" in names
    assert "get_official_evidence" in names
    assert "get_financial_statements" in names
    assert "extract_shadow_strategy" in names
    assert "run_shadow_backtest" in names
    assert "propose_mandate_profiles" not in names
    assert not any(name.startswith("trading_") for name in names)


def test_public_capability_endpoint_always_reports_no_brokerage(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    import api_server

    monkeypatch.setenv("VIBE_TRADING_ENABLE_BROKERAGE", "true")
    response = TestClient(api_server.app).get("/api")

    assert response.status_code == 200
    assert response.json()["service"] == "Vibe Analysis API"
    assert response.json()["capabilities"]["brokerage"] is False
