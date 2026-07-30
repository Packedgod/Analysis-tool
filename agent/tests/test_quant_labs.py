from __future__ import annotations

import math

from fastapi.testclient import TestClient

import api_server
from src.api.quant_labs_routes import OptionsRequest, OrderBookRequest, _options, _order_book


def test_catalog_exposes_all_ten_labs():
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.get("/quant/labs")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["labs"]}
    assert ids == {
        "backtest", "pairs", "options", "order-book", "sentiment",
        "portfolio", "monte-carlo", "volatility-surface", "factor-model",
        "market-dashboard",
    }


def test_black_scholes_matches_reference_value_and_put_call_shape():
    result = _options(OptionsRequest(spot=100, strike=100, expiry_days=365, volatility=.2, risk_free_rate=.05))
    assert math.isclose(result["metrics"]["price"], 10.450584, rel_tol=1e-5)
    assert 0 < result["metrics"]["delta"] < 1
    assert result["metrics"]["gamma"] > 0
    assert len(result["series"]) == 80
    assert result["evidence"]["data_class"] == "simulation"


def test_order_book_is_seeded_and_preserves_positive_spread():
    first = _order_book(OrderBookRequest(seed=7))
    second = _order_book(OrderBookRequest(seed=7))
    assert first["bids"] == second["bids"]
    assert first["asks"] == second["asks"]
    assert first["trades"] == second["trades"]
    assert first["metrics"]["best_bid"] < first["metrics"]["best_ask"]
    assert first["metrics"]["trades_processed"] == 80
    assert first["evidence"]["data_class"] == "simulation"


def test_observed_endpoint_never_fabricates_prices(monkeypatch):
    from src.api import quant_labs_routes as module

    monkeypatch.setattr(module, "_history", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("provider unavailable")))
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    response = client.post("/quant/backtest", json={"ticker": "SPY"})
    assert response.status_code == 400
    assert response.json()["detail"] == "provider unavailable"
