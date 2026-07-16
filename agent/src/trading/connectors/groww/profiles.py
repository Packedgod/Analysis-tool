"""Built-in read-only Groww connector profiles."""

from __future__ import annotations

from src.trading.types import READ_CAPABILITIES, TradingProfile

GROWW_PROFILES: tuple[TradingProfile, ...] = (
    TradingProfile(
        id="groww-live-sdk-readonly",
        connector="groww",
        label="Groww Live · Trading API Read-Only (India)",
        environment="live",
        transport="broker_sdk",
        capabilities=READ_CAPABILITIES,
        readonly=True,
        config={"profile": "live-readonly"},
        notes=(
            "Reads a Groww account, holdings, positions, orders, quotes, and "
            "historical candles. Requires an active Groww Trading API "
            "subscription. Real order placement is disabled."
        ),
    ),
)

