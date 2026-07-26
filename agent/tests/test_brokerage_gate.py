"""Brokerage removal guarantee.

This is a permanently analysis-only fork: ``brokerage_enabled()`` is hard-locked
to ``False`` and the brokerage option has been removed. These tests pin that the
live-trading surface stays absent so it can never be reintroduced by accident:

- ``brokerage_enabled()`` is off.
- The ``trading_*`` / ``propose_mandate_profiles`` agent tools are excluded from
  the tool registry.
- ``GET /api`` advertises ``capabilities.brokerage`` as false so the frontend
  hides any live-trading UI.
- ``register_live_routes`` mounts none of the ``/live/*`` or ``/mandate/*``
  endpoints.
"""

from __future__ import annotations

import api_server  # noqa: F401 — ensures api_server is in sys.modules for route helpers
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config.accessor import brokerage_enabled, reset_env_config

_BROKER_TOOLS = {
    "trading_connections",
    "trading_select_connection",
    "trading_check",
    "trading_account",
    "trading_positions",
    "trading_orders",
    "trading_quote",
    "trading_history",
    "trading_place_order",
    "trading_cancel_order",
    "propose_mandate_profiles",
}


def _enable(monkeypatch, on: bool) -> None:
    if on:
        monkeypatch.setenv("VIBE_TRADING_ENABLE_BROKERAGE", "1")
    else:
        monkeypatch.delenv("VIBE_TRADING_ENABLE_BROKERAGE", raising=False)
    reset_env_config()


def test_disabled_by_default(monkeypatch) -> None:
    _enable(monkeypatch, False)
    assert brokerage_enabled() is False


def test_broker_tools_absent_when_disabled(monkeypatch) -> None:
    from src.tools import build_registry

    _enable(monkeypatch, False)
    registry = build_registry()
    present = _BROKER_TOOLS & set(registry.tool_names)
    assert present == set(), f"broker tools leaked into research-only registry: {present}"


def _api_client() -> TestClient:
    from src.api.system_routes import register_system_routes

    app = FastAPI()
    register_system_routes(app)
    return TestClient(app)


def test_api_capability_false_when_disabled(monkeypatch) -> None:
    _enable(monkeypatch, False)
    resp = _api_client().get("/api")
    assert resp.status_code == 200
    assert resp.json()["capabilities"]["brokerage"] is False


def test_register_live_routes_mounts_nothing_when_disabled(monkeypatch) -> None:
    from src.api.live_routes import register_live_routes

    _enable(monkeypatch, False)
    app = FastAPI()
    register_live_routes(app)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/live/status" not in paths
    assert "/mandate/commit" not in paths
