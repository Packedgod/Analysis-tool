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


class TestNsePledgeMerge:
    """Joining NSE's two feeds: shareholding (many quarters) + pledge (latest)."""

    def _merge(self, sh, pl):
        from src.tools.promoter_pledge_tool import _merge_pledge

        return _merge_pledge(sh, pl)

    def test_pledge_overlaid_on_matching_quarter(self) -> None:
        out = self._merge(
            [{"period": "31-MAR-2026", "promoter_pct": 50.1},
             {"period": "30-JUN-2026", "promoter_pct": 51.32}],
            [{"period": "30-Jun-2026", "pledged_pct_of_total": 1.23}],
        )
        latest = [r for r in out if r["period"] == "30-JUN-2026"][0]
        assert latest["pledged_pct_of_total"] == 1.23
        # the non-matching quarter stays undisclosed, NOT zero
        earlier = [r for r in out if r["period"] == "31-MAR-2026"][0]
        assert "pledged_pct_of_total" not in earlier

    def test_case_insensitive_period_join(self) -> None:
        # NSE spells the same quarter 30-JUN-2026 and 30-Jun-2026 across feeds.
        out = self._merge(
            [{"period": "30-JUN-2026", "promoter_pct": 51.32}],
            [{"period": "30-Jun-2026", "pledged_pct_of_total": 1.23}],
        )
        assert out[0]["pledged_pct_of_total"] == 1.23

    def test_pledge_only_quarter_is_kept(self) -> None:
        out = self._merge([], [{"period": "30-Jun-2026", "pledged_pct_of_total": 1.23}])
        assert len(out) == 1

    def test_no_pledge_feed_leaves_series_untouched(self) -> None:
        sh = [{"period": "30-JUN-2026", "promoter_pct": 51.32}]
        assert self._merge(sh, []) is sh

    def test_percent_of_total_converts_to_percent_of_promoter(self) -> None:
        # The reporting trap: NSE quotes pledge as % of TOTAL equity. Read as
        # % of promoter holding it would understate risk ~2x.
        out = analyze_promoter_risk(
            [{"period": "30-JUN-2026", "promoter_pct": 51.32, "pledged_pct_of_total": 1.23}]
        )
        assert round(out["pledge_pct_of_promoter"], 2) == 2.40
        assert out["pledge_pct_of_total_equity"] == 1.23


class TestSchemaDriftGuard:
    """A feed that parses structurally but maps nothing must fail loudly.

    This is the failure that actually happened: NSE's columns were unmapped, so
    every value came back null while the envelope still said ``status: "ok"`` —
    a broken feed reporting success. "Unknown" and "no pledging" are different
    claims and must never be conflated.
    """

    def _run(self, **kw):
        return json.loads(PromoterPledgeTool().execute(**kw))

    def test_unmapped_payload_reports_drift_not_ok(self, monkeypatch) -> None:
        import src.tools.promoter_pledge_tool as mod

        drifted = mod.normalize_payload_rows(
            [{"date": "30-JUN-2026", "SOME_RENAMED_PROMOTER_COL": "51.32"}]
        )
        monkeypatch.setattr(mod, "_fetch_nse_shareholding", lambda symbol: drifted)
        monkeypatch.setattr(mod, "_fetch_nse_pledge", lambda symbol: [])
        out = self._run(symbol="RELIANCE.NS")
        assert out["status"] == "schema_drift"
        assert "UNKNOWN" in out["error"]

    def test_partial_mapping_is_still_ok(self, monkeypatch) -> None:
        # Promoter stake alone is genuine signal; only a total mapping failure
        # is drift, otherwise a feed that drops one optional column would alarm.
        import src.tools.promoter_pledge_tool as mod

        monkeypatch.setattr(
            mod, "_fetch_nse_shareholding",
            lambda symbol: [{"period": "30-JUN-2026", "promoter_pct": 51.32}],
        )
        monkeypatch.setattr(mod, "_fetch_nse_pledge", lambda symbol: [])
        assert self._run(symbol="RELIANCE.NS")["status"] == "ok"

    def test_has_mapped_values_helper(self) -> None:
        from src.tools.promoter_pledge_tool import has_mapped_values

        assert has_mapped_values([{"period": "x", "promoter_pct": 1.0}]) is True
        assert has_mapped_values([{"period": "x"}]) is False
        assert has_mapped_values([]) is False

    def test_unmapped_keys_lists_the_offenders(self) -> None:
        from src.tools.promoter_pledge_tool import unmapped_keys

        keys = unmapped_keys([{"date": "x", "brandNewColumn": 1, "pr_and_prgrp": "50"}])
        assert "brandNewColumn" in keys
        # recognised columns must not be reported as drift
        assert "pr_and_prgrp" not in keys and "date" not in keys


class TestNseFieldContract:
    """Pin the exact upstream column names this tool depends on.

    These are undocumented NSE endpoints. If someone edits the alias table,
    this fails immediately rather than the breakage surfacing as silent nulls
    in production months later.
    """

    def test_shareholding_columns_are_mapped(self) -> None:
        rows = normalize_payload_rows([{
            "date": "30-JUN-2026", "pr_and_prgrp": "50.48", "public_val": "49.52",
        }])
        assert rows[0]["period"] == "30-JUN-2026"
        assert rows[0]["promoter_pct"] == "50.48"
        assert rows[0]["public_pct"] == "49.52"

    def test_pledge_columns_are_mapped(self) -> None:
        rows = normalize_payload_rows([{
            "shp": "30-Jun-2026", "percPromoterHolding": "    51.32",
            "percSharesPledged": "1.23",
        }])
        assert rows[0]["period"] == "30-Jun-2026"
        assert rows[0]["promoter_pct"] == "    51.32"   # whitespace tolerated downstream
        # percSharesPledged is a share of TOTAL issued shares, NOT promoter
        # holding — verified as numSharesPledged/totIssuedShares upstream.
        assert rows[0]["pledged_pct_of_total"] == "1.23"
        assert "pledged_pct_of_promoter" not in rows[0]


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
        monkeypatch.setattr(mod, "_fetch_nse_pledge", lambda symbol: [])
        out = self._run(symbol="RELIANCE.NS")
        assert out["status"] == "unavailable"

    def test_fetch_path_used_when_records_absent(self, monkeypatch) -> None:
        import src.tools.promoter_pledge_tool as mod

        monkeypatch.setattr(
            mod, "_fetch_nse_shareholding",
            lambda symbol: [{"period": "2024-06-30", "promoter_pct": 50.0,
                             "pledged_pct_of_promoter": 30.0}],
        )
        monkeypatch.setattr(mod, "_fetch_nse_pledge", lambda symbol: [])
        out = self._run(symbol="RELIANCE.NS")
        assert out["status"] == "ok"
        assert out["source"] == "nse_corporate_api"
        assert out["pledge_severity"] == "high"

    def test_both_feeds_are_combined(self, monkeypatch) -> None:
        import src.tools.promoter_pledge_tool as mod

        monkeypatch.setattr(
            mod, "_fetch_nse_shareholding",
            lambda symbol: [{"period": "30-JUN-2026", "promoter_pct": 51.32}],
        )
        monkeypatch.setattr(
            mod, "_fetch_nse_pledge",
            lambda symbol: [{"period": "30-Jun-2026", "pledged_pct_of_total": 1.23}],
        )
        out = self._run(symbol="RELIANCE.NS")
        assert out["status"] == "ok"
        assert round(out["pledge_pct_of_promoter"], 2) == 2.40

    def test_tool_metadata_and_discovery(self) -> None:
        from src.tools import build_registry

        tool = PromoterPledgeTool()
        assert tool.name == "get_promoter_pledge"
        assert tool.is_readonly is True
        assert "get_promoter_pledge" in build_registry().tool_names
