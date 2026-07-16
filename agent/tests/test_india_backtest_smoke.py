"""End-to-end smoke test: backtest runs on Indian (NSE) symbols.

Drives ``IndiaEquityEngine`` so strategies can run on NSE/BSE data with the
India cost stack. This test feeds NSE bars through a fake loader + trivial long
signal and asserts:

  1. The backtest completes and emits metrics + a run card.
  2. India trading costs are actually applied — the identical strategy on the
     zero-commission US engine ends with strictly more cash than on the India
     engine.

All data is in-memory; no network access.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.engines.global_equity import GlobalEquityEngine
from backtest.engines.india_equity import IndiaEquityEngine
from backtest.engines._market_hooks import normalize_market_symbol


_REQUESTED_NSE_CODES = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "ITC", "LT", "TATAMOTORS", "SBIN", "BHARTIARTL",
]


def _nse_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2024-04-01", periods=5)
    return pd.DataFrame(
        {
            "open": [100.0, 102.0, 104.0, 106.0, 108.0],
            "high": [101.0, 103.0, 105.0, 107.0, 109.0],
            "low": [99.0, 101.0, 103.0, 105.0, 107.0],
            "close": [102.0, 104.0, 106.0, 108.0, 110.0],
            "volume": [10_000, 10_000, 10_000, 10_000, 10_000],
        },
        index=dates,
    )


class _FakeLoader:
    def __init__(self, code: str, bars: pd.DataFrame) -> None:
        self._code = code
        self._bars = bars

    def fetch(self, *args, **kwargs):
        return {self._code: self._bars.copy()}


class _LongSignal:
    """Allocate fully long to the single instrument every bar."""

    def __init__(self, code: str) -> None:
        self._code = code

    def generate(self, data_map):
        idx = data_map[self._code].index
        return {self._code: pd.Series(1.0, index=idx)}


class _MultiLoader:
    def __init__(self, bars_by_code: dict[str, pd.DataFrame]) -> None:
        self._bars_by_code = bars_by_code

    def fetch(self, codes, *args, **kwargs):
        return {code: self._bars_by_code[code].copy() for code in codes}


class _SupertrendRiskSignal:
    """Small reference implementation for the exact user regression case."""

    def generate(self, data_map):
        signals = {}
        for code, frame in data_map.items():
            close = frame["close"].astype(float)
            high = frame["high"].astype(float)
            low = frame["low"].astype(float)
            previous = close.shift(1)
            tr = pd.concat(
                [(high - low), (high - previous).abs(), (low - previous).abs()],
                axis=1,
            ).max(axis=1)
            atr = tr.ewm(alpha=0.1, adjust=False, min_periods=10).mean()
            midpoint = (high + low) / 2.0
            upper = (midpoint + 3.0 * atr).copy()
            lower = (midpoint - 3.0 * atr).copy()
            direction = pd.Series(0, index=frame.index, dtype=int)
            for i in range(1, len(frame)):
                if pd.isna(atr.iloc[i]):
                    continue
                if not pd.isna(upper.iloc[i - 1]):
                    if upper.iloc[i] >= upper.iloc[i - 1] and close.iloc[i - 1] <= upper.iloc[i - 1]:
                        upper.iloc[i] = upper.iloc[i - 1]
                    if lower.iloc[i] <= lower.iloc[i - 1] and close.iloc[i - 1] >= lower.iloc[i - 1]:
                        lower.iloc[i] = lower.iloc[i - 1]
                    direction.iloc[i] = direction.iloc[i - 1]
                    if close.iloc[i] > upper.iloc[i - 1]:
                        direction.iloc[i] = 1
                    elif close.iloc[i] < lower.iloc[i - 1]:
                        direction.iloc[i] = -1

            weights = pd.Series(0.0, index=frame.index)
            active = False
            stop = target = 0.0
            weight = 0.0
            for i in range(1, len(frame)):
                buy_flip = direction.iloc[i] == 1 and direction.iloc[i - 1] != 1
                sell_flip = direction.iloc[i] == -1 and direction.iloc[i - 1] != -1
                if active:
                    # Conservative same-bar ordering: stop takes precedence.
                    if low.iloc[i] <= stop or high.iloc[i] >= target or sell_flip:
                        active = False
                        weight = 0.0
                elif buy_flip and pd.notna(atr.iloc[i]):
                    entry = close.iloc[i]
                    stop_distance = max(entry - lower.iloc[i], atr.iloc[i], 0.01)
                    stop = entry - stop_distance
                    target = entry + 2.0 * stop_distance
                    weight = min(1.0, 0.01 * entry / stop_distance)
                    active = True
                weights.iloc[i] = weight if active else 0.0
            signals[code] = weights
        return signals


def _intraday_wave_bars(offset: float) -> pd.DataFrame:
    import numpy as np

    sessions = []
    for day in pd.bdate_range("2026-06-15", periods=8):
        sessions.extend(pd.date_range(day + pd.Timedelta(hours=9, minutes=15), periods=25, freq="15min"))
    index = pd.DatetimeIndex(sessions)
    x = np.arange(len(index), dtype=float)
    close = 100.0 + offset + 0.02 * x + 5.0 * np.sin(x / 8.0)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + 0.40,
            "low": np.minimum(open_, close) - 0.40,
            "close": close,
            "volume": np.full(len(index), 100_000.0),
        },
        index=index,
    )


def _run(engine, code: str, run_dir: Path) -> dict:
    bars = _nse_bars()
    return engine.run_backtest(
        {
            "codes": [code],
            "start_date": "2024-04-01",
            "end_date": "2024-04-30",
            "source": "yahoo",
            "initial_cash": 1_000_000,
        },
        _FakeLoader(code, bars),
        _LongSignal(code),
        run_dir,
    )


def test_india_backtest_completes_and_emits_run_card(tmp_path: Path) -> None:
    engine = IndiaEquityEngine({"initial_cash": 1_000_000})
    metrics = _run(engine, "RELIANCE.NS", tmp_path)

    assert metrics  # non-empty metrics dict
    assert (tmp_path / "run_card.json").exists()
    # The equity curve must have advanced through the bars.
    assert metrics.get("final_value") is not None
    assert metrics["trade_count"] >= 1


def test_india_costs_are_applied_vs_zero_commission_us(tmp_path: Path) -> None:
    """Identical data + signal: the India engine pays costs the US engine does not."""
    in_engine = IndiaEquityEngine({"initial_cash": 1_000_000})
    us_engine = GlobalEquityEngine({"initial_cash": 1_000_000}, market="us")

    in_metrics = _run(in_engine, "RELIANCE.NS", tmp_path / "in")
    us_metrics = _run(us_engine, "AAPL.US", tmp_path / "us")

    # Same price path; the only difference is India's cost stack, so India must
    # end strictly poorer than the zero-commission US run.
    assert in_metrics["final_value"] < us_metrics["final_value"]


def test_ten_stock_15m_supertrend_risk_backtest_completes(tmp_path: Path) -> None:
    """Regression: the reported ten-stock prompt must not crash the engine."""
    codes = [normalize_market_symbol(code) for code in _REQUESTED_NSE_CODES]
    bars = {code: _intraday_wave_bars(i * 3.0) for i, code in enumerate(codes)}
    config = {
        "codes": codes,
        "start_date": "2026-06-15",
        "end_date": "2026-06-26",
        "source": "yahoo",
        "interval": "15m",
        "initial_cash": 1_000_000,
    }
    engine = IndiaEquityEngine(config)
    metrics = engine.run_backtest(
        config,
        _MultiLoader(bars),
        _SupertrendRiskSignal(),
        tmp_path,
        bars_per_year=252 * 25,
    )

    assert set(codes) == set(bars)
    assert metrics["trade_count"] >= len(codes)
    assert (tmp_path / "artifacts" / "metrics.csv").exists()
    assert (tmp_path / "artifacts" / "equity.csv").exists()
