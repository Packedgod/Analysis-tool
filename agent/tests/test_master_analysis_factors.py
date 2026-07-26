"""Authoritative master-factor registry and tool tests."""

import json

from src.analysis.master_factors import factor_pack, load_master_factor_registry
from src.tools.master_analysis_factors_tool import MasterAnalysisFactorsTool


def test_registry_preserves_all_common_parameters_and_user_authority():
    registry = load_master_factor_registry()

    assert registry["source"]["verification_status"] == "user_verified_authoritative"
    assert {source["sha256"] for source in registry["sources"]} == {
        "2dd2c03652645dbf453737593c3e58ded0fc65d86430479007723f5f98568db9",
        "f00fd78e1e4ab9ae1d29a4c2dfb03b11889e7b16ef517da73435594645af337d",
    }
    assert registry["governance"]["applies_to_every_prompt"] is True
    assert len(registry["common_parameters"]) == 70
    assert len(registry["sector_map"]) == 23
    assert len(registry["sector_factors"]) == 23
    assert len(registry["macro_market_briefing"]) == 7


def test_sector_pack_returns_financial_services_factors_and_benchmark():
    pack = factor_pack("Financial Services", include_qualitative=True)

    assert pack["status"] == "ok"
    assert pack["matched_sector"] == "Financial Services"
    assert pack["sector_factors"]
    mapped = next(item for item in pack["sector_map"] if item["Sector Name"] == "Financial Services")
    assert mapped["Benchmark Index"] == "Nifty Financial Services"
    assert pack["factor_policy"]["common_category_weight"] == 0.75
    assert pack["factor_policy"]["qualitative_industry_layer_weight"] == 0.60


def test_backend_tool_returns_filtered_authoritative_pack():
    result = json.loads(MasterAnalysisFactorsTool().execute(sector="Information Technology"))

    assert result["authority"]["verification_status"] == "user_verified_authoritative"
    assert result["matched_sector"] == "Information Technology"
    assert len(result["common_parameters"]) == 70
    assert result["sector_factors"]


def test_analysis_backbone_end_to_end():
    """One path: generated registry -> runtime tool -> private prompt contract."""
    from src.api.analysis_routes import AnalysisBriefRequest, build_analysis_prompt

    registry = load_master_factor_registry()
    pack = json.loads(MasterAnalysisFactorsTool().execute(sector="Information Technology"))
    prompt = build_analysis_prompt(
        AnalysisBriefRequest(
            company="Infosys Limited",
            ticker="INFY.NS",
            factors="quality, valuation, and macro sensitivity",
            history_years=3,
        )
    )

    assert [source["filename"] for source in registry["sources"]] == [
        "Stocks_Sector.xlsx",
        "India_Macro_Market_Briefing.xlsx",
    ]
    assert pack["matched_sector"] == "Information Technology"
    assert len(pack["common_parameters"]) == 70
    assert pack["sector_factors"]
    assert {
        "Indicator Dashboard",
        "Cycle Placement",
        "Linkage Map",
        "Positioning",
        "Triggers & Caveats",
    }.issubset(pack["macro_market_briefing"])
    assert any(
        row.get("calculated_cells")
        for row in pack["macro_market_briefing"]["Cycle Placement"]
    )
    assert "two user-verified sources" in prompt
    assert "Use the macro workbook alone" in prompt
    assert "workbook filename, sheet, and row provenance" in prompt
    assert "not a recommendation on any security" in prompt

