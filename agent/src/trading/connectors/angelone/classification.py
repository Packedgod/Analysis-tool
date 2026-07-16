"""Read/write classification for Angel One SmartAPI operations."""

from __future__ import annotations

from src.live.classification import ToolClass

ANGELONE_TOOL_CLASS: dict[str, ToolClass] = {
    "getProfile": ToolClass.READ,
    "rmsLimit": ToolClass.READ,
    "holding": ToolClass.READ,
    "allholding": ToolClass.READ,
    "position": ToolClass.READ,
    "orderBook": ToolClass.READ,
    "tradeBook": ToolClass.READ,
    "getMarketData": ToolClass.READ,
    "ltpData": ToolClass.READ,
    "getCandleData": ToolClass.READ,
    "placeOrder": ToolClass.WRITE,
    "modifyOrder": ToolClass.WRITE,
    "cancelOrder": ToolClass.WRITE,
    "convertPosition": ToolClass.WRITE,
}

