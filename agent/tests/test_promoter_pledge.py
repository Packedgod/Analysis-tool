"""Tests for promoter shareholding / pledge risk analysis.

The analysis core is pure, so these cover the real decision logic: the two
pledge conventions, severity banding, escalation detection, and graceful
degradation on missing fields. The tool layer is tested without network.
"""

from __future__ import annotations

import json

from src.analysis.promoter_risk import analyze_promoter_risk, normalize_records
from src.tools.promoter_pledge_tool import PromoterPledgeTool, normalize_payload_rows


def _q(period: str, promoter: float, pledge_of_promoter: float, **kw):
    return {"period": period, "promoter_pct": promoter,
            "pledged_pct_of_promoter": pledge_of_promoter, **kw}


class TestNormalization:
    def test_derives_pct_of_total_from_pct_of_promoter(self) -> None:
        rows = normalize_records([_q("2024-03-31", 50.0, 20.0)])
        # 20% of a 50% stake == 10% of total equity
        assert rows[0]["pledged_pct_of_total"] == 10.0

    def test_derives_pct_of_promoter_from_pct_of_total(self) -> None:
        rows = normalize_records([
            {"period": "2024-03-31", "promoter_pct": 50.0, "pledged_pct_of_total": 10.0}
        ])
        assert rows[0]["pledged_pct_of_promoter"] == 20.0

    def test_messy_values_coerced(self) -> None:
        rows = normalize_records([
            {"period": "2024-03-31", "promoter_pct": "54.2%", "pledged_pct_of_promoter": "-"}
        ])
        assert rows[0]["promoter_pct"] == 54.2
        assert rows[0]["pledged_pct_of_promoter"] is None

    def test_sorted_chronologically(self) -> None:
        rows = normalize_records([_q("2024-06-30", 50, 5), _q("2023-03-31", 50, 1)])
        assert [r["period"] for r in rows] == ["2023-03-31", "2024-06-30"]

    def test_rows_without_period_dropped(self) -> None:
        assert normalize_records([{"promoter_pct": 50.0}]) == []


class TestSeverity:
    def test_bands(self) -> None:
        cases = {0.0: "none", 5.0: "low", 15.0: "watch", 30.0: "high", 60.0: "severe"}
        for pledge, expected in cases.items():
            out = analyze_promoter_risk([_q("2024-03-31", 50.0, pledge)])
            assert out["pledge_severity"] == expected, pledge

    def test_undisclosed_is_unknown_not_zero(self) -> None:
        out = analyze_promoter_risk([{"period": "2024-03-31", "promoter_pct": 50.0}])
        assert out["pledge_severity"] == "unknown"
        assert "unverified" in out["assessment"]


class TestTrendsAndFlags:
    def test_rising_pledge_flagged(self) -> None:
        out = analyze_promoter_risk([_q("2024-03-31", 50.0, 10.0), _q("2024-06-30", 50.0, 18.0)])
        assert "pledge_rising" in out["flags"]
        assert out["pledge_qoq_change"] == 8.0

    def test_noise_below_threshold_not_flagged(self) -> None:
        out = analyze_promoter_risk([_q("2024-03-31", 50.0, 10.0), _q("2024-06-30", 50.0, 11.0)])
        assert "pledge_rising" not in out["flags"]

    def test_escalating_governance_risk(self) -> None:
        # Pledging up AND promoters selling down — the pre-blowup combination.
        out = analyze_promoter_risk([
            _q("2024-03-31", 55.0, 10.0),
            _q("2024-06-30", 51.0, 20.0),
        ])
        assert "escalating_governance_risk" in out["flags"]
        assert "forced lender selling" in out["assessment"]

    def test_window_trends(self) -> None:
        out = analyze_promoter_risk([
            _q("2023-03-31", 60.0, 5.0, fii_pct=10.0, dii_pct=5.0),
            _q("2023-06-30", 58.0, 12.0, fii_pct=12.0, dii_pct=6.0),
            _q("2023-09-30", 55.0, 22.0, fii_pct=8.0, dii_pct=9.0),
        ])
        assert out["pledge_trend_window"] == 17.0
        assert out["promoter_stake_trend_window"] == -5.0
        assert out["fii_trend_window"] == -2.0
        assert out["dii_trend_window"] == 4.0
        assert out["periods_analyzed"] == 3

    def test_no_data(self) -> None:
        assert analyze_promoter_risk([])["status"] == "no_data"

    def test_json_safe(self) -> None:
        json.loads(json.dumps(analyze_promoter_risk([_q("2024-03-31", 50.0, 30.0)])))


class TestFieldAliasing:
    def test_provider_aliases_mapped(self) -> None:
        rows = normalize_payload_rows([
            {"asOnDate": "2024-03-31", "Promoter Holding": 54.2, "Pledged %": 12.5, "FII": 18.0}
        ])
        assert rows[0]["period"] == "2024-03-31"
        assert rows[0]["promoter_pct"] == 54.2
        assert rows[0]["pledged_pct_of_promoter"] == 12.5
        assert rows[0]["fii_pct"] == 18.0

    def test_unknown_keys_dropped_not_guessed(self) -> None:
        rows = normalize_payload_rows([{"period": "2024-03-31", "mystery_field": 99}])
        assert "mystery_field" not in rows[0]

    def test_non_list_payload_safe(self) -> None:
        assert normalize_payload_rows({"nope": 1}) == []


class TestToolLayer:
    def _run(self, **kw):
        return json.loads(PromoterPledgeTool().execute(**kw))

    def test_records_mode_offline(self) -> None:
        out = self._run(records=[
            {"period": "2024-03-31", "promoter_pct": 55.0, "pledged_pct_of_promoter": 10.0},
            {"period": "2024-06-30", "promoter_pct": 51.0, "pledged_pct_of_promoter": 22.0},
        ])
        assert out["status"] == "ok"
        assert out["source"] == "supplied_records"
        assert "escalating_governance_risk" in out["flags"]

    def test_no_input_is_clean_unavailable(self) -> None:
        out = self._run()
        assert out["status"] == "unavailable"
        assert "records" in out["error"]

    def test_fetch_failure_degrades_cleanly(self, monkeypatch) -> None:
        # A schema change / block must never fabricate a pledge level.
        import src.tools.promoter_pledge_tool as mod

        monkeypatch.setattr(mod, "_fetch_nse_shareholding", lambda symbol: [])
        out = self._run(symbol="RELIANCE.NS")
        assert out["status"] == "unavailable"

    def test_fetch_path_used_when_records_absent(self, monkeypatch) -> None:
        import src.tools.promoter_pledge_tool as mod

        monkeypatch.setattr(
            mod, "_fetch_nse_shareholding",
            lambda symbol: [{"period": "2024-06-30", "promoter_pct": 50.0,
                             "pledged_pct_of_promoter": 30.0}],
        )
        out = self._run(symbol="RELIANCE.NS")
        assert out["status"] == "ok"
        assert out["source"] == "nse_corporate_api"
        assert out["pledge_severity"] == "high"

    def test_tool_metadata_and_discovery(self) -> None:
        from src.tools import build_registry

        tool = PromoterPledgeTool()
        assert tool.name == "get_promoter_pledge"
        assert tool.is_readonly is True
        assert "get_promoter_pledge" in build_registry().tool_names
