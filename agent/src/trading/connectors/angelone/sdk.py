"""Read-only Angel One connector via the official SmartAPI Python SDK.

The connector can use a pre-generated JWT session or create a daily session
from client code, PIN, and TOTP secret. Session material is kept in memory and
all configuration/status payloads redact credentials. Every order mutation is
hard-disabled.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.config.paths import get_runtime_root

CONFIG_FILENAME = "angelone.json"
PAPER_GUARD = "read_only_no_sandbox"
SMARTAPI_HOST = "https://apiconnect.angelone.in"


class AngelOneDependencyError(RuntimeError):
    """Raised when the optional SmartAPI packages are unavailable."""


class AngelOneConfigError(RuntimeError):
    """Raised when Angel One connector settings are missing or invalid."""


class AngelOneAPIError(RuntimeError):
    """Raised when SmartAPI returns an authentication or API error."""


@dataclass(frozen=True)
class AngelOneConfig:
    api_key: str = ""
    client_code: str = ""
    pin: str = ""
    totp_secret: str = ""
    jwt_token: str = ""
    refresh_token: str = ""
    feed_token: str = ""
    profile: str = "live-readonly"
    timeout: float = 15.0
    instrument_tokens: dict[str, Any] = field(default_factory=dict)
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "AngelOneConfig":
        payload = dict(data or {})
        profile = str(payload.get("profile") or "live-readonly").strip().lower()
        if profile not in {"live-readonly", "live"}:
            raise AngelOneConfigError("profile must be 'live-readonly' or 'live'")
        tokens = payload.get("instrument_tokens") or {}
        if not isinstance(tokens, Mapping):
            raise AngelOneConfigError("instrument_tokens must be a JSON object")
        return cls(
            api_key=str(payload.get("api_key") or "").strip(),
            client_code=str(payload.get("client_code") or "").strip(),
            pin=str(payload.get("pin") or "").strip(),
            totp_secret=str(payload.get("totp_secret") or "").strip().replace(" ", ""),
            jwt_token=_strip_bearer(payload.get("jwt_token")),
            refresh_token=str(payload.get("refresh_token") or "").strip(),
            feed_token=str(payload.get("feed_token") or "").strip(),
            profile=profile,
            timeout=float(payload.get("timeout") or 15.0),
            instrument_tokens={str(key).upper(): value for key, value in tokens.items()},
            readonly=True,
        )


_OVERRIDE_KEYS = {
    "api_key", "client_code", "pin", "totp_secret", "jwt_token",
    "refresh_token", "feed_token", "profile", "instrument_tokens",
}
_CLIENT_CACHE: dict[tuple[str, str, str], Any] = {}


def config_path() -> Path:
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> AngelOneConfig:
    path = config_path()
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise AngelOneConfigError(f"invalid Angel One config at {path}: {exc}") from exc
    env_defaults = {
        "api_key": os.getenv("ANGELONE_API_KEY", ""),
        "client_code": os.getenv("ANGELONE_CLIENT_CODE", ""),
        "pin": os.getenv("ANGELONE_PIN", ""),
        "totp_secret": os.getenv("ANGELONE_TOTP_SECRET", ""),
        "jwt_token": os.getenv("ANGELONE_JWT_TOKEN", ""),
        "refresh_token": os.getenv("ANGELONE_REFRESH_TOKEN", ""),
        "feed_token": os.getenv("ANGELONE_FEED_TOKEN", ""),
    }
    for key, value in env_defaults.items():
        if value and not payload.get(key):
            payload[key] = value
    return AngelOneConfig.from_mapping(payload)


def save_config(config: AngelOneConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def build_config(
    profile_config: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> AngelOneConfig:
    base = asdict(load_config())
    base.update({key: value for key, value in dict(profile_config or {}).items() if value is not None})
    base.update({
        key: value for key, value in dict(overrides or {}).items()
        if key in _OVERRIDE_KEYS and value not in (None, "")
    })
    return AngelOneConfig.from_mapping(base)


def smartapi_available() -> bool:
    try:
        _require_smartapi()
        return True
    except AngelOneDependencyError:
        return False


def check_status(config: AngelOneConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {"package": "smartapi-python", "installed": smartapi_available()},
        "paper_guard": PAPER_GUARD,
        "host": SMARTAPI_HOST,
    }
    missing = _missing_fields(cfg)
    if missing:
        report["status"] = "error"
        report["error"] = f"Angel One connector not configured: missing {', '.join(missing)}."
        return report
    if not report["sdk"]["installed"]:
        report["status"] = "error"
        report["error"] = "Optional dependency missing: install with `pip install smartapi-python pyotp`."
        return report
    try:
        snapshot = get_account_snapshot(cfg)
    except (AngelOneConfigError, AngelOneDependencyError, AngelOneAPIError) as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report
    except Exception as exc:  # noqa: BLE001 - return a clean health payload
        report["status"] = "error"
        report["error"] = f"Angel One connector check failed: {exc}"
        return report
    report["account"] = {
        "client_code": _redact_id(cfg.client_code),
        "available_cash": snapshot.get("account", {}).get("available_cash"),
    }
    return report


def get_account_snapshot(config: AngelOneConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    client = _smart_client(cfg)
    limits = _response_data(_call(client, ("rmsLimit",)))
    limit_map = dict(limits) if isinstance(limits, Mapping) else {"raw": limits}
    profile: Any = {}
    if cfg.refresh_token:
        try:
            profile = _response_data(_call(client, ("getProfile",), cfg.refresh_token))
        except Exception:  # profile is optional; the funds endpoint already validates auth
            profile = {}
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "account": {
            "currency": "INR",
            "available_cash": limit_map.get("availablecash") or limit_map.get("availableCash"),
            "available_intraday_payin": limit_map.get("availableintradaypayin"),
            "utilized_amount": limit_map.get("utiliseddebits") or limit_map.get("utilizedAmount"),
            "collateral": limit_map.get("collateral"),
            "m2m_unrealized": limit_map.get("m2munrealized"),
        },
        "limits": limit_map,
        "user": dict(profile) if isinstance(profile, Mapping) else profile,
    }


def get_positions(config: AngelOneConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    client = _smart_client(cfg)
    position_data = _response_data(_call(client, ("position",)))
    try:
        holding_data = _response_data(_call(client, ("allholding", "holding")))
    except AngelOneAPIError:
        holding_data = []
    positions = [_position_to_dict(item, holding=False) for item in _extract_items(position_data)]
    holdings = [_position_to_dict(item, holding=True) for item in _extract_items(holding_data)]
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "positions": positions + holdings,
        "intraday_positions": positions,
        "holdings": holdings,
    }


def get_open_orders(
    config: AngelOneConfig | None = None,
    *,
    include_executions: bool = False,
) -> dict[str, Any]:
    cfg = config or load_config()
    client = _smart_client(cfg)
    order_data = _response_data(_call(client, ("orderBook",)))
    rows = [_order_to_dict(item) for item in _extract_items(order_data)]
    terminal = {"COMPLETE", "COMPLETED", "EXECUTED", "CANCELLED", "REJECTED"}
    result: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "open_orders": [row for row in rows if str(row.get("status") or "").upper() not in terminal],
    }
    if include_executions:
        try:
            trades = _response_data(_call(client, ("tradeBook",)))
            result["executions"] = [_order_to_dict(item) for item in _extract_items(trades)]
        except AngelOneAPIError:
            result["executions"] = [row for row in rows if str(row.get("status") or "").upper() in terminal]
    return result


def get_quote(symbol: str, *, config: AngelOneConfig | None = None, **_: Any) -> dict[str, Any]:
    cfg = config or load_config()
    instrument = _instrument_parts(symbol, cfg)
    if instrument is None:
        return _instrument_error(symbol, cfg)
    exchange, token, trading_symbol = instrument
    client = _smart_client(cfg)
    data = _response_data(_call(client, ("ltpData",), exchange, trading_symbol, token))
    quote = dict(data) if isinstance(data, Mapping) else {"raw": data}
    return {
        "status": "ok",
        "symbol": trading_symbol,
        "symbol_token": token,
        "exchange": exchange,
        "quote": {
            "ltp": quote.get("ltp"),
            "open": quote.get("open"),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "close": quote.get("close"),
        },
        "raw": quote,
    }


_INTERVALS = {
    "1m": ("ONE_MINUTE", 1), "3m": ("THREE_MINUTE", 3),
    "5m": ("FIVE_MINUTE", 5), "10m": ("TEN_MINUTE", 10),
    "15m": ("FIFTEEN_MINUTE", 15), "30m": ("THIRTY_MINUTE", 30),
    "1h": ("ONE_HOUR", 60), "1d": ("ONE_DAY", 1440),
}


def get_historical_bars(
    symbol: str,
    *,
    config: AngelOneConfig | None = None,
    period: str = "1d",
    limit: int = 90,
    **_: Any,
) -> dict[str, Any]:
    cfg = config or load_config()
    if period not in _INTERVALS:
        return {"status": "error", "symbol": symbol, "error": f"unsupported period: {period}"}
    instrument = _instrument_parts(symbol, cfg)
    if instrument is None:
        return _instrument_error(symbol, cfg)
    exchange, token, trading_symbol = instrument
    interval, minutes = _INTERVALS[period]
    end = datetime.now(ZoneInfo("Asia/Kolkata"))
    start = end - timedelta(minutes=max(int(limit), 1) * minutes * 2)
    params = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": interval,
        "fromdate": start.strftime("%Y-%m-%d %H:%M"),
        "todate": end.strftime("%Y-%m-%d %H:%M"),
    }
    client = _smart_client(cfg)
    candles = _response_data(_call(client, ("getCandleData",), params))
    bars = [
        {"time": row[0], "open": row[1], "high": row[2], "low": row[3], "close": row[4], "volume": row[5]}
        for row in (candles or []) if isinstance(row, (list, tuple)) and len(row) >= 6
    ]
    return {
        "status": "ok",
        "symbol": trading_symbol,
        "symbol_token": token,
        "exchange": exchange,
        "period": period,
        "bars": bars[-max(int(limit), 1):],
    }


_ORDER_DISABLED = (
    "Angel One connector is read-only: real order placement and cancellation are disabled."
)


def place_order(config: AngelOneConfig | None = None, *, symbol: str, side: str, **kwargs: Any) -> dict[str, Any]:
    cfg = config or load_config()
    return _order_refused(cfg, symbol=symbol, side=side, **kwargs)


def cancel_order(
    config: AngelOneConfig | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    return _order_refused(cfg, order_id=order_id, symbol=symbol)


def _order_refused(config: AngelOneConfig, **extra: Any) -> dict[str, Any]:
    result = {"status": "error", "error": _ORDER_DISABLED, "profile": config.profile, "paper_guard": PAPER_GUARD}
    result.update({key: value for key, value in extra.items() if value is not None})
    return result


def _require_smartapi() -> tuple[Any, Any]:
    try:
        from SmartApi import SmartConnect  # type: ignore
        import pyotp  # type: ignore
    except ModuleNotFoundError as exc:
        raise AngelOneDependencyError(
            "smartapi-python/pyotp are not installed; run `pip install smartapi-python pyotp`."
        ) from exc
    return SmartConnect, pyotp


def _smart_client(config: AngelOneConfig) -> Any:
    missing = _missing_fields(config)
    if missing:
        raise AngelOneConfigError(f"Angel One connector not configured: missing {', '.join(missing)}.")
    cache_key = (config.api_key, config.client_code, config.jwt_token)
    if cache_key in _CLIENT_CACHE:
        return _CLIENT_CACHE[cache_key]
    SmartConnect, pyotp = _require_smartapi()
    client = SmartConnect(config.api_key, timeout=config.timeout)
    if config.jwt_token:
        _set_if_supported(client, "setAccessToken", config.jwt_token)
        _set_if_supported(client, "setRefreshToken", config.refresh_token)
        _set_if_supported(client, "setFeedToken", config.feed_token)
    else:
        try:
            totp = pyotp.TOTP(config.totp_secret).now()
            session = client.generateSession(config.client_code, config.pin, totp)
        except Exception as exc:
            raise AngelOneAPIError(f"Angel One login failed: {exc}") from exc
        _response_data(session)
    _CLIENT_CACHE[cache_key] = client
    return client


def _set_if_supported(client: Any, method: str, value: str) -> None:
    if value and callable(getattr(client, method, None)):
        getattr(client, method)(value)


def _call(client: Any, names: tuple[str, ...], *args: Any) -> Any:
    for name in names:
        method = getattr(client, name, None)
        if callable(method):
            try:
                return method(*args)
            except Exception as exc:
                raise AngelOneAPIError(f"Angel One SmartAPI {name} failed: {exc}") from exc
    raise AngelOneAPIError(f"Angel One SmartAPI method unavailable: {'/'.join(names)}")


def _response_data(response: Any) -> Any:
    if isinstance(response, Mapping):
        if response.get("status") is False:
            message = response.get("message") or response.get("errorcode") or "request failed"
            raise AngelOneAPIError(f"Angel One API error: {message}")
        if "data" in response:
            return response.get("data")
    return response


def _missing_fields(config: AngelOneConfig) -> list[str]:
    missing: list[str] = []
    if not config.api_key:
        missing.append("api_key")
    if not config.jwt_token:
        if not config.client_code:
            missing.append("client_code")
        if not config.pin:
            missing.append("pin")
        if not config.totp_secret:
            missing.append("totp_secret")
    return missing


def _public_config(config: AngelOneConfig) -> dict[str, Any]:
    data = asdict(config)
    if data.get("api_key"):
        data["api_key"] = data["api_key"][:4] + "***"
    if data.get("client_code"):
        data["client_code"] = _redact_id(data["client_code"])
    for key in ("pin", "totp_secret", "jwt_token", "refresh_token", "feed_token"):
        if data.get(key):
            data[key] = "***redacted***"
    return data


def _redact_id(value: str) -> str:
    text = str(value or "")
    return ("***" + text[-3:]) if text else ""


def _strip_bearer(value: Any) -> str:
    token = str(value or "").strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    return token


def _instrument_parts(symbol: str, config: AngelOneConfig) -> tuple[str, str, str] | None:
    key = str(symbol or "").strip().upper()
    entry = config.instrument_tokens.get(key)
    if isinstance(entry, Mapping):
        token = str(entry.get("token") or entry.get("symbol_token") or "").strip()
        exchange = str(entry.get("exchange") or "NSE").strip().upper()
        trading_symbol = str(entry.get("trading_symbol") or key).strip().upper()
        return (exchange, token, trading_symbol) if token else None
    if isinstance(entry, str) and entry.strip():
        return "NSE", entry.strip(), key
    if key.count(":") >= 2:
        exchange, token, trading_symbol = key.split(":", 2)
        return exchange, token, trading_symbol
    if key.count("|") >= 2:
        trading_symbol, token, exchange = key.split("|", 2)
        return exchange, token, trading_symbol
    return None


def _instrument_error(symbol: str, config: AngelOneConfig) -> dict[str, Any]:
    return {
        "status": "error",
        "profile": config.profile,
        "symbol": str(symbol or "").strip().upper(),
        "error": (
            "Angel One requires an exchange symbol token. Add it to instrument_tokens "
            "in angelone.json or use EXCHANGE:TOKEN:TRADING_SYMBOL (example NSE:3045:SBIN-EQ)."
        ),
    }


def _extract_items(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        for key in ("data", "positions", "holdings", "totalholding", "orderbook"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, Mapping)]
    return []


def _position_to_dict(item: Mapping[str, Any], *, holding: bool) -> dict[str, Any]:
    return {
        "symbol": item.get("tradingsymbol") or item.get("tradingSymbol") or "",
        "symbol_token": item.get("symboltoken") or item.get("symbolToken"),
        "exchange": item.get("exchange"),
        "product": item.get("producttype") or item.get("productType"),
        "quantity": item.get("netqty") or item.get("quantity") or item.get("t1quantity") or 0,
        "average_price": item.get("avgnetprice") or item.get("averageprice") or item.get("averagePrice"),
        "current_price": item.get("ltp") or item.get("closingprice"),
        "realized_pnl": item.get("realised") or item.get("realized"),
        "unrealized_pnl": item.get("unrealised") or item.get("unrealized"),
        "position_type": "holding" if holding else "position",
        "raw": dict(item),
    }


def _order_to_dict(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "order_id": item.get("orderid") or item.get("orderId") or "",
        "symbol": item.get("tradingsymbol") or item.get("tradingSymbol") or "",
        "symbol_token": item.get("symboltoken") or item.get("symbolToken"),
        "side": str(item.get("transactiontype") or item.get("transactionType") or "").lower(),
        "order_type": str(item.get("ordertype") or item.get("orderType") or "").lower(),
        "quantity": item.get("quantity") or 0,
        "filled_qty": item.get("filledshares") or item.get("filledShares") or 0,
        "price": item.get("price"),
        "status": item.get("orderstatus") or item.get("status") or "",
        "exchange": item.get("exchange"),
        "product": item.get("producttype") or item.get("productType"),
    }
