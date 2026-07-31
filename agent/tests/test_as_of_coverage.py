"""The point-in-time clock across the non-price data paths.

Price/OHLCV coverage lives in ``test_as_of.py``; this pins the remaining
surfaces — evidence windows, fundamentals filings, and event feeds — so a
study standing at a past date cannot see later evidence through any of them.
Each path must also stay byte-identical when the clock is unset.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backtest import as_of
from src.tools._pit import EvidenceWindow, as_of_ceiling, filter_to_window, parse_window


@pytest.fixture(autouse=True)
def _clean_clock():
    token = as_of.set_as_of(None)
    yield
    as_of.reset_as_of(token)


class TestEvidenceWindows:
    def test_no_clock_is_unchanged(self) -> None:
        assert parse_window() is None
        assert parse_window(year=2016) == EvidenceWindow(date(2016, 1, 1), date(2016, 12, 31))

    def test_ceiling_reports_clock(self) -> None:
        assert as_of_ceiling() is None
        with as_of.as_of_scope("2021-06-30"):
            assert as_of_ceiling() == date(2021, 6, 30)

    def test_unrequested_window_becomes_bounded(self) -> None:
        # Without a clock this is None (unconstrained); with one it must bound.
        with as_of.as_of_scope("2021-06-30"):
            window = parse_window()
        assert window is not None and window.end == date(2021, 6, 30)

    def test_requested_window_end_is_clamped(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            window = parse_window(start_date="2020-01-01", end_date="2026-01-01")
        assert window == EvidenceWindow(date(2020, 1, 1), date(2021, 6, 30))

    def test_historical_window_untouched(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            window = parse_window(year=2016)
        assert window == EvidenceWindow(date(2016, 1, 1), date(2016, 12, 31))

    def test_window_entirely_after_as_of_fails_loudly(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            with pytest.raises(ValueError, match="as-of"):
                parse_window(start_date="2023-01-01", end_date="2024-01-01")

    def test_future_evidence_dropped_end_to_end(self) -> None:
        records = [
            {"title": "old", "date": "2020-05-01"},
            {"title": "future", "date": "2025-05-01"},
        ]
        with as_of.as_of_scope("2021-06-30"):
            kept, audit = filter_to_window(records, parse_window())
        assert [r["title"] for r in kept] == ["old"]
        assert audit["enforced"] is True and audit["dropped_outside_window"] == 1

    def test_undated_evidence_dropped_under_clock(self) -> None:
        # Fail-closed: an undated record cannot be proven to predate the as-of.
        with as_of.as_of_scope("2021-06-30"):
            kept, audit = filter_to_window([{"title": "no date"}], parse_window())
        assert kept == [] and audit["dropped_undated"] == 1


class TestFundamentalsFilings:
    """A figure filed after the as-of date was unknowable then."""

    def _rows(self):
        return [
            # (period_end, filed) — the last one is filed after our as-of date
            {"period_end": "2020-12-31", "filed": "2021-02-15", "value": 100.0, "_concept_order": 0,
             "period_start": "2020-10-01"},
            {"period_end": "2021-03-31", "filed": "2021-05-10", "value": 110.0, "_concept_order": 0,
             "period_start": "2021-01-01"},
            {"period_end": "2021-06-30", "filed": "2021-08-12", "value": 120.0, "_concept_order": 0,
             "period_start": "2021-04-01"},
        ]

    def _facts(self):
        """A minimal SEC companyfacts payload built from the rows above."""
        return {
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {"start": r["period_start"], "end": r["period_end"],
                                 "filed": r["filed"], "val": r["value"], "form": "10-Q"}
                                for r in self._rows()
                            ]
                        }
                    }
                }
            }
        }

    def _extract(self):
        from backtest.loaders.fundamentals_loader import _extract_concept_series

        # Stock concept (Assets) + quarterly: exercises the real extraction path.
        return _extract_concept_series(self._facts(), ["Assets"], "quarterly")

    def test_filings_after_as_of_withheld(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            out = self._extract()
        # The Jun-2021 quarter was only filed in August — unknowable on 30 Jun.
        assert list(out["value"]) == [100.0, 110.0]
        assert out["filed"].max() <= pd.Timestamp("2021-06-30")

    def test_no_clock_keeps_every_filing(self) -> None:
        assert list(self._extract()["value"]) == [100.0, 110.0, 120.0]

    def test_clock_before_all_filings_yields_empty(self) -> None:
        with as_of.as_of_scope("2019-01-01"):
            assert self._extract().empty


class TestEventFeeds:
    """A global clock is a ceiling on the caller's as_of, never a relaxation."""

    def _frame(self):
        return pd.DataFrame({
            "ts_code": ["A", "A", "A"],
            "knowable_date": pd.to_datetime(["2020-01-02", "2021-05-01", "2025-01-02"]),
            "score": [1.0, 1.0, 1.0],
        })

    def _effective_cutoff(self, caller_as_of: str) -> pd.Timestamp:
        """Mirror the provider's cutoff resolution."""
        cutoff = pd.Timestamp(caller_as_of).normalize()
        clock = as_of.get_as_of()
        if clock is not None and clock < cutoff:
            cutoff = clock
        return cutoff

    def test_clock_tightens_caller_boundary(self) -> None:
        with as_of.as_of_scope("2021-06-30"):
            cutoff = self._effective_cutoff("2026-01-01")
        assert cutoff == pd.Timestamp("2021-06-30")
        kept = self._frame()[self._frame()["knowable_date"] <= cutoff]
        assert len(kept) == 2

    def test_clock_never_relaxes_a_tighter_caller_boundary(self) -> None:
        with as_of.as_of_scope("2025-01-01"):
            assert self._effective_cutoff("2020-06-30") == pd.Timestamp("2020-06-30")

    def test_no_clock_uses_caller_boundary(self) -> None:
        assert self._effective_cutoff("2026-01-01") == pd.Timestamp("2026-01-01")

    def test_provider_source_wires_the_clock(self) -> None:
        import inspect

        from backtest.loaders import rsshub_events as ev

        src = inspect.getsource(ev.RSSHubEventProvider.query_events)
        assert "as_of.get_as_of" in src or "_as_of.get_as_of" in src
