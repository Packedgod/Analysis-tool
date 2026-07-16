"""Lazy singleton accessor for EnvConfig.

Use :func:`get_env_config` to get the cached config instance.  The first call
creates an :class:`~src.config.env_schema.EnvConfig` (which reads
``os.environ``) and caches it; subsequent calls return the same object.

Call :func:`reset_env_config` after modifying ``os.environ`` at runtime
(e.g. in the Settings API) so the next :func:`get_env_config` call picks up
the new values.

Thread-safety is guaranteed by a module-level :class:`threading.Lock` —
swarm workers and the agent loop both run in threads and may call
:func:`get_env_config` concurrently.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config.env_schema import EnvConfig

__all__ = [
    "get_env_config",
    "reset_env_config",
    "_parse_bool",
    "get_env_or",
    "brokerage_enabled",
]

# ---------------------------------------------------------------------------
# Module-level singleton state
# ---------------------------------------------------------------------------

_instance: EnvConfig | None = None
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Truthy / falsy string sets for the unified boolean parser
# ---------------------------------------------------------------------------

_TRUTHY: frozenset[str] = frozenset({"1", "true", "yes", "on"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_env_config() -> EnvConfig:
    """Return the cached :class:`EnvConfig` singleton, creating it on first access.

    Thread-safe: acquires a lock before checking / creating the instance so
    concurrent callers (swarm workers, agent loop) never see a half-built
    config or create duplicate instances.

    Returns:
        The shared :class:`EnvConfig` instance.
    """
    global _instance  # noqa: PLW0603
    if _instance is not None:
        return _instance
    with _lock:
        # Double-checked locking: another thread may have created the
        # instance while we were waiting for the lock.
        if _instance is not None:
            return _instance
        # Import here to avoid a circular import at module-load time and
        # to keep the heavy Pydantic model out of the import path for
        # callers that only need ``_parse_bool`` or ``get_env_or``.
        from src.config.env_schema import EnvConfig as _EnvConfig

        _instance = _EnvConfig()
    return _instance


def reset_env_config() -> None:
    """Clear the cached :class:`EnvConfig` singleton.

    Acquires the same lock used by :func:`get_env_config` so the reset is
    atomic with respect to concurrent readers.  After this call the next
    :func:`get_env_config` invocation will create a fresh instance that
    reflects any ``os.environ`` mutations made since the previous access.

    Typical caller: ``settings_routes.py`` after writing new values to
    ``agent/.env`` and patching ``os.environ``.
    """
    global _instance  # noqa: PLW0603
    with _lock:
        _instance = None


def _parse_bool(value: str | None) -> bool:
    """Parse a string (or ``None``) into a boolean.

    Truthy values (case-insensitive): ``"1"``, ``"true"``, ``"yes"``, ``"on"``.
    Everything else — including ``None``, ``""``, ``"0"``, ``"false"``,
    ``"no"``, ``"off"`` — returns ``False``.

    This is the single source of truth for boolean env-var parsing across the
    codebase, replacing 6+ duplicated inline patterns.

    Args:
        value: The raw string value (typically from ``os.getenv``) or ``None``.

    Returns:
        ``True`` when *value* is a recognised truthy string; ``False`` otherwise.
    """
    if value is None:
        return False
    return value.strip().lower() in _TRUTHY


def brokerage_enabled() -> bool:
    """Return whether the live-brokerage subsystem is enabled.

    Single source of truth for the ``VIBE_TRADING_ENABLE_BROKERAGE`` master
    switch (default OFF). Every live-trading surface — the ``/live`` + ``/mandate``
    HTTP routes, the ``trading_*`` / ``propose_mandate_profiles`` agent tools, and
    the frontend connector panels — consults this so the whole capability flips
    on or off from one flag. When OFF the tool ships as a research-only toolkit
    that sources market data purely from verified public feeds.
    """
    # Product boundary: this fork is permanently analysis-only.  Retained
    # simulation modules may never expose accounts, brokers, mandates or orders,
    # even if a copied environment file contains the old feature flag.
    return False


def get_env_or(primary: str, fallback: str, default: str = "") -> str:
    """Read an env var with a backward-compatible alias fallback.

    Several env vars were renamed during the centralization effort (e.g.
    ``VIBE_TRADING_API_KEY`` → ``API_AUTH_KEY``).  This helper reads the
    *primary* (new) name first, falls back to the *fallback* (old) name,
    and finally returns *default* when neither is set.

    Args:
        primary: The preferred (new) environment variable name.
        fallback: The legacy alias to try when *primary* is unset or empty.
        default: Value returned when neither variable is set.

    Returns:
        The first non-empty value found, or *default*.
    """
    value = os.getenv(primary)
    if value:
        return value
    value = os.getenv(fallback)
    if value:
        return value
    return default
