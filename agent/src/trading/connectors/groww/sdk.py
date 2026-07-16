"""Read-only Groww connector via the official Trading REST API.

Authentication supports either a short-lived access token or the official API
key + secret approval flow. Generated access tokens are cached only in process;
credentials are never returned in connector payloads. All order mutations are
hard-disabled because Groww exposes no paper/sandbox discriminator.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests

from src.config.paths import get_runtime_root

CONFIG_FILENAME = "groww.json"
DEFAULT_BASE_URL = "https://api.groww.in"
PAPER_GUARD = "read_only_no_sandbox"


class GrowwConfigError(RuntimeError):
    """Raised when Groww connector settings are missing or invalid."""


class GrowwAPIError(RuntimeError):
    """Raised for Groww authentication, HTTP, network, or response errors."""


@dataclass(frozen=True)
class GrowwConfig:
    access_token: str = ""
    api_key: str = ""
    api_secret: str = ""
    profile: str = "live-readonly"
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 15.0
    default_exchange: str = "NSE"
    default_segment: str = "CASH"
    readonly: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "GrowwConfig":
        payload = dict(data or {})
        profile = str(payload.get("profile") or "live-readonly").strip().lower()
        if profile not in {"live-readonly", "live"}:
            raise GrowwConfigError("profile must be 'live-readonly' or 'live'")
        base_url = str(payload.get("base_url") or DEFAULT_BASE_URL).strip().rstrip("/")
        if not base_url.startswith("https://"):
            raise GrowwConfigError("base_url must use https://")
        exchange = str(payload.get("default_exchange") or "NSE").strip().upper()
        if exchange not in {"NSE", "BSE", "MCX"}:
            raise GrowwConfigError("default_exchange must be NSE, BSE, or MCX")
        segment = str(payload.get("default_segment") or "CASH").strip().upper()
        if segment not in {"CASH", "FNO", "COMMODITY"}:
            raise GrowwConfigError("default_segment must be CASH, FNO, or COMMODITY")
        return cls(
            access_token=str(payload.get("access_token") or "").strip(),
            api_key=str(payload.get("api_key") or "").strip(),
            api_secret=str(payload.get("api_secret") or "").strip(),
            profile=profile,
            base_url=base_url,
            timeout=float(payload.get("timeout") or 15.0),
            default_exchange=exchange,
            default_segment=segment,
            readonly=True,
        )

    def with_overrides(self, **overrides: Any) -> "GrowwConfig":
        payload = asdict(self)
        payload.update({key: value for key, value in overrides.items() if value is not None})
        return GrowwConfig.from_mapping(payload)


_OVERRIDE_KEYS = {
    "access_token", "api_key", "api_secret", "profile", "base_url",
    "default_exchange", "default_segment",
}
_TOKEN_CACHE: dict[tuple[str, str], str] = {}


def config_path() -> Path:
    return get_runtime_root() / CONFIG_FILENAME


def load_config() -> GrowwConfig:
    path = config_path()
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise GrowwConfigError(f"invalid Groww config at {path}: {exc}") from exc
    env_defaults = {
        "access_token": os.getenv("GROWW_ACCESS_TOKEN", ""),
        "api_key": os.getenv("GROWW_API_KEY", ""),
        "api_secret": os.getenv("GROWW_API_SECRET", ""),
    }
    for key, value in env_defaults.items():
        if value and not payload.get(key):
            payload[key] = value
    return GrowwConfig.from_mapping(payload)


def save_config(config: GrowwConfig) -> Path:
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
) -> GrowwConfig:
    base = asdict(load_config())
    base.update({key: value for key, value in dict(profile_config or {}).items() if value is not None})
    clean = {
        key: value for key, value in dict(overrides or {}).items()
        if key in _OVERRIDE_KEYS and value not in (None, "")
    }
    base.update(clean)
    return GrowwConfig.from_mapping(base)


def check_status(config: GrowwConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {"package": "requests", "installed": True},
        "paper_guard": PAPER_GUARD,
        "base_url": cfg.base_url,
    }
    missing = _missing_fields(cfg)
    if missing:
        report["status"] = "error"
        report["error"] = f"Groww connector not configured: missing {', '.join(missing)}."
        return report
    try:
        profile = _get(cfg, "/v1/user/detail")
    except (GrowwConfigError, GrowwAPIError) as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return report
    report["account"] = {
        "ucc": profile.get("ucc") if isinstance(profile, Mapping) else None,
        "active_segments": profile.get("active_segments", []) if isinstance(profile, Mapping) else [],
    }
    return report


def get_account_snapshot(config: GrowwConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    margin = _get(cfg, "/v1/margins/detail/user")
    profile = _get(cfg, "/v1/user/detail")
    margin_map = dict(margin) if isinstance(margin, Mapping) else {}
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "account": {
            "currency": "INR",
            "available_cash": margin_map.get("clear_cash"),
            "used_margin": margin_map.get("net_margin_used"),
            "collateral_available": margin_map.get("collateral_available"),
            "collateral_used": margin_map.get("collateral_used"),
            "brokerage_and_charges": margin_map.get("brokerage_and_charges"),
        },
        "user": dict(profile) if isinstance(profile, Mapping) else profile,
        "margin": margin_map,
    }


def get_positions(config: GrowwConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    positions_payload = _get(
        cfg,
        "/v1/positions/user",
        params={"segment": cfg.default_segment},
    )
    holdings_payload = _get(cfg, "/v1/holdings/user")
    positions = [_position_to_dict(item, holding=False) for item in _extract_items(positions_payload)]
    holdings = [_position_to_dict(item, holding=True) for item in _extract_items(holdings_payload)]
    return {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "positions": positions + holdings,
        "intraday_positions": positions,
        "holdings": holdings,
    }


def get_open_orders(
    config: GrowwConfig | None = None,
    *,
    include_executions: bool = False,
) -> dict[str, Any]:
    cfg = config or load_config()
    payload = _get(
        cfg,
        "/v1/order/list",
        params={"segment": cfg.default_segment, "page": 0, "page_size": 100},
    )
    rows = [_order_to_dict(item) for item in _extract_items(payload)]
    terminal = {"COMPLETED", "EXECUTED", "FILLED", "CANCELLED", "REJECTED"}
    result: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "paper_guard": PAPER_GUARD,
        "open_orders": [row for row in rows if str(row.get("status") or "").upper() not in terminal],
    }
    if include_executions:
        result["executions"] = [row for row in rows if str(row.get("status") or "").upper() in terminal]
    return result


def get_quote(symbol: str, *, config: GrowwConfig | None = None, **_: Any) -> dict[str, Any]:
    cfg = config or load_config()
    exchange, segment, trading_symbol, _groww_symbol = _symbol_parts(symbol, cfg)
    quote = _get(
        cfg,
        "/v1/live-data/quote",
        params={"exchange": exchange, "segment": segment, "trading_symbol": trading_symbol},
    )
    data = dict(quote) if isinstance(quote, Mapping) else {"raw": quote}
    return {
        "status": "ok",
        "symbol": trading_symbol,
        "exchange": exchange,
        "segment": segment,
        "quote": {
            "ltp": data.get("last_price"),
            "open": _nested(data, "ohlc", "open"),
            "high": _nested(data, "ohlc", "high"),
            "low": _nested(data, "ohlc", "low"),
            "close": _nested(data, "ohlc", "close"),
            "volume": data.get("volume"),
            "day_change": data.get("day_change"),
            "day_change_percent": data.get("day_change_perc"),
        },
        "raw": data,
    }


_INTERVALS = {
    "1m": ("1minute", 1), "2m": ("2minute", 2), "3m": ("3minute", 3),
    "5m": ("5minute", 5), "10m": ("10minute", 10), "15m": ("15minute", 15),
    "30m": ("30minute", 30), "1h": ("1hour", 60), "4h": ("4hour", 240),
    "1d": ("1day", 1440), "1w": ("1week", 10080), "1M": ("1month", 43200),
}


def get_historical_bars(
    symbol: str,
    *,
    config: GrowwConfig | None = None,
    period: str = "1d",
    limit: int = 90,
    **_: Any,
) -> dict[str, Any]:
    cfg = config or load_config()
    if period not in _INTERVALS:
        return {"status": "error", "symbol": symbol, "error": f"unsupported period: {period}"}
    exchange, segment, trading_symbol, groww_symbol = _symbol_parts(symbol, cfg)
    interval, minutes = _INTERVALS[period]
    end = datetime.now(ZoneInfo("Asia/Kolkata"))
    span_minutes = min(max(int(limit), 1) * minutes * 2, 180 * 24 * 60)
    start = end - timedelta(minutes=span_minutes)
    payload = _get(
        cfg,
        "/v1/historical/candles",
        params={
            "exchange": exchange,
            "segment": segment,
            "groww_symbol": groww_symbol,
            "start_time": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": end.strftime("%Y-%m-%d %H:%M:%S"),
            "candle_interval": interval,
        },
    )
    candles = payload.get("candles", []) if isinstance(payload, Mapping) else []
    bars = [
        {"time": row[0], "open": row[1], "high": row[2], "low": row[3], "close": row[4], "volume": row[5]}
        for row in candles if isinstance(row, (list, tuple)) and len(row) >= 6
    ]
    return {
        "status": "ok",
        "symbol": trading_symbol,
        "groww_symbol": groww_symbol,
        "exchange": exchange,
        "segment": segment,
        "period": period,
        "bars": bars[-max(int(limit), 1):],
    }


_ORDER_DISABLED = (
    "Groww connector is read-only: real order placement and cancellation are disabled."
)


def place_order(config: GrowwConfig | None = None, *, symbol: str, side: str, **kwargs: Any) -> dict[str, Any]:
    cfg = config or load_config()
    return _order_refused(cfg, symbol=symbol, side=side, **kwargs)


def cancel_order(
    config: GrowwConfig | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    return _order_refused(cfg, order_id=order_id, symbol=symbol)


def _order_refused(config: GrowwConfig, **extra: Any) -> dict[str, Any]:
    result = {"status": "error", "error": _ORDER_DISABLED, "profile": config.profile, "paper_guard": PAPER_GUARD}
    result.update({key: value for key, value in extra.items() if value is not None})
    return result


def _get(config: GrowwConfig, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
    return _request(config, "GET", path, params=params)


def _request(
    config: GrowwConfig,
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json_body: Any = None,
) -> Any:
    missing = _missing_fields(config)
    if missing:
        raise GrowwConfigError(f"Groww connector not configured: missing {', '.join(missing)}.")
    token = _access_token(config)
    url = urljoin(f"{config.base_url.rstrip('/')}/", path.lstrip("/"))
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "X-API-VERSION": "1.0",
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    try:
        response = requests.request(
            method.upper(), url, headers=headers, params=dict(params or {}),
            json=json_body, timeout=config.timeout,
        )
    except requests.RequestException as exc:
        raise GrowwAPIError(f"Groww request failed: {exc}") from exc
    if response.status_code in (401, 403):
        raise GrowwAPIError("Groww API authentication failed: refresh the access token or approve the API key.")
    if response.status_code >= 400:
        raise GrowwAPIError(f"Groww API returned HTTP {response.status_code}: {_response_error(response)}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise GrowwAPIError("Groww API returned invalid JSON.") from exc
    if isinstance(payload, Mapping) and str(payload.get("status") or "").upper() == "FAILURE":
        raise GrowwAPIError(f"Groww API error: {_payload_error(payload)}")
    if isinstance(payload, Mapping) and "payload" in payload:
        return payload.get("payload")
    return payload


def _access_token(config: GrowwConfig) -> str:
    if config.access_token:
        return config.access_token
    if not config.api_key or not config.api_secret:
        raise GrowwConfigError("Groww connector needs access_token or api_key + api_secret.")
    cache_key = (config.base_url, config.api_key)
    cached = _TOKEN_CACHE.get(cache_key)
    if cached:
        return cached
    timestamp = str(int(time.time()))
    checksum = hashlib.sha256(f"{config.api_secret}{timestamp}".encode("utf-8")).hexdigest()
    url = urljoin(f"{config.base_url.rstrip('/')}/", "/v1/token/api/access".lstrip("/"))
    try:
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
            json={"key_type": "approval", "checksum": checksum, "timestamp": timestamp},
            timeout=config.timeout,
        )
    except requests.RequestException as exc:
        raise GrowwAPIError(f"Groww token request failed: {exc}") from exc
    if response.status_code >= 400:
        raise GrowwAPIError(f"Groww token request failed: {_response_error(response)}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise GrowwAPIError("Groww token endpoint returned invalid JSON.") from exc
    token = str(payload.get("token") or payload.get("access_token") or "") if isinstance(payload, Mapping) else ""
    if not token:
        raise GrowwAPIError(f"Groww token endpoint returned no token: {_payload_error(payload)}")
    _TOKEN_CACHE[cache_key] = token
    return token


def _missing_fields(config: GrowwConfig) -> list[str]:
    if config.access_token or (config.api_key and config.api_secret):
        return []
    return ["access_token or api_key+api_secret"]


def _public_config(config: GrowwConfig) -> dict[str, Any]:
    data = asdict(config)
    if data.get("access_token"):
        data["access_token"] = "***redacted***"
    if data.get("api_key"):
        data["api_key"] = data["api_key"][:4] + "***"
    if data.get("api_secret"):
        data["api_secret"] = "***redacted***"
    return data


def _symbol_parts(symbol: str, config: GrowwConfig) -> tuple[str, str, str, str]:
    token = str(symbol or "").strip().upper()
    if not token:
        raise GrowwConfigError("symbol is required")
    exchange = config.default_exchange
    if ":" in token:
        maybe_exchange, token = token.split(":", 1)
        if maybe_exchange in {"NSE", "BSE", "MCX"}:
            exchange = maybe_exchange
    elif token.startswith(("NSE-", "BSE-", "MCX-")):
        exchange, token = token.split("-", 1)
    elif token.endswith(".NS"):
        exchange, token = "NSE", token[:-3]
    elif token.endswith(".BO"):
        exchange, token = "BSE", token[:-3]
    groww_symbol = f"{exchange}-{token}"
    return exchange, config.default_segment, token, groww_symbol


def _extract_items(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("positions", "holdings", "order_list", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
        if all(isinstance(value, Mapping) for value in payload.values()):
            return [value for value in payload.values() if isinstance(value, Mapping)]
    return []


def _position_to_dict(item: Mapping[str, Any], *, holding: bool) -> dict[str, Any]:
    return {
        "symbol": item.get("trading_symbol") or item.get("symbol") or item.get("groww_symbol") or "",
        "exchange": item.get("exchange"),
        "segment": item.get("segment") or "CASH",
        "product": item.get("product"),
        "quantity": item.get("quantity") or item.get("net_quantity") or item.get("available_quantity") or 0,
        "average_price": item.get("average_price") or item.get("average_buy_price") or item.get("buy_price"),
        "current_price": item.get("ltp") or item.get("last_price"),
        "realized_pnl": item.get("realised_pnl") or item.get("realized_pnl"),
        "unrealized_pnl": item.get("unrealised_pnl") or item.get("unrealized_pnl"),
        "position_type": "holding" if holding else "position",
        "raw": dict(item),
    }


def _order_to_dict(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "order_id": item.get("groww_order_id") or item.get("order_id") or "",
        "symbol": item.get("trading_symbol") or "",
        "side": str(item.get("transaction_type") or "").lower(),
        "order_type": str(item.get("order_type") or "").lower(),
        "quantity": item.get("quantity") or 0,
        "filled_qty": item.get("filled_quantity") or 0,
        "price": item.get("price"),
        "status": item.get("order_status") or item.get("status") or "",
        "exchange": item.get("exchange"),
        "segment": item.get("segment"),
        "product": item.get("product"),
    }


def _nested(data: Mapping[str, Any], key: str, child: str) -> Any:
    value = data.get(key)
    if isinstance(value, Mapping):
        return value.get(child)
    if isinstance(value, str):
        # Groww currently documents OHLC as a compact string such as
        # ``{open: 149.50,high: 150.50,low: 148.50,close: 149.50}``.
        match = re.search(
            rf"(?:^|[,{{])\s*{re.escape(child)}\s*:\s*"
            r"(-?(?:\d+(?:\.\d*)?|\.\d+)|null)",
            value,
            flags=re.IGNORECASE,
        )
        if match:
            return None if match.group(1).lower() == "null" else float(match.group(1))
    return None


def _payload_error(payload: Any) -> str:
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            return str(error.get("message") or error.get("code") or error)
        return str(error or payload.get("message") or payload)
    return str(payload)


def _response_error(response: requests.Response) -> str:
    try:
        return _payload_error(response.json())
    except ValueError:
        return response.text.strip() or response.reason or "request failed"
