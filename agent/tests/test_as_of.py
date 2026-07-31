"""Tests for the point-in-time clock.

The load-bearing properties:
  1. Unset clock == strict no-op (turning the feature off restores exact
     prior behaviour — the safety guarantee the integration relies on).
  2. Engaged clock withholds every future row, at both chokepoints.
  3. Scoping nests and restores correctly, and never leaks between scopes.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backtest import as_of


@pytest.fixture(autouse=True)
def _clean_clock():
    """Guarantee no test leaves a clock engaged for the next one."""
    token = as_of.set_as_of(None)
    yield
    as_of.reset_as_of(token)


def _frame(start: str = "2021-01-01", periods: int = 400) -> pd.DataFrame:
    idx = pd.date_range(start, periods=periods, freq="D")
    return pd.DataFrame({"close": np.arange(periods, dtype=float)}, index=idx)


class TestNoOpWhenUnset:
    def test_not_engaged_by_default(self) -> None:
        assert as_of.get_as_of() is None
        assert as_of.is_engaged() is False

    def test_enforce_frame_returns_input_untouched(self) -> None:
        f = _frame()
        assert as_of.enforce_frame(f) is f

    def test_clamp_and_window_are_noops(self) -> None:
        assert as_of.clamp_end_date("2030-01-01") == "2030-01-01"
        assert as_of.window_is_empty("2030-01-01", "2031-01-01") is False

    def test_enforce_data_map_returns_input(self) -> None:
        m = {"A.US": _frame()}
        assert as_of.enforce_data_map(m) is m


class TestEngagedClock:
    def test_future_rows_withheld(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            out = as_of.enforce_frame(_frame(), label="A.US")
        assert out.index.max() <= pd.Timestamp("2021-06-30")
        assert len(out) == 181  # Jan 1 .. Jun 30 inclusive

    def test_no_future_row_survives_any_offset(self) -> None:
        with as_of.as_of_scope("2021-03-15"):
            out = as_of.enforce_frame(_frame())
        assert (out.index <= pd.Timestamp("2021-03-15")).all()

    def test_end_date_clamped(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            assert as_of.clamp_end_date("2026-01-01") == "2021-06-30"
            # an already-historical request is left alone
            assert as_of.clamp_end_date("2020-01-01") == "2020-01-01"

    def test_window_entirely_in_the_future_is_empty(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            assert as_of.window_is_empty("2022-01-01", "2023-01-01") is True
            assert as_of.window_is_empty("2020-01-01", "2023-01-01") is False

    def test_tz_aware_index_handled(self) -> None:
        idx = pd.date_range("2021-01-01", periods=100, freq="D", tz="UTC")
        f = pd.DataFrame({"close": np.arange(100, dtype=float)}, index=idx)
        with as_of.as_of_scope("2021-02-01"):
            out = as_of.enforce_frame(f)
        assert len(out) == 32

    def test_non_datetime_index_passes_through(self) -> None:
        f = pd.DataFrame({"close": [1.0, 2.0]})
        with as_of.as_of_scope("2021-06-30"):
            assert as_of.enforce_frame(f) is f

    def test_data_map_enforced(self) -> None:
        with as_of.as_of_scope("2021-02-01"):
            out = as_of.enforce_data_map({"A.US": _frame(), "B.US": _frame()})
        for frame in out.values():
            assert frame.index.max() <= pd.Timestamp("2021-02-01")


class TestScoping:
    def test_scope_restores_previous(self) -> None:
        assert as_of.get_as_of() is None
        with as_of.as_of_scope("2021-06-30"):
            assert as_of.get_as_of() == pd.Timestamp("2021-06-30")
        assert as_of.get_as_of() is None

    def test_nested_scopes(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            with as_of.as_of_scope("2019-01-01"):
                assert as_of.get_as_of() == pd.Timestamp("2019-01-01")
            assert as_of.get_as_of() == pd.Timestamp("2021-06-30")

    def test_inner_none_scope_runs_live(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            with as_of.as_of_scope(None):
                assert as_of.is_engaged() is False
            assert as_of.is_engaged() is True


class TestAudit:
    def test_ledger_records_withheld_rows(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            as_of.enforce_frame(_frame(), label="A.US")
            block = as_of.audit_block()
        assert block["engaged"] is True
        assert block["as_of"] == "2021-06-30"
        assert block["rows_withheld"] > 0
        json.loads(json.dumps(block))

    def test_audit_block_when_disengaged(self) -> None:
        block = as_of.audit_block()
        assert block["engaged"] is False and block["as_of"] is None


class TestLoaderChokepoint:
    """cached_loader_fetch must bypass the shared cache in historical mode."""

    def test_historical_fetch_is_clipped_and_uncached(self, monkeypatch) -> None:
        from backtest.loaders import base as loader_base

        def _boom(**kwargs):  # cache must not be consulted while time-travelling
            raise AssertionError("shared cache must be bypassed under an as-of clock")

        monkeypatch.setattr(loader_base, "loader_cache_get", _boom)
        monkeypatch.setattr(loader_base, "loader_cache_put", _boom)

        with as_of.as_of_scope("2021-06-30"):
            out = loader_base.cached_loader_fetch(
                source="test", symbol="A.US", timeframe="1D",
                start_date="2021-01-01", end_date="2026-01-01",
                fields=None, fetch=lambda: _frame(),
            )
        assert out is not None
        assert out.index.max() <= pd.Timestamp("2021-06-30")

    def test_window_after_as_of_returns_none(self) -> None:
        from backtest.loaders import base as loader_base

        with as_of.as_of_scope("2021-06-30"):
            out = loader_base.cached_loader_fetch(
                source="test", symbol="A.US", timeframe="1D",
                start_date="2022-01-01", end_date="2023-01-01",
                fields=None,
                fetch=lambda: pytest.fail("fetch must not run for a future-only window"),
            )
        assert out is None
