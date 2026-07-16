"""Authoritative master-factor registry and tool tests."""

import json

from src.analysis.master_factors import factor_pack, load_master_factor_registry
from src.tools.master_analysis_factors_tool import MasterAnalysisFactorsTool


def test_registry_preserves_all_common_parameters_and_user_authority():
    registry = load_master_factor_registry()

    assert registry["source"]["verification_status"] == "user_verified_authoritative"
    assert registry["source"]["sha256"] == "f25f4c5b1a48fa973aa806069aed3f19c526217854975c0157d5e543bf508406"
    assert len(registry["common_parameters"]) == 70
    assert len(registry["sector_map"]) == 23
    assert len(registry["sector_factors"]) == 23


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

