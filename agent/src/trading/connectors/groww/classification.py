"""Read/write classification for Groww Trading API operations."""

from __future__ import annotations

from src.live.classification import ToolClass

GROWW_TOOL_CLASS: dict[str, ToolClass] = {
    "get_user_profile": ToolClass.READ,
    "get_available_margin_details": ToolClass.READ,
    "get_holdings_for_user": ToolClass.READ,
    "get_positions_for_user": ToolClass.READ,
    "get_order_list": ToolClass.READ,
    "get_quote": ToolClass.READ,
    "get_historical_candles": ToolClass.READ,
    "place_order": ToolClass.WRITE,
    "modify_order": ToolClass.WRITE,
    "cancel_order": ToolClass.WRITE,
}

