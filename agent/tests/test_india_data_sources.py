"""Verified India public data-source loaders: NSE, Moneycontrol, Groww.

All HTTP is mocked — these tests never touch the network. They pin the parsing
contract (correct OHLCV frame, inclusive-window clipping, ascending index),
symbol scoping (NSE/BSE handling), the daily-only guard, and the india_equity
fallback-chain wiring that routes public India symbols through these sources
(and no longer through a broker login).
"""

from __future__ import annotations

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fallback-chain wiring
# ---------------------------------------------------------------------------


def test_india_chain_uses_public_sources_not_broker() -> None:
    from backtest.loaders import registry

    registry._ensure_registered()
    chain = registry.FALLBACK_CHAINS["india_equity"]
    assert chain == ["yahoo", "groww", "nse", "moneycontrol", "yfinance", "local"]
    assert "india_broker" not in chain
    # New sources are registered and are accepted config source names.
    for name in ("nse", "moneycontrol", "groww"):
        assert name in registry.LOADER_REGISTRY
        assert name in registry.VALID_SOURCES


# ---------------------------------------------------------------------------
# NSE loader
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _nse_payload():
    # NSE returns most-recent-first; the loader must sort ascending.
    return {
        "data": [
            {
                "CH_TIMESTAMP": "2024-01-03",
                "CH_OPENING_PRICE": 101.0,
                "CH_TRADE_HIGH_PRICE": 105.0,
                "CH_TRADE_LOW_PRICE": 100.0,
                "CH_CLOSING_PRICE": 104.0,
                "CH_TOT_TRADED_QTY": 2000,
            },
            {
                "CH_TIMESTAMP": "2024-01-02",
                "CH_OPENING_PRICE": 100.0,
                "CH_TRADE_HIGH_PRICE": 102.0,
                "CH_TRADE_LOW_PRICE": 99.0,
                "CH_CLOSING_PRICE": 101.0,
                "CH_TOT_TRADED_QTY": 1000,
            },
        ]
    }


def test_nse_fetch_parses_and_sorts(monkeypatch) -> None:
    from backtest.loaders import nse_loader

    def fake_get(url, **kwargs):
        # Home-page prime returns a bare 200; the API returns the payload.
        if url.endswith("/api/historical/cm/equity"):
            return _FakeResponse(200, _nse_payload())
        return _FakeResponse(200, {})

    monkeypatch.setattr(nse_loader, "throttled_get", fake_get)
    out = nse_loader.DataLoader().fetch(["RELIANCE.NS"], "2024-01-01", "2024-01-31")

    assert set(out) == {"RELIANCE.NS"}
    df = out["RELIANCE.NS"]
    assert list(df.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert list(df["close"]) == [101.0, 104.0]
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_nse_declines_bse_and_intraday(monkeypatch) -> None:
    from backtest.loaders import nse_loader

    monkeypatch.setattr(
        nse_loader, "throttled_get",
        lambda url, **kw: _FakeResponse(200, _nse_payload()),
    )
    # BSE symbol is not served by the NSE-only feed.
    assert nse_loader.DataLoader().fetch(["500325.BO"], "2024-01-01", "2024-01-31") == {}
    # NSE public history is daily-only.
    assert nse_loader.DataLoader().fetch(
        ["RELIANCE.NS"], "2024-01-01", "2024-01-31", interval="5m"
    ) == {}


def test_nse_reprimes_on_403(monkeypatch) -> None:
    from backtest.loaders import nse_loader

    monkeypatch.setattr(nse_loader, "_primed", False, raising=False)
    calls = {"api": 0}

    def fake_get(url, **kwargs):
        if url.endswith("/api/historical/cm/equity"):
            calls["api"] += 1
            if calls["api"] == 1:
                return _FakeResponse(403, {})  # stale cookie → forces a re-prime
            return _FakeResponse(200, _nse_payload())
        return _FakeResponse(200, {})

    monkeypatch.setattr(nse_loader, "throttled_get", fake_get)
    out = nse_loader.DataLoader().fetch(["SBIN.NS"], "2024-01-01", "2024-01-31")
    assert "SBIN.NS" in out
    assert calls["api"] == 2  # first 403, retried once after re-prime


# ---------------------------------------------------------------------------
# Moneycontrol loader
# ---------------------------------------------------------------------------


def test_moneycontrol_resolves_ticker_then_history(monkeypatch) -> None:
    from backtest.loaders import moneycontrol_loader

    moneycontrol_loader._TICKER_CACHE.clear()

    def fake_json(url, **kwargs):
        if url.endswith("/search"):
            return [{"symbol": "RELIANCE", "exchange": "NSE", "ticker": "RI"}]
        assert kwargs["params"]["symbol"] == "RI"  # resolved ticker used for history
        return {
            "s": "ok",
            "t": [1704153600, 1704240000],  # 2024-01-02, 2024-01-03 (UTC)
            "o": [100.0, 101.0],
            "h": [102.0, 105.0],
            "l": [99.0, 100.0],
            "c": [101.0, 104.0],
            "v": [1000, 2000],
        }

    monkeypatch.setattr(moneycontrol_loader, "throttled_get_json", fake_json)
    out = moneycontrol_loader.DataLoader().fetch(["RELIANCE.NS"], "2024-01-01", "2024-01-31")
    assert set(out) == {"RELIANCE.NS"}
    df = out["RELIANCE.NS"]
    assert list(df["close"]) == [101.0, 104.0]
    assert df.index.is_monotonic_increasing


def test_moneycontrol_unresolved_symbol_omitted(monkeypatch) -> None:
    from backtest.loaders import moneycontrol_loader

    moneycontrol_loader._TICKER_CACHE.clear()
    monkeypatch.setattr(
        moneycontrol_loader, "throttled_get_json",
        lambda url, **kw: [] if url.endswith("/search") else {"s": "no_data"},
    )
    assert moneycontrol_loader.DataLoader().fetch(
        ["NOSUCH.NS"], "2024-01-01", "2024-01-31"
    ) == {}


# ---------------------------------------------------------------------------
# Groww loader
# ---------------------------------------------------------------------------


def test_groww_parses_candles(monkeypatch) -> None:
    from backtest.loaders import groww_loader

    def fake_json(url, **kwargs):
        assert "/exchange/NSE/segment/CASH/RELIANCE" in url
        return {
            "candles": [
                [1704153600, 100.0, 102.0, 99.0, 101.0, 1000],
                [1704240000, 101.0, 105.0, 100.0, 104.0, 2000],
            ]
        }

    monkeypatch.setattr(groww_loader, "throttled_get_json", fake_json)
    out = groww_loader.DataLoader().fetch(["RELIANCE.NS"], "2024-01-01", "2024-01-31")
    assert set(out) == {"RELIANCE.NS"}
    df = out["RELIANCE.NS"]
    assert list(df["close"]) == [101.0, 104.0]
    assert list(df["volume"]) == [1000.0, 2000.0]


def test_groww_handles_millisecond_epochs(monkeypatch) -> None:
    from backtest.loaders import groww_loader

    monkeypatch.setattr(
        groww_loader, "throttled_get_json",
        lambda url, **kw: {"candles": [[1704153600000, 100.0, 102.0, 99.0, 101.0, 1000]]},
    )
    out = groww_loader.DataLoader().fetch(["TCS.NS"], "2024-01-01", "2024-01-31")
    assert list(out["TCS.NS"].index) == [pd.Timestamp("2024-01-02")]


def test_groww_declines_bse(monkeypatch) -> None:
    from backtest.loaders import groww_loader

    monkeypatch.setattr(
        groww_loader, "throttled_get_json",
        lambda url, **kw: {"candles": [[1704153600, 1, 1, 1, 1, 1]]},
    )
    assert groww_loader.DataLoader().fetch(["500325.BO"], "2024-01-01", "2024-01-31") == {}
