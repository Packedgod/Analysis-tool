"""Point-in-time (PIT) evidence discipline shared by the evidence tools.

The guarantee here is *fail-closed*: when an evidence window is requested, a
record is kept only if its publication date can be verified to fall inside the
window. Undated and out-of-window records are dropped rather than assumed
in-window, because an unverifiable date is exactly the vector a look-ahead leak
slips through. Every filter emits an audit block so a reader can see what was
excluded instead of taking the result on trust.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

# Integer publication values below this are not plausible epoch seconds (this
# floor is ~1973); they are rejected rather than misread as a date.
_EPOCH_FLOOR = 100_000_000
# Reject implausibly old calendar years to catch typos / bad inputs loudly.
_MIN_YEAR = 1800

_TEXT_DATE_FORMATS = (
    "%d %b %Y",   # 08 Jul 2016
    "%d %B %Y",   # 08 July 2016
    "%b %d, %Y",  # Jul 8, 2016
    "%B %d, %Y",  # July 8, 2016
    "%d/%m/%Y",   # 08/07/2016  (day-first)
    "%d-%m-%Y",   # 08-07-2016  (day-first)
)


@dataclass(frozen=True)
class EvidenceWindow:
    start: date
    end: date

    def contains(self, value: date) -> bool:
        """Inclusive membership test."""
        return self.start <= value <= self.end

    @property
    def label(self) -> str:
        """Compact label: the bare year for a full calendar year, else a range."""
        if (
            self.start.year == self.end.year
            and (self.start.month, self.start.day) == (1, 1)
            and (self.end.month, self.end.day) == (12, 31)
        ):
            return str(self.start.year)
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


def parse_window(
    *, year: int | None = None, start_date: str | None = None, end_date: str | None = None
) -> EvidenceWindow | None:
    """Build an inclusive evidence window, or ``None`` when none is requested.

    Fails loudly (``ValueError``) on an invalid year or an inverted/half range,
    rather than silently running the search unconstrained — the very leak the
    window exists to prevent.
    """
    if year is not None:
        try:
            value = int(year)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid year: {year!r}") from exc
        if value < _MIN_YEAR:
            raise ValueError(f"implausible year: {value}")
        return EvidenceWindow(date(value, 1, 1), date(value, 12, 31))

    if start_date or end_date:
        if not (start_date and end_date):
            raise ValueError("both start_date and end_date are required for a range")
        start = date.fromisoformat(str(start_date))
        end = date.fromisoformat(str(end_date))
        if start > end:
            raise ValueError(f"inverted range: {start} > {end}")
        return EvidenceWindow(start, end)

    return None


def parse_published(raw: Any) -> date | None:
    """Parse a publication value from any backend format into a ``date``.

    Handles epoch seconds (int or digit-string), ISO dates/datetimes (with ``Z``
    or numeric offset), and common textual/numeric formats. Returns ``None`` for
    anything that cannot be verified — booleans and too-small integers included.
    """
    if raw is None or isinstance(raw, bool):
        return None

    # Epoch seconds (Yahoo providerPublishTime and friends).
    if isinstance(raw, (int, float)):
        return _from_epoch(raw)
    if not isinstance(raw, str):
        return None

    text = raw.strip()
    if not text:
        return None
    if text.isdigit():
        return _from_epoch(int(text))

    # ISO 8601, tolerating a trailing Z.
    iso = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        pass
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass

    for fmt in _TEXT_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _from_epoch(value: float) -> date | None:
    if value < _EPOCH_FLOOR:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def filter_to_window(
    records: list[dict[str, Any]], window: EvidenceWindow | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep only records verifiably inside ``window``; always emit an audit.

    With ``window=None`` nothing is enforced and every record passes through.
    Kept records are stamped with the verified ``published_date`` (ISO).
    """
    examined = len(records)
    if window is None:
        return list(records), {
            "examined": examined,
            "kept": examined,
            "dropped_outside_window": 0,
            "dropped_undated": 0,
            "enforced": False,
            "policy": "fail-closed PIT window not enforced (no window requested)",
        }

    kept: list[dict[str, Any]] = []
    dropped_outside = 0
    dropped_undated = 0
    for record in records:
        published = parse_published(record.get("date"))
        if published is None:
            dropped_undated += 1
            continue
        if window.contains(published):
            stamped = dict(record)
            stamped["published_date"] = published.isoformat()
            kept.append(stamped)
        else:
            dropped_outside += 1

    audit = {
        "examined": examined,
        "kept": len(kept),
        "dropped_outside_window": dropped_outside,
        "dropped_undated": dropped_undated,
        "enforced": True,
        "policy": "fail-closed: undated and out-of-window evidence dropped, never assumed in-window",
    }
    return kept, audit


def unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    """Envelope that tells the caller a window turned up nothing usable.

    The explicit guidance stops a caller from degrading to out-of-window or
    model-memory content when no verified evidence exists.
    """
    return {
        "status": "unavailable",
        "reason": reason,
        "guidance": "Do not substitute out-of-window results or model memory; report the gap instead.",
        **extra,
    }
