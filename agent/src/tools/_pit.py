"""Small point-in-time window helpers shared by evidence tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class EvidenceWindow:
    start: date
    end: date


def parse_window(*, year: int | None = None, start_date: str | None = None,
                 end_date: str | None = None) -> EvidenceWindow:
    """Return an inclusive evidence window without silently guessing dates."""
    if year is not None:
        value = int(year)
        return EvidenceWindow(date(value, 1, 1), date(value, 12, 31))
    if not start_date or not end_date:
        today = date.today()
        return EvidenceWindow(date(today.year, 1, 1), today)
    return EvidenceWindow(date.fromisoformat(start_date), date.fromisoformat(end_date))
