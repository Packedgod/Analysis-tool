"""Tests for the live launcher checks without making network calls."""

from __future__ import annotations

import datetime as dt
import time

import pandas as pd

from src import runtime_self_test


class _Loader:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def fetch(self, codes, start_date, end_date, *, interval):
        assert codes == ["^NSEI"]
        assert start_date == "2026-06-22"
        assert end_date == "2026-07-13"
        assert interval == "1D"
        return {"^NSEI": self.frame} if not self.frame.empty else {}


def _ohlc_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [25000.0, 25100.0],
            "high": [25200.0, 25300.0],
            "low": [24900.0, 25000.0],
            "close": [25100.0, 25200.0],
            "volume": [0.0, 0.0],
        },
        index=pd.to_datetime(["2026-07-10", "2026-07-13"]),
    )


def test_nifty_market_check_requires_real_ohlc_bars() -> None:
    frame = _ohlc_frame()
    result = runtime_self_test.check_nifty_market_data(
        lambda: _Loader(frame),
        today=dt.date(2026, 7, 13),
    )

    assert result.ok is True
    assert "2 recent daily bars" in result.message


def test_nifty_market_check_rejects_empty_provider_result() -> None:
    result = runtime_self_test.check_nifty_market_data(
        lambda: _Loader(pd.DataFrame()),
        today=dt.date(2026, 7, 13),
    )

    assert result.ok is False
    assert "no recent daily bars" in result.message


def test_hosted_search_check_requires_cited_url() -> None:
    ok = runtime_self_test.check_hosted_web_search(
        lambda query, limit: [{"title": "NSE", "url": "https://www.nseindia.com/"}]
    )
    empty = runtime_self_test.check_hosted_web_search(lambda query, limit: [])

    assert ok.ok is True
    assert empty.ok is False


def test_runtime_self_test_collects_failures_without_raising() -> None:
    results = runtime_self_test.run_runtime_self_test(
        [
            lambda: runtime_self_test.RuntimeCheck("one", True, "ready"),
            lambda: runtime_self_test.RuntimeCheck("two", False, "unavailable"),
        ]
    )

    assert [result.ok for result in results] == [True, False]


def test_runtime_self_test_bounds_a_stuck_provider_check() -> None:
    def stuck() -> runtime_self_test.RuntimeCheck:
        time.sleep(0.2)
        return runtime_self_test.RuntimeCheck("late", True, "too late")

    started = time.monotonic()
    results = runtime_self_test.run_runtime_self_test([stuck], timeout_seconds=0.01)

    assert time.monotonic() - started < 0.15
    assert results[0].ok is False
    assert "timed out" in results[0].message
