"""Provider schema-drift guards shared by the loaders.

The failure these exist to catch is not a network error — it is a provider
quietly renaming a column so the mapping misses and a synthesized default
(``volume = 0.0``) takes its place. The feed then looks healthy while every
volume-themed factor computes on zeros.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from backtest.loaders.base import audit_provider_columns, flag_degenerate_columns

_OHLCV = ("open", "high", "low", "close", "volume")


def _frame(**overrides) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=20, freq="D")
    data = {c: np.linspace(10, 20, len(idx)) for c in ("open", "high", "low", "close")}
    data["volume"] = np.linspace(1_000, 2_000, len(idx))
    data.update(overrides)
    return pd.DataFrame(data, index=idx)


class TestAuditProviderColumns:
    def test_no_missing_columns_is_silent(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            assert audit_provider_columns(_frame(), _OHLCV, source="yahoo") == []
        assert caplog.records == []

    def test_missing_column_is_reported_and_logged(self, caplog) -> None:
        frame = _frame().drop(columns=["volume"])
        with caplog.at_level(logging.WARNING):
            missing = audit_provider_columns(frame, _OHLCV, source="yahoo", symbol="AAPL.US")
        assert missing == ["volume"]
        assert "schema drift" in caplog.text
        assert "yahoo/AAPL.US" in caplog.text

    def test_log_names_the_columns_actually_present(self, caplog) -> None:
        # A rename is only actionable if the new name is visible.
        frame = _frame().rename(columns={"volume": "vol_traded"})
        with caplog.at_level(logging.WARNING):
            audit_provider_columns(frame, _OHLCV, source="nse")
        assert "vol_traded" in caplog.text

    def test_none_frame_reports_everything_missing(self) -> None:
        assert audit_provider_columns(None, _OHLCV, source="x") == list(_OHLCV)


class TestFlagDegenerateColumns:
    def test_healthy_volume_is_silent(self, caplog) -> None:
        with caplog.at_level(logging.WARNING):
            assert flag_degenerate_columns(_frame(), source="yahoo") == []
        assert caplog.records == []

    def test_all_zero_volume_flagged(self, caplog) -> None:
        # The fingerprint of a synthesized default standing in for a rename.
        with caplog.at_level(logging.WARNING):
            flagged = flag_degenerate_columns(_frame(volume=0.0), source="yahoo", symbol="X.US")
        assert flagged == ["volume"]
        assert "all-zero" in caplog.text

    def test_all_nan_volume_flagged(self) -> None:
        assert flag_degenerate_columns(_frame(volume=np.nan), source="yahoo") == ["volume"]

    def test_partially_zero_volume_not_flagged(self) -> None:
        # Real markets have quiet days; only a wholly dead column is suspect.
        vol = np.linspace(1_000, 2_000, 20)
        vol[:10] = 0.0
        assert flag_degenerate_columns(_frame(volume=vol), source="yahoo") == []

    def test_empty_frame_is_not_flagged(self) -> None:
        assert flag_degenerate_columns(pd.DataFrame(), source="yahoo") == []

    def test_absent_column_is_not_flagged_here(self) -> None:
        # Absence is audit_provider_columns' job; this guard only judges content.
        assert flag_degenerate_columns(_frame().drop(columns=["volume"]), source="yahoo") == []


class TestLoaderIntegration:
    """The guards must actually be reachable from the loaders that synthesize."""

    def test_yahoo_rows_to_frame_flags_missing_volume(self, caplog) -> None:
        from backtest.loaders.yahoo_loader import _rows_to_frame

        rows = [
            {"trade_date": 1704067200 + i * 86400, "open": 10.0, "high": 11.0,
             "low": 9.0, "close": 10.5}
            for i in range(5)
        ]
        with caplog.at_level(logging.WARNING):
            frame = _rows_to_frame(rows, "2024-01-01", "2024-01-31")
        # The bars still load (volume defaulted) but the drift is on the record.
        assert not frame.empty
        assert "schema drift" in caplog.text or "all-zero" in caplog.text

    def test_yahoo_healthy_payload_is_silent(self, caplog) -> None:
        from backtest.loaders.yahoo_loader import _rows_to_frame

        rows = [
            {"trade_date": 1704067200 + i * 86400, "open": 10.0, "high": 11.0,
             "low": 9.0, "close": 10.5, "volume": 1000.0 + i}
            for i in range(5)
        ]
        with caplog.at_level(logging.WARNING):
            frame = _rows_to_frame(rows, "2024-01-01", "2024-01-31")
        assert len(frame) == 5
        assert caplog.records == []


class TestDataHealthEndpoint:
    """Drift must be visible to an operator, not only in the log file."""

    def _client(self):
        from fastapi.testclient import TestClient

        import api_server

        return TestClient(api_server.app, client=("127.0.0.1", 50000))

    def test_reports_ok_when_nothing_observed(self, monkeypatch) -> None:
        from backtest.loaders import base as lb

        monkeypatch.setattr(lb, "_drift_log", [])
        body = self._client().get("/system/data-health").json()
        assert body["status"] == "ok" and body["observations"] == 0

    def test_reports_degraded_and_names_the_source(self, monkeypatch) -> None:
        from backtest.loaders import base as lb

        monkeypatch.setattr(lb, "_drift_log", [])
        audit_provider_columns(
            _frame().drop(columns=["volume"]), _OHLCV, source="yahoo", symbol="AAPL.US",
        )
        body = self._client().get("/system/data-health").json()
        assert body["status"] == "degraded"
        assert "yahoo" in body["sources_affected"]
        assert body["recent"][0]["symbol"] == "AAPL.US"

    def test_drift_log_is_bounded(self, monkeypatch) -> None:
        from backtest.loaders import base as lb

        monkeypatch.setattr(lb, "_drift_log", [])
        frame = _frame().drop(columns=["volume"])
        for _ in range(lb._DRIFT_LOG_MAX + 25):
            audit_provider_columns(frame, _OHLCV, source="yahoo")
        assert len(lb._drift_log) == lb._DRIFT_LOG_MAX
