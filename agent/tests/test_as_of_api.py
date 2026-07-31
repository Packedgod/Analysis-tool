"""Tests for the point-in-time clock's user-facing entry points.

Covers the two ways a study can engage the clock:
  * ``config.json``'s ``as_of`` for a full backtest run (validated, fails loud
    on a bad date), and
  * the ``as_of`` field on the quant-lab API requests, scoped per request.

Network is never touched: ``_history``'s yfinance call is monkeypatched.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest import as_of
from backtest.runner import BacktestConfigSchema


@pytest.fixture(autouse=True)
def _clean_clock():
    token = as_of.set_as_of(None)
    yield
    as_of.reset_as_of(token)


class TestConfigSchema:
    def _base(self, **kw):
        return {"codes": ["AAPL.US"], "start_date": "2020-01-01", "end_date": "2024-01-01", **kw}

    def test_as_of_optional(self) -> None:
        assert BacktestConfigSchema(**self._base()).as_of is None

    def test_valid_as_of_accepted(self) -> None:
        assert BacktestConfigSchema(**self._base(as_of="2021-06-30")).as_of == "2021-06-30"

    def test_blank_treated_as_unset(self) -> None:
        assert BacktestConfigSchema(**self._base(as_of="   ")).as_of is None

    def test_malformed_as_of_fails_loudly(self) -> None:
        # A silently-ignored as_of would be a look-ahead leak, so this must raise.
        with pytest.raises(Exception, match="as_of"):
            BacktestConfigSchema(**self._base(as_of="not-a-date"))


class TestQuantLabHistoryUnderClock:
    """_history must clip to the clock and re-anchor relative periods."""

    def _fake_yf(self, monkeypatch, captured: dict):
        import src.api.quant_labs_routes as labs

        idx = pd.date_range("2018-01-01", "2026-01-01", freq="B")
        frame = pd.DataFrame(
            {"Close": np.linspace(100, 300, len(idx)), "Open": np.linspace(100, 300, len(idx))},
            index=idx,
        )

        class _FakeYF:
            @staticmethod
            def download(names, **kwargs):
                captured.update(kwargs)
                if kwargs.get("start"):
                    lo = pd.Timestamp(kwargs["start"])
                    hi = pd.Timestamp(kwargs["end"])
                    return frame.loc[(frame.index >= lo) & (frame.index < hi)].copy()
                return frame.copy()

        monkeypatch.setitem(__import__("sys").modules, "yfinance", _FakeYF)
        return labs

    def test_live_request_unclipped(self, monkeypatch) -> None:
        captured: dict = {}
        labs = self._fake_yf(monkeypatch, captured)
        out = labs._history(["AAPL"], "5y")
        assert out["AAPL"].index.max() > pd.Timestamp("2025-01-01")
        assert "period" in captured  # relative period used when live

    def test_clock_clips_and_reanchors(self, monkeypatch) -> None:
        captured: dict = {}
        labs = self._fake_yf(monkeypatch, captured)
        with as_of.as_of_scope("2021-06-30"):
            out = labs._history(["AAPL"], "2y")
        assert out["AAPL"].index.max() <= pd.Timestamp("2021-06-30")
        # window re-anchored to the as-of date rather than today
        assert pd.Timestamp(captured["start"]) < pd.Timestamp("2021-06-30")
        assert pd.Timestamp(captured["end"]) <= pd.Timestamp("2021-07-02")

    def test_clipped_history_still_has_depth(self, monkeypatch) -> None:
        captured: dict = {}
        labs = self._fake_yf(monkeypatch, captured)
        with as_of.as_of_scope("2021-06-30"):
            out = labs._history(["AAPL"], "5y")
        # a 5y window ending at the as-of date, not an empty frame
        assert len(out["AAPL"]) > 200


class TestEndpointWiring:
    """A request carrying as_of must run under the clock and report the audit."""

    def _client(self):
        from fastapi.testclient import TestClient

        import api_server

        return TestClient(api_server.app, client=("127.0.0.1", 50000))

    def _stub_history(self, monkeypatch):
        import src.api.quant_labs_routes as labs

        def _fake(tickers, period="2y", interval="1d"):
            cutoff = as_of.get_as_of()
            end = cutoff if cutoff is not None else pd.Timestamp("2026-01-01")
            idx = pd.date_range(end=end, periods=400, freq="B")
            frame = pd.DataFrame(
                {"Close": np.linspace(100, 200, len(idx)), "Open": np.linspace(100, 200, len(idx))},
                index=idx,
            )
            # exercise the real enforcement path
            return {t.strip().upper(): as_of.enforce_frame(frame.copy(), label=t) for t in tickers}

        monkeypatch.setattr(labs, "_history", _fake)

    def test_as_of_request_reports_point_in_time_block(self, monkeypatch) -> None:
        self._stub_history(monkeypatch)
        r = self._client().post("/quant/backtest", json={"ticker": "SPY", "as_of": "2021-06-30"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["point_in_time"]["engaged"] is True
        assert body["point_in_time"]["as_of"] == "2021-06-30"
        # no series point may postdate the as-of date
        assert max(row["date"] for row in body["series"]) < "2021-07-01"

    def test_live_request_has_no_point_in_time_block(self, monkeypatch) -> None:
        self._stub_history(monkeypatch)
        r = self._client().post("/quant/backtest", json={"ticker": "SPY"})
        assert r.status_code == 200, r.text
        assert "point_in_time" not in r.json()

    def test_clock_does_not_leak_between_requests(self, monkeypatch) -> None:
        self._stub_history(monkeypatch)
        client = self._client()
        client.post("/quant/backtest", json={"ticker": "SPY", "as_of": "2021-06-30"})
        assert as_of.get_as_of() is None  # scope exited
        r = client.post("/quant/backtest", json={"ticker": "SPY"})
        assert "point_in_time" not in r.json()


class TestRequestModels:
    def test_history_models_expose_as_of(self) -> None:
        import src.api.quant_labs_routes as labs

        for model in (labs.BacktestRequest, labs.PairsRequest, labs.TickersRequest,
                      labs.MonteCarloRequest, labs.FactorRequest, labs.PortfolioRequest):
            assert "as_of" in model.model_fields, model.__name__
            assert model().as_of is None  # live by default

    def test_simulation_only_models_have_no_as_of(self) -> None:
        import src.api.quant_labs_routes as labs

        # Pure simulations fetch no history, so a clock would be meaningless.
        for model in (labs.OptionsRequest, labs.OrderBookRequest):
            assert "as_of" not in model.model_fields, model.__name__
