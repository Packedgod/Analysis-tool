"""Live startup checks for the services required by the local application.

The normal test suite verifies behavior with deterministic provider doubles.
This module is intentionally different: the Windows launcher runs it before
opening the browser to prove that the configured hosted search and the NIFTY
market-data route work from the process context that will run Vibe-Trading.
"""

from __future__ import annotations

import datetime as dt
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class RuntimeCheck:
    """One non-sensitive live startup-check result."""

    name: str
    ok: bool
    message: str


def _load_project_environment() -> None:
    """Load ``agent/.env`` and refresh cached provider configuration."""
    from src.config.accessor import reset_env_config
    from src.providers.llm import _ensure_dotenv, _sync_provider_env

    _ensure_dotenv()
    reset_env_config()
    _sync_provider_env()
    reset_env_config()


def check_nifty_market_data(
    loader_factory: Callable[[], Any] | None = None,
    *,
    today: dt.date | None = None,
) -> RuntimeCheck:
    """Fetch recent NIFTY 50 bars through the exact Yahoo backtest loader."""
    if loader_factory is None:
        from backtest.loaders.yahoo_loader import DataLoader

        loader_factory = DataLoader

    end = today or dt.date.today()
    start = end - dt.timedelta(days=21)
    try:
        data = loader_factory().fetch(
            ["^NSEI"],
            start.isoformat(),
            end.isoformat(),
            interval="1D",
        )
        frame = data.get("^NSEI")
        if frame is None or frame.empty:
            return RuntimeCheck(
                "Market data / backtest",
                False,
                "NIFTY 50 returned no recent daily bars",
            )
        required = {"open", "high", "low", "close"}
        if not required.issubset(frame.columns):
            return RuntimeCheck(
                "Market data / backtest",
                False,
                "NIFTY 50 bars are missing required OHLC fields",
            )
        return RuntimeCheck(
            "Market data / backtest",
            True,
            f"NIFTY 50 returned {len(frame)} recent daily bars",
        )
    except Exception as exc:  # noqa: BLE001 - convert provider failures to a clean launcher result
        return RuntimeCheck(
            "Market data / backtest",
            False,
            f"{type(exc).__name__}: {exc}",
        )


def check_hosted_web_search(
    search: Callable[[str, int], list[dict] | None] | None = None,
) -> RuntimeCheck:
    """Verify the configured Responses endpoint can perform hosted web search."""
    if search is None:
        from src.tools.web_search_tool import _responses_api_search

        search = _responses_api_search

    try:
        results = search("official NSE NIFTY 50 historical data", 2)
        if not results:
            return RuntimeCheck(
                "Web search",
                False,
                "the configured Responses endpoint returned no cited sources",
            )
        usable = [
            item
            for item in results
            if str(item.get("url") or item.get("href") or "").startswith(("http://", "https://"))
        ]
        if not usable:
            return RuntimeCheck(
                "Web search",
                False,
                "the configured Responses endpoint returned no usable source URLs",
            )
        return RuntimeCheck(
            "Web search",
            True,
            f"hosted search returned {len(usable)} cited source(s)",
        )
    except Exception as exc:  # noqa: BLE001 - convert provider failures to a clean launcher result
        return RuntimeCheck("Web search", False, f"{type(exc).__name__}: {exc}")


def run_runtime_self_test(
    checks: Iterable[Callable[[], RuntimeCheck]] | None = None,
    *,
    timeout_seconds: float = 20.0,
) -> list[RuntimeCheck]:
    """Run live checks with a hard per-check deadline and never raise.

    Provider clients can carry production-sized HTTP timeouts. Startup probes
    must not keep the launcher blocked for minutes when an upstream service is
    unavailable, so each check runs on a daemon thread with a short deadline.
    """
    selected = checks or (check_nifty_market_data, check_hosted_web_search)
    results: list[RuntimeCheck] = []
    for check in selected:
        holder: list[RuntimeCheck] = []

        def run_one(current_check: Callable[[], RuntimeCheck] = check) -> None:
            try:
                holder.append(current_check())
            except Exception as exc:  # noqa: BLE001 - probes report, never abort startup
                holder.append(
                    RuntimeCheck(
                        getattr(current_check, "__name__", "runtime check"),
                        False,
                        f"{type(exc).__name__}: {exc}",
                    )
                )

        worker = threading.Thread(target=run_one, daemon=True, name="runtime-self-test")
        worker.start()
        worker.join(timeout=max(float(timeout_seconds), 0.01))
        if worker.is_alive():
            results.append(
                RuntimeCheck(
                    getattr(check, "__name__", "runtime check"),
                    False,
                    f"timed out after {timeout_seconds:g} seconds",
                )
            )
        elif holder:
            results.append(holder[0])
        else:
            results.append(RuntimeCheck("runtime check", False, "ended without a result"))
    return results


def main() -> int:
    """Command-line entry point used by the one-click Windows launcher."""
    try:
        _load_project_environment()
    except Exception as exc:  # noqa: BLE001 - keep launcher output concise and non-sensitive
        print(f"[FAIL] Configuration: {type(exc).__name__}: {exc}")
        return 1

    results = run_runtime_self_test()
    for result in results:
        label = "OK" if result.ok else "FAIL"
        print(f"[{label}] {result.name}: {result.message}")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
