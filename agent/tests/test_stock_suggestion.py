"""suggest_stocks: cross-sectional factor ranking of a candidate universe."""

import json

from src.tools.stock_suggestion_tool import SuggestStocksTool


def _series(start: float, drift: float, n: int = 260) -> list[dict]:
    """A deterministic upward/downward close series as OHLCV records."""
    out = []
    price = start
    for i in range(n):
        price *= (1 + drift)
        out.append({"trade_date": f"2024-{1 + i // 21:02d}-{1 + i % 21:02d}T00:00:00", "close": round(price, 2)})
    return out


def test_ranks_stronger_trend_higher(monkeypatch) -> None:
    def fake_fetch(*, codes, start_date, end_date, source="auto", max_rows=0, **_):
        return {
            "STRONG.NS": _series(100.0, 0.004),   # steady climber
            "WEAK.NS": _series(100.0, -0.002),    # steady decliner
            "FLAT.NS": _series(100.0, 0.0005),    # barely moving
        }

    monkeypatch.setattr("src.market_data.fetch_market_data", fake_fetch)
    out = json.loads(SuggestStocksTool().execute(codes=["STRONG.NS", "WEAK.NS", "FLAT.NS"], top_n=3))
    assert out["status"] == "ok"
    assert out["evaluated"] == 3
    ranked = [s["code"] for s in out["suggestions"]]
    assert ranked[0] == "STRONG.NS"
    assert ranked.index("STRONG.NS") < ranked.index("WEAK.NS")
    assert all("factors" in s and "score" in s for s in out["suggestions"])


def test_excludes_symbols_without_enough_history(monkeypatch) -> None:
    def fake_fetch(*, codes, start_date, end_date, source="auto", max_rows=0, **_):
        return {
            "GOOD.NS": _series(100.0, 0.003),
            "SHORT.NS": _series(100.0, 0.003, n=10),   # too short to score
            "EMPTY.NS": [],
        }

    monkeypatch.setattr("src.market_data.fetch_market_data", fake_fetch)
    out = json.loads(SuggestStocksTool().execute(codes=["GOOD.NS", "SHORT.NS", "EMPTY.NS", "MISSING.NS"]))
    # Only one scorable -> cannot rank cross-sectionally
    assert out["status"] == "unavailable"
    reasons = {e["code"]: e["reason"] for e in out["excluded"]}
    assert "SHORT.NS" in reasons and "EMPTY.NS" in reasons and "MISSING.NS" in reasons


def test_requires_at_least_two_codes() -> None:
    out = json.loads(SuggestStocksTool().execute(codes=["ONLY.NS"]))
    assert out["status"] == "error"


def test_tool_is_registered_and_readonly() -> None:
    from src.tools import build_registry

    assert "suggest_stocks" in build_registry().tool_names
    assert SuggestStocksTool.is_readonly is True
