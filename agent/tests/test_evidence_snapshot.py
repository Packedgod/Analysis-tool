"""Evidence snapshot and validation JSON-safety regressions.

Two production failures are pinned here:

1. The "verified artifact snapshot" only ever described *backtest* outputs, so a
   fundamentals question produced an empty/backtest-shaped snapshot and the model
   — following its instruction to report only verifiable values — marked every
   factor "unavailable in verified snapshot", despite having fetched them.
2. A wipeout path emitted bare ``NaN`` into validation.json, which is not valid
   JSON and makes the whole document unparseable to a strict reader.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from backtest.validation import json_safe, monte_carlo_test, run_validation
from src.agent.loop import _build_artifact_evidence_snapshot, _collect_tool_evidence


def _write_trace(run_dir, events) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


class TestToolEvidenceHarvest:
    def test_successful_tool_results_are_collected(self, tmp_path) -> None:
        _write_trace(tmp_path, [
            {"type": "tool_call", "tool": "get_fundamentals", "iter": 1},
            {"type": "tool_result", "tool": "get_fundamentals", "status": "ok",
             "iter": 1, "preview": '{"revenue_growth": 0.18, "net_margin": 0.11}'},
        ])
        evidence = _collect_tool_evidence(tmp_path)
        assert len(evidence) == 1
        assert evidence[0]["tool"] == "get_fundamentals"
        assert "revenue_growth" in evidence[0]["result"]

    def test_failed_results_are_not_treated_as_evidence(self, tmp_path) -> None:
        _write_trace(tmp_path, [
            {"type": "tool_result", "tool": "x", "status": "error", "preview": "boom"},
        ])
        assert _collect_tool_evidence(tmp_path) == []

    def test_missing_trace_is_not_fatal(self, tmp_path) -> None:
        assert _collect_tool_evidence(tmp_path) == []

    def test_harvest_is_bounded(self, tmp_path) -> None:
        from src.agent.loop import _EVIDENCE_MAX_TOOL_RESULTS

        _write_trace(tmp_path, [
            {"type": "tool_result", "tool": f"t{i}", "status": "ok", "preview": f"v{i}"}
            for i in range(_EVIDENCE_MAX_TOOL_RESULTS + 30)
        ])
        assert len(_collect_tool_evidence(tmp_path)) == _EVIDENCE_MAX_TOOL_RESULTS


class TestSnapshotIncludesResearchEvidence:
    def test_research_run_no_longer_yields_an_empty_snapshot(self, tmp_path) -> None:
        # No backtest artifacts at all — the exact shape of a fundamentals run.
        _write_trace(tmp_path, [
            {"type": "tool_result", "tool": "get_fundamentals", "status": "ok",
             "preview": '{"revenue_growth": 0.18}'},
        ])
        snapshot = _build_artifact_evidence_snapshot(tmp_path)
        assert snapshot, "a research run must still produce an evidence snapshot"
        payload = json.loads(snapshot)
        assert "tool_evidence" in payload
        assert "revenue_growth" in json.dumps(payload["tool_evidence"])

    def test_snapshot_states_the_artifact_scope(self, tmp_path) -> None:
        # The model must not read "no artifacts" as "no evidence exists".
        _write_trace(tmp_path, [
            {"type": "tool_result", "tool": "t", "status": "ok", "preview": "1"},
        ])
        payload = json.loads(_build_artifact_evidence_snapshot(tmp_path))
        assert "backtest outputs only" in payload["artifacts_scope"]

    def test_truly_empty_run_still_returns_nothing(self, tmp_path) -> None:
        assert _build_artifact_evidence_snapshot(tmp_path) == ""

    def test_instruction_permits_tool_results_as_evidence(self) -> None:
        from src.agent.loop import _EVIDENCE_ONLY_FINAL_INSTRUCTION

        # Collapse wrapping so the assertions test meaning, not line breaks.
        text = " ".join(_EVIDENCE_ONLY_FINAL_INSTRUCTION.lower().split())
        # This wording is the actual fix for "unavailable in verified snapshot".
        assert "not the complete set of evidence" in text
        assert "never label a factor unavailable merely because it is absent" in text
        assert "only when no tool call in this run produced it" in text


class TestValidationJsonSafety:
    def _wipeout_equity(self) -> pd.Series:
        idx = pd.date_range("2024-01-01", periods=40, freq="D")
        return pd.Series(np.linspace(1_000_000, 0.0, 40), index=idx)

    def test_json_safe_replaces_non_finite(self) -> None:
        out = json_safe({"a": float("nan"), "b": float("inf"), "c": 1.5,
                         "d": [float("-inf"), 2], "e": "x", "f": True})
        assert out["a"] is None and out["b"] is None and out["d"][0] is None
        assert out["c"] == 1.5 and out["e"] == "x" and out["f"] is True

    def test_monte_carlo_on_wipeout_is_strict_json(self) -> None:
        from backtest.models import TradeRecord
        import inspect

        sig = inspect.signature(TradeRecord)

        def _trade(pnl, when):
            kwargs = {}
            for name, param in sig.parameters.items():
                if name == "pnl":
                    kwargs[name] = pnl
                elif "time" in name:
                    kwargs[name] = when
                elif param.default is not inspect.Parameter.empty:
                    continue
                else:
                    annotation = str(param.annotation)
                    kwargs[name] = 0.0 if "float" in annotation else (
                        0 if "int" in annotation else "x")
            return TradeRecord(**kwargs)

        idx = pd.date_range("2024-01-01", periods=40, freq="D")
        trades = [_trade(-1_000_000.0, idx[i * 5]) for i in range(3)] + [_trade(0.0, idx[20])]
        result = run_validation(
            {"validation": {"monte_carlo": {"n_simulations": 20},
                            "bootstrap": {"n_bootstrap": 20},
                            "walk_forward": {"n_windows": 3}}},
            self._wipeout_equity(), trades, 1_000_000,
        )
        # The whole document must survive a strict parser, not just look fine.
        json.dumps(result, allow_nan=False)
        for value in json.loads(json.dumps(result, allow_nan=False)).get("monte_carlo", {}).values():
            assert not (isinstance(value, float) and not math.isfinite(value))

    def test_zero_equity_returns_do_not_explode(self) -> None:
        from backtest.validation import _safe_returns

        returns = _safe_returns(np.array([100.0, 0.0, 0.0, 50.0]))
        assert np.isfinite(returns).all()
