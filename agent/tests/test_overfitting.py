"""Tests for overfitting-honest performance statistics.

Property-based where possible (monotonicity, bounds, deflation direction) so
the suite pins the *behaviour* of PSR / Deflated Sharpe / MinTRL without being
brittle about exact floating-point values.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from backtest.overfitting import (
    deflated_sharpe_ratio,
    min_track_record_length,
    overfitting_report,
    probabilistic_sharpe_ratio,
)
from backtest.validation import run_validation


def _returns(n: int, mean: float, sd: float, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).normal(mean, sd, size=n)


class TestProbabilisticSharpe:
    def test_bounded_unit_interval(self) -> None:
        psr = probabilistic_sharpe_ratio(_returns(250, 0.001, 0.01))
        assert 0.0 <= psr <= 1.0

    def test_longer_record_is_more_credible(self) -> None:
        # Same return distribution, more observations -> higher confidence.
        short = probabilistic_sharpe_ratio(_returns(60, 0.0008, 0.01, seed=1))
        long = probabilistic_sharpe_ratio(_returns(1000, 0.0008, 0.01, seed=1))
        assert long > short

    def test_zero_edge_averages_to_half(self) -> None:
        # A zero-mean strategy's PSR is ~uniform per sample, so it centres on
        # 0.5 in expectation: no systematic evidence the true Sharpe beats zero.
        psrs = [probabilistic_sharpe_ratio(_returns(500, 0.0, 0.01, seed=s)) for s in range(200)]
        assert 0.4 < float(np.mean(psrs)) < 0.6

    def test_degenerate_inputs_do_not_raise(self) -> None:
        assert math.isnan(probabilistic_sharpe_ratio([]))
        assert math.isnan(probabilistic_sharpe_ratio([0.01]))
        # zero-volatility series -> undefined, not a crash
        assert math.isnan(probabilistic_sharpe_ratio([0.01, 0.01, 0.01]))


class TestDeflatedSharpe:
    def test_deflation_never_increases_confidence(self) -> None:
        r = _returns(500, 0.0009, 0.01, seed=5)
        psr = probabilistic_sharpe_ratio(r, sr_benchmark=0.0)
        dsr = deflated_sharpe_ratio(r, n_trials=50)["dsr"]
        assert dsr <= psr + 1e-9

    def test_more_trials_lower_confidence(self) -> None:
        r = _returns(750, 0.001, 0.01, seed=7)
        d1 = deflated_sharpe_ratio(r, n_trials=1)["dsr"]
        d10 = deflated_sharpe_ratio(r, n_trials=10)["dsr"]
        d500 = deflated_sharpe_ratio(r, n_trials=500)["dsr"]
        assert d1 >= d10 >= d500

    def test_single_trial_benchmark_is_zero(self) -> None:
        r = _returns(300, 0.001, 0.01, seed=9)
        out = deflated_sharpe_ratio(r, n_trials=1)
        assert out["deflated_benchmark_sr"] == 0.0
        # with a zero benchmark DSR collapses to PSR(0)
        assert abs(out["dsr"] - probabilistic_sharpe_ratio(r, 0.0)) < 1e-12

    def test_explicit_trial_sharpes_drive_deflation(self) -> None:
        r = _returns(400, 0.001, 0.01, seed=11)
        wide = deflated_sharpe_ratio(r, n_trials=20, trial_sharpes=[0.2, -0.2, 0.3, -0.3, 0.1])
        assert wide["deflated_benchmark_sr"] > 0.0


class TestMinTrackRecordLength:
    def test_positive_edge_finite_and_positive(self) -> None:
        mintrl = min_track_record_length(_returns(500, 0.001, 0.01, seed=13))
        assert math.isfinite(mintrl) and mintrl > 1.0

    def test_non_positive_edge_is_infinite(self) -> None:
        # Clearly negative drift (mean 5x the standard error) -> no track record
        # length could make a losing strategy's Sharpe credible.
        assert math.isinf(min_track_record_length(_returns(500, -0.005, 0.01, seed=15)))


class TestOverfittingReport:
    def test_shape_and_types(self) -> None:
        rep = overfitting_report(_returns(500, 0.001, 0.01, seed=17), n_trials=25, bars_per_year=252)
        for key in (
            "sharpe_annualized",
            "probabilistic_sharpe_ratio",
            "deflated_sharpe_ratio",
            "min_track_record_length_periods",
            "credible_at_95",
            "interpretation",
        ):
            assert key in rep
        assert isinstance(rep["credible_at_95"], bool)
        assert isinstance(rep["interpretation"], str) and rep["interpretation"]

    def test_json_safe_no_nan_or_inf(self) -> None:
        import json

        rep = overfitting_report(_returns(400, 0.0, 0.01, seed=19), n_trials=100)
        # must round-trip through JSON (no NaN/Inf leaking into artifacts)
        json.loads(json.dumps(rep))

    def test_insufficient_data_note(self) -> None:
        rep = overfitting_report([0.01, -0.02])
        assert "note" in rep


class TestRunValidationIntegration:
    def _equity(self, n: int, seed: int = 21) -> pd.Series:
        rets = np.random.default_rng(seed).normal(0.0008, 0.01, size=n)
        eq = 1_000_000 * np.cumprod(1 + rets)
        idx = pd.date_range("2022-01-01", periods=n, freq="D")
        return pd.Series(eq, index=idx)

    def test_overfitting_added_when_validation_configured(self) -> None:
        result = run_validation(
            {"validation": {"bootstrap": {"n_bootstrap": 20}}},
            self._equity(300),
            [],
            1_000_000,
        )
        assert "overfitting" in result
        assert "deflated_sharpe_ratio" in result["overfitting"]

    def test_empty_config_still_returns_empty(self) -> None:
        # The {}-in/{}-out contract must survive the new section.
        assert run_validation({}, self._equity(100), [], 1_000_000) == {}

    def test_n_trials_flows_through(self) -> None:
        result = run_validation(
            {"validation": {"overfitting": {"n_trials": 250}}},
            self._equity(400),
            [],
            1_000_000,
        )
        assert result["overfitting"]["n_trials"] == 250
