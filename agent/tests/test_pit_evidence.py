"""Point-in-time evidence discipline: no lookahead leakage, fail-closed sourcing.

The bug these tests pin: research scored "as of 2016" was being fed undated and
later-dated articles, silently contaminating the conclusion with hindsight. The
contract is that a window admits ONLY evidence verified to fall inside it, and
that an empty result is reported as ``unavailable`` rather than back-filled with
material from another period.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from src.tools._pit import parse_window
from src.tools._sources import _in_window


# --------------------------------------------------------------------------- #
# Window construction
# --------------------------------------------------------------------------- #


def test_year_shorthand_spans_whole_calendar_year() -> None:
    w = parse_window(year=2016)
    assert (w.start, w.end) == (dt.date(2016, 1, 1), dt.date(2016, 12, 31))


def test_explicit_range_wins_and_is_inclusive() -> None:
    w = parse_window(start_date="2016-04-01", end_date="2016-06-30")
    assert w.start <= dt.date(2016, 4, 1) and dt.date(2016, 6, 30) <= w.end
    assert not (w.start <= dt.date(2016, 3, 31)) and not (dt.date(2016, 7, 1) <= w.end)


# --------------------------------------------------------------------------- #
# Date parsing across the backends' formats
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Fail-closed filtering — the core guarantee
# --------------------------------------------------------------------------- #


def _records() -> list[dict]:
    return [
        {"title": "in-window", "date": "2016-07-08"},
        {"title": "leak-from-next-year", "date": "2017-02-01"},
        {"title": "leak-from-prior-year", "date": "2015-12-31"},
        {"title": "undated"},
    ]


def test_window_admits_only_in_window_evidence() -> None:
    w = parse_window(year=2016)
    kept = [r for r in _records() if _in_window(r, w)]
    assert [r["title"] for r in kept] == ["in-window"]
    # Fail-closed: both out-of-window AND undated records are excluded — the
    # window admits only evidence verified to fall inside it.
    dropped = {r["title"] for r in _records() if not _in_window(r, w)}
    assert dropped == {"leak-from-next-year", "leak-from-prior-year", "undated"}


def test_undated_records_are_dropped_not_assumed_in_window() -> None:
    """An unverifiable date is the exact vector lookahead leaks through."""
    w = parse_window(year=2016)
    assert _in_window({"title": "undated"}, w) is False


# --------------------------------------------------------------------------- #
# web_search PIT branch (no network)
# --------------------------------------------------------------------------- #


class _FakeDDGS:
    """Stand-in for ddgs returning a fixed dated-news payload."""

    payload: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def news(self, query, max_results=None):  # noqa: D401, ARG002
        return list(self.payload)

    def text(self, *_args, **_kwargs):  # pragma: no cover - must not be used under a window
        raise AssertionError("text() carries no date and must never serve a PIT window")


def _run_search(monkeypatch, payload, **kwargs) -> dict:
    import src.tools.web_search_tool as mod

    _FakeDDGS.payload = payload
    monkeypatch.setitem(__import__("sys").modules, "ddgs", type("m", (), {"DDGS": _FakeDDGS}))
    return json.loads(mod.WebSearchTool().execute(**kwargs))


def test_web_search_invalid_year_is_an_error_not_an_open_search(monkeypatch) -> None:
    out = _run_search(monkeypatch, [], query="q", year="not-a-year")
    assert out["status"] == "error"
