"""Built-in read-only Angel One SmartAPI connector profiles."""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

ANGELONE_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="angelone-live-sdk-readonly",
        connector="angelone",
        label="Angel One Live · SmartAPI Read-Only (India)",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes=(
            "Reads an Angel One account, holdings, positions, orders, quotes, "
            "and historical candles through SmartAPI. Real order placement is disabled."
        ),
    ),
)

