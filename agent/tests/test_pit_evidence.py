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

from src.tools._pit import (
    filter_to_window,
    parse_published,
    parse_window,
    unavailable,
)


# --------------------------------------------------------------------------- #
# Window construction
# --------------------------------------------------------------------------- #


def test_year_shorthand_spans_whole_calendar_year() -> None:
    w = parse_window(year=2016)
    assert (w.start, w.end, w.label) == (dt.date(2016, 1, 1), dt.date(2016, 12, 31), "2016")


def test_explicit_range_wins_and_is_inclusive() -> None:
    w = parse_window(start_date="2016-04-01", end_date="2016-06-30")
    assert w.contains(dt.date(2016, 4, 1)) and w.contains(dt.date(2016, 6, 30))
    assert not w.contains(dt.date(2016, 3, 31)) and not w.contains(dt.date(2016, 7, 1))


def test_no_window_requested_returns_none() -> None:
    assert parse_window() is None


@pytest.mark.parametrize("bad", [{"year": "twenty-sixteen"}, {"year": 1799}])
def test_invalid_window_raises_rather_than_silently_unconstrained(bad) -> None:
    # Failing loudly matters: silently dropping the window would run the search
    # unconstrained and reintroduce the leak the window exists to prevent.
    with pytest.raises(ValueError):
        parse_window(**bad)


def test_inverted_range_raises() -> None:
    with pytest.raises(ValueError):
        parse_window(start_date="2016-12-31", end_date="2016-01-01")


# --------------------------------------------------------------------------- #
# Date parsing across the backends' formats
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw",
    [
        1468000000,  # epoch seconds (Yahoo providerPublishTime)
        "1468000000",
        "2016-07-08",
        "2016-07-08T10:00:00Z",
        "2016-07-08T10:00:00+05:30",
        "08 Jul 2016",
        "Jul 8, 2016",
        "08/07/2016",
    ],
)
def test_publication_dates_parse_to_the_same_day(raw) -> None:
    assert parse_published(raw) == dt.date(2016, 7, 8)


@pytest.mark.parametrize("raw", [None, "", "sometime last year", "n/a", True, 12])
def test_unparseable_dates_return_none(raw) -> None:
    assert parse_published(raw) is None


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
    kept, audit = filter_to_window(_records(), parse_window(year=2016))
    assert [r["title"] for r in kept] == ["in-window"]
    assert audit["dropped_outside_window"] == 2
    assert audit["dropped_undated"] == 1
    assert audit["enforced"] is True


def test_undated_records_are_dropped_not_assumed_in_window() -> None:
    """An unverifiable date is the exact vector lookahead leaks through."""
    kept, audit = filter_to_window([{"title": "undated"}], parse_window(year=2016))
    assert kept == []
    assert audit["dropped_undated"] == 1


def test_kept_records_are_stamped_with_the_verified_date() -> None:
    kept, _ = filter_to_window(_records(), parse_window(year=2016))
    assert kept[0]["published_date"] == "2016-07-08"


def test_no_window_passes_everything_through_unfiltered() -> None:
    kept, audit = filter_to_window(_records(), None)
    assert len(kept) == 4
    assert audit["enforced"] is False


def test_audit_block_is_always_emitted() -> None:
    """A reader must be able to see what was excluded, not take it on trust."""
    _, audit = filter_to_window(_records(), parse_window(year=2016))
    assert audit["examined"] == 4
    assert audit["kept"] == 1
    assert "fail-closed" in audit["policy"]


def test_unavailable_envelope_tells_the_caller_not_to_substitute() -> None:
    env = unavailable("no 2016 source", query="X")
    assert env["status"] == "unavailable"
    assert env["reason"] == "no 2016 source"
    assert "do not" in env["guidance"].lower()


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


def test_web_search_year_drops_out_of_window_results(monkeypatch) -> None:
    payload = [
        {"title": "2016 piece", "url": "u1", "source": "ET", "date": "2016-05-02", "body": "b"},
        {"title": "2019 piece", "url": "u2", "source": "ET", "date": "2019-05-02", "body": "b"},
    ]
    out = _run_search(monkeypatch, payload, query="q", year=2016)
    assert out["status"] == "ok"
    assert [r["title"] for r in out["results"]] == ["2016 piece"]
    assert out["evidence_window"]["dropped_outside_window"] == 1


def test_web_search_reports_unavailable_when_nothing_in_window(monkeypatch) -> None:
    payload = [{"title": "2019 only", "url": "u", "source": "ET", "date": "2019-05-02", "body": "b"}]
    out = _run_search(monkeypatch, payload, query="q", year=2016)
    assert out["status"] == "unavailable"
    assert "2016" in out["reason"]
    assert "results" not in out  # never degrade to out-of-window material


def test_web_search_invalid_year_is_an_error_not_an_open_search(monkeypatch) -> None:
    out = _run_search(monkeypatch, [], query="q", year="not-a-year")
    assert out["status"] == "error"
