"""Point-in-time clock: render the whole system as of a historical date.

Why this exists
---------------
Research integrity dies on look-ahead. A backtest, a screen, or a "what would I
have concluded in June 2021?" study is worthless if any fetch quietly returns
data published after the decision date. Per-tool PIT filters (see
``src.tools._pit`` for evidence windows) each guard one doorway; this module is
the *clock the whole house runs on*: a process/task-scoped as-of date that the
data-access layer enforces uniformly, so a leak cannot slip in through a loader
nobody remembered to patch.

Safety stance
-------------
**Unset by default, and unset means strict no-op.** With no as-of date engaged,
every function here returns its input unchanged and no code path behaves
differently — the guarantee that turning this module on is opt-in and turning it
off restores exact prior behaviour. The clock is stored in a
:class:`~contextvars.ContextVar`, so concurrent tasks/threads can each hold their
own as-of date without bleeding into one another.

Enforcement is *fail-closed and audited*: rows dated after the as-of date are
dropped, not trusted, and each drop is recorded in a leak ledger so a reader can
see what was withheld instead of taking the result on faith.

Usage::

    with as_of_scope("2021-06-30"):
        data = loader.fetch(codes, "2015-01-01", "2026-01-01", interval="1D")
        # every frame is clipped at 2021-06-30; the requested end is clamped too
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from datetime import date
from typing import Any, Dict, Iterator, List, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

DateLike = Union[str, date, pd.Timestamp, None]

# The clock. ``None`` == live mode == every helper is a no-op.
_AS_OF: contextvars.ContextVar[Optional[pd.Timestamp]] = contextvars.ContextVar(
    "vantage_as_of", default=None
)
# Audit ledger of everything withheld while the clock was engaged.
_LEAK_LEDGER: contextvars.ContextVar[Optional[List[Dict[str, Any]]]] = contextvars.ContextVar(
    "vantage_as_of_ledger", default=None
)


def _coerce(value: DateLike) -> Optional[pd.Timestamp]:
    """Normalise a date-like to a tz-naive midnight Timestamp (None passes through)."""
    if value is None:
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(None) if ts.tz is not None else ts.tz_localize(None)
    return ts.normalize()


def get_as_of() -> Optional[pd.Timestamp]:
    """Current as-of date, or ``None`` when running live (the default)."""
    return _AS_OF.get()


def is_engaged() -> bool:
    """Whether a point-in-time clock is currently set."""
    return _AS_OF.get() is not None


def set_as_of(value: DateLike) -> contextvars.Token:
    """Engage (or clear, with ``None``) the clock. Returns a reset token."""
    return _AS_OF.set(_coerce(value))


def reset_as_of(token: contextvars.Token) -> None:
    """Restore the clock to its value before the matching :func:`set_as_of`."""
    _AS_OF.reset(token)


@contextmanager
def as_of_scope(value: DateLike) -> Iterator[Optional[pd.Timestamp]]:
    """Scope the clock to a block, restoring the previous value on exit.

    ``as_of_scope(None)`` explicitly runs live inside the block, which is the
    documented way to make a deliberate "current data" call from inside a
    historical study.
    """
    token = set_as_of(value)
    ledger_token = _LEAK_LEDGER.set([])
    try:
        yield get_as_of()
    finally:
        _LEAK_LEDGER.reset(ledger_token)
        reset_as_of(token)


def leak_ledger() -> List[Dict[str, Any]]:
    """Audit records of data withheld by the clock in the current scope."""
    return list(_LEAK_LEDGER.get() or [])


def _record(entry: Dict[str, Any]) -> None:
    ledger = _LEAK_LEDGER.get()
    if ledger is not None:
        ledger.append(entry)


def clamp_end_date(end_date: str) -> str:
    """Clamp a fetch window's end to the as-of date (no-op when unset).

    Requesting data through 2026 while standing at 2021-06-30 must fetch only
    through 2021-06-30 — clamping at the request keeps the cache key honest and
    avoids paying for data that would be discarded anyway.
    """
    cutoff = get_as_of()
    if cutoff is None or not end_date:
        return end_date
    try:
        requested = pd.Timestamp(end_date).normalize()
    except (ValueError, TypeError):
        return end_date
    if requested <= cutoff:
        return end_date
    _record({"kind": "window_clamped", "requested_end": str(end_date), "clamped_to": cutoff.date().isoformat()})
    return cutoff.date().isoformat()


def window_is_empty(start_date: str, end_date: str) -> bool:
    """Whether the as-of clock has clipped this window out of existence.

    True when the window starts after the as-of date — i.e. the caller is asking
    for data that did not exist yet at the decision date.
    """
    cutoff = get_as_of()
    if cutoff is None or not start_date:
        return False
    try:
        start = pd.Timestamp(start_date).normalize()
    except (ValueError, TypeError):
        return False
    return start > cutoff


def enforce_frame(frame: Optional[pd.DataFrame], label: str = "") -> Optional[pd.DataFrame]:
    """Drop rows dated after the as-of date (no-op when the clock is unset).

    Operates on a ``DatetimeIndex``; a frame indexed otherwise is returned
    untouched (nothing to compare), so this can be applied blindly at a
    chokepoint without knowing each loader's shape.
    """
    cutoff = get_as_of()
    if cutoff is None or frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return frame
    index = frame.index
    if not isinstance(index, pd.DatetimeIndex):
        return frame
    if index.tz is not None:
        comparable = index.tz_convert(None)
    else:
        comparable = index
    mask = comparable.normalize() <= cutoff
    n_dropped = int((~mask).sum())
    if n_dropped == 0:
        return frame
    _record({
        "kind": "rows_withheld",
        "label": label or "frame",
        "rows_dropped": n_dropped,
        "as_of": cutoff.date().isoformat(),
    })
    logger.debug("as-of %s: withheld %d future row(s) from %s", cutoff.date(), n_dropped, label or "frame")
    return frame.loc[mask]


def enforce_data_map(data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Apply :func:`enforce_frame` across a ``code -> frame`` map (no-op when unset)."""
    if get_as_of() is None or not data_map:
        return data_map
    return {code: enforce_frame(frame, label=code) for code, frame in data_map.items()}


def audit_block() -> Dict[str, Any]:
    """JSON-safe summary of the clock and everything it withheld."""
    cutoff = get_as_of()
    ledger = leak_ledger()
    return {
        "as_of": cutoff.date().isoformat() if cutoff is not None else None,
        "engaged": cutoff is not None,
        "withheld_events": len(ledger),
        "rows_withheld": sum(int(e.get("rows_dropped", 0)) for e in ledger),
        "events": ledger[:50],
    }
