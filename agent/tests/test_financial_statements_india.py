"""India (.NS/.BO) support in get_financial_statements (yfinance-backed)."""

import sys
import types

import pandas as pd

from src.tools import financial_statements_tool as fst


def test_classify_market_recognises_india() -> None:
    assert fst._classify_market("RELIANCE.NS") == "india"
    assert fst._classify_market("500325.BO") == "india"
    assert fst._classify_market("AAPL.US") == "us"
    assert fst._classify_market("FOO.XYZ") is None


def test_error_message_lists_india_suffix() -> None:
    import json

    out = json.loads(fst.FinancialStatementsTool().execute(code="FOO.XYZ"))
    assert out["ok"] is False
    assert ".NS/.BO" in out["error"]


def _fake_yfinance(frame: pd.DataFrame) -> types.ModuleType:
    module = types.ModuleType("yfinance")

    class _Ticker:
        def __init__(self, _code: str) -> None:
            pass

        income_stmt = frame
        balance_sheet = frame
        cashflow = frame
        quarterly_income_stmt = frame

    module.Ticker = _Ticker  # type: ignore[attr-defined]
    return module


def test_india_income_statement_is_shaped_as_periods(monkeypatch) -> None:
    # yfinance layout: line items as index, period-ends as columns (newest first).
    frame = pd.DataFrame(
        {
            pd.Timestamp("2025-03-31"): {"Total Revenue": 100.0, "Net Income": 20.0},
            pd.Timestamp("2024-03-31"): {"Total Revenue": 90.0, "Net Income": float("nan")},
        }
    )
    monkeypatch.setitem(sys.modules, "yfinance", _fake_yfinance(frame))

    import json

    out = json.loads(
        fst.FinancialStatementsTool().execute(code="RELIANCE.NS", statement="income", period="annual")
    )
    assert out["ok"] is True
    assert out["source"] == "yfinance"
    periods = out["data"]["RELIANCE.NS"]["periods"]
    assert [p["period_end"] for p in periods] == ["2025-03-31", "2024-03-31"]
    assert periods[0]["Total Revenue"] == 100.0
    # NaN cells are dropped, never serialised.
    assert "Net Income" not in periods[1]
