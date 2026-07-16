"""Tests for the read-only Groww and Angel One India broker connectors."""

from __future__ import annotations

import pytest

from src.live import registry
from src.live.classification import ToolClass, classify_tool
from src.trading import profiles, service
from src.trading.connectors.angelone import sdk as angel
from src.trading.connectors.angelone.classification import ANGELONE_TOOL_CLASS
from src.trading.connectors.groww import sdk as groww
from src.trading.connectors.groww.classification import GROWW_TOOL_CLASS

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "profile_id,connector",
    [
        ("groww-live-sdk-readonly", "groww"),
        ("angelone-live-sdk-readonly", "angelone"),
    ],
)
def test_india_profiles_registered_readonly(profile_id: str, connector: str) -> None:
    profile = profiles.profile_by_id(profile_id)
    assert profile.connector == connector
    assert profile.environment == "live"
    assert profile.transport == "broker_sdk"
    assert profile.readonly is True
    assert "orders.place" not in profile.capabilities


def test_groww_classification_is_fail_closed() -> None:
    curated = registry._BROKER_CURATED_MAPS["groww"]
    assert GROWW_TOOL_CLASS["get_holdings_for_user"] is ToolClass.READ
    assert GROWW_TOOL_CLASS["place_order"] is ToolClass.WRITE
    assert classify_tool("place_order", None, curated) is ToolClass.WRITE
    assert classify_tool("future_unknown_groww_method", None, curated) is ToolClass.UNKNOWN


def test_angelone_classification_is_fail_closed() -> None:
    curated = registry._BROKER_CURATED_MAPS["angelone"]
    assert ANGELONE_TOOL_CLASS["position"] is ToolClass.READ
    assert ANGELONE_TOOL_CLASS["placeOrder"] is ToolClass.WRITE
    assert classify_tool("placeOrder", None, curated) is ToolClass.WRITE
    assert classify_tool("future_unknown_angel_method", None, curated) is ToolClass.UNKNOWN


def test_groww_unconfigured_service_check(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(groww, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("groww-live-sdk-readonly")
    assert result["status"] == "error"
    assert "access_token or api_key+api_secret" in result["error"]
    assert result["connector"] == "groww"


def test_angelone_unconfigured_service_check(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(angel, "get_runtime_root", lambda: tmp_path)
    result = service.check_connection("angelone-live-sdk-readonly")
    assert result["status"] == "error"
    assert "api_key" in result["error"]
    assert result["connector"] == "angelone"


def test_groww_public_config_redacts_all_secrets() -> None:
    public = groww._public_config(
        groww.GrowwConfig(access_token="access-secret", api_key="KEY12345", api_secret="api-secret")
    )
    assert public["access_token"] == "***redacted***"
    assert public["api_key"] == "KEY1***"
    assert public["api_secret"] == "***redacted***"
    assert "access-secret" not in str(public)
    assert "api-secret" not in str(public)


def test_angelone_public_config_redacts_login_material() -> None:
    public = angel._public_config(
        angel.AngelOneConfig(
            api_key="KEY12345",
            client_code="A123456",
            pin="1234",
            totp_secret="BASE32SECRET",
            jwt_token="jwt-secret",
            refresh_token="refresh-secret",
        )
    )
    assert public["api_key"] == "KEY1***"
    assert public["client_code"] == "***456"
    for secret in ("1234", "BASE32SECRET", "jwt-secret", "refresh-secret"):
        assert secret not in str(public)


def test_groww_positions_combine_intraday_and_holdings(monkeypatch) -> None:
    def fake_get(config, path, *, params=None):
        if path == "/v1/positions/user":
            assert params == {"segment": "CASH"}
            return {"positions": [{"trading_symbol": "NIFTY25JULFUT", "net_quantity": 50, "segment": "FNO"}]}
        if path == "/v1/holdings/user":
            return {"holdings": [{"trading_symbol": "RELIANCE", "quantity": 2, "average_price": 2500}]}
        raise AssertionError(path)

    monkeypatch.setattr(groww, "_get", fake_get)
    result = service.get_positions("groww-live-sdk-readonly", access_token="token")

    assert result["status"] == "ok"
    assert result["connector"] == "groww"
    assert [item["symbol"] for item in result["positions"]] == ["NIFTY25JULFUT", "RELIANCE"]
    assert result["holdings"][0]["position_type"] == "holding"


def test_groww_quote_and_symbol_normalization(monkeypatch) -> None:
    seen = {}

    def fake_get(config, path, *, params=None):
        seen.update({"path": path, "params": params})
        return {"last_price": 150.5, "ohlc": {"open": 149, "high": 151, "low": 148, "close": 149.5}}

    monkeypatch.setattr(groww, "_get", fake_get)
    result = service.get_quote("RELIANCE.NS", "groww-live-sdk-readonly", access_token="token")

    assert seen == {
        "path": "/v1/live-data/quote",
        "params": {"exchange": "NSE", "segment": "CASH", "trading_symbol": "RELIANCE"},
    }
    assert result["quote"]["ltp"] == 150.5


def test_groww_quote_parses_documented_ohlc_string(monkeypatch) -> None:
    monkeypatch.setattr(
        groww,
        "_get",
        lambda config, path, *, params=None: {
            "last_price": 150.5,
            "ohlc": "{open: 149.50,high: 150.50,low: 148.50,close: 149.75}",
        },
    )
    result = service.get_quote("NSE:RELIANCE", "groww-live-sdk-readonly", access_token="token")
    assert result["quote"] == {
        "ltp": 150.5,
        "open": 149.5,
        "high": 150.5,
        "low": 148.5,
        "close": 149.75,
        "volume": None,
        "day_change": None,
        "day_change_percent": None,
    }


class _FakeAngelClient:
    def rmsLimit(self):
        return {"status": True, "data": {"availablecash": "10000", "utiliseddebits": "500"}}

    def position(self):
        return {"status": True, "data": [{"tradingsymbol": "NIFTY25JULFUT", "netqty": "50"}]}

    def allholding(self):
        return {"status": True, "data": [{"tradingsymbol": "SBIN-EQ", "quantity": "3"}]}

    def orderBook(self):
        return {"status": True, "data": [
            {"orderid": "1", "tradingsymbol": "SBIN-EQ", "orderstatus": "open"},
            {"orderid": "2", "tradingsymbol": "SBIN-EQ", "orderstatus": "complete"},
        ]}

    def tradeBook(self):
        return {"status": True, "data": [{"orderid": "2", "tradingsymbol": "SBIN-EQ", "orderstatus": "complete"}]}

    def ltpData(self, exchange, trading_symbol, token):
        assert (exchange, trading_symbol, token) == ("NSE", "SBIN-EQ", "3045")
        return {"status": True, "data": {"ltp": 812.5, "open": 800, "high": 820, "low": 795, "close": 805}}

    def getCandleData(self, params):
        assert params["exchange"] == "NSE" and params["symboltoken"] == "3045"
        return {"status": True, "data": [["2026-07-13T09:15:00+05:30", 800, 810, 798, 807, 10000]]}


@pytest.fixture
def fake_angel(monkeypatch):
    client = _FakeAngelClient()
    monkeypatch.setattr(angel, "_smart_client", lambda config: client)
    return client


def _angel_overrides() -> dict[str, str]:
    return {"api_key": "key", "jwt_token": "jwt"}


def test_angelone_read_paths_map_sdk_payloads(fake_angel) -> None:
    account = service.get_account("angelone-live-sdk-readonly", **_angel_overrides())
    positions = service.get_positions("angelone-live-sdk-readonly", **_angel_overrides())
    orders = service.get_open_orders("angelone-live-sdk-readonly", include_executions=True, **_angel_overrides())

    assert account["account"]["available_cash"] == "10000"
    assert [item["symbol"] for item in positions["positions"]] == ["NIFTY25JULFUT", "SBIN-EQ"]
    assert [item["order_id"] for item in orders["open_orders"]] == ["1"]
    assert [item["order_id"] for item in orders["executions"]] == ["2"]


def test_angelone_quote_and_history_accept_explicit_token(fake_angel) -> None:
    quote = service.get_quote("NSE:3045:SBIN-EQ", "angelone-live-sdk-readonly", **_angel_overrides())
    history = service.get_history(
        "NSE:3045:SBIN-EQ", "angelone-live-sdk-readonly", period="1m", limit=1, **_angel_overrides()
    )
    assert quote["quote"]["ltp"] == 812.5
    assert history["bars"][0]["close"] == 807


def test_angelone_quote_without_token_fails_cleanly() -> None:
    result = angel.get_quote("SBIN-EQ", config=angel.AngelOneConfig(api_key="key", jwt_token="jwt"))
    assert result["status"] == "error"
    assert "symbol token" in result["error"]


def test_angelone_strips_optional_bearer_prefix() -> None:
    config = angel.AngelOneConfig.from_mapping({"api_key": "key", "jwt_token": "Bearer jwt-token"})
    assert config.jwt_token == "jwt-token"


@pytest.mark.parametrize(
    "module,config",
    [
        (groww, groww.GrowwConfig(access_token="token")),
        (angel, angel.AngelOneConfig(api_key="key", jwt_token="jwt")),
    ],
)
def test_order_methods_are_hard_disabled(module, config) -> None:
    placed = module.place_order(config, symbol="SBIN", side="buy", quantity=1)
    cancelled = module.cancel_order(config, "order-1", symbol="SBIN")
    assert placed["status"] == "error" and "read-only" in placed["error"]
    assert cancelled["status"] == "error" and "read-only" in cancelled["error"]


def test_service_refuses_orders_for_readonly_profiles() -> None:
    for profile_id in ("groww-live-sdk-readonly", "angelone-live-sdk-readonly"):
        placed = service.place_order("SBIN", profile_id, side="buy", quantity=1)
        cancelled = service.cancel_order("order-1", profile_id, symbol="SBIN")
        assert placed["status"] == "error"
        assert cancelled["status"] == "error"
        assert "does not support orders.place" in placed["error"]
