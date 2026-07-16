"""Verified-source ladder + official-domain resolution.

The failures pinned here are the ones that actually occurred while building this:

* the ladder must be walked in the configured order and stop at the first rung
  holding in-window evidence — the order is editorial policy, not a hint;
* a rung's results must be discarded unless they are really hosted on that rung's
  domain, or the attribution is a lie;
* domain resolution must be *correct or refuse*, never wrong. Real misfires seen:
  "Reliance Industries" -> reliance.com (Reliance, Inc., a US company),
  "HDFC Bank" -> bank.in, "Tata Consultancy Services" ->
  tataconsultingengineers.com (a different Tata company whose site lists its
  siblings). A wrong domain silently attributes another company's filings to the
  issuer, so these are regression-locked.
"""

from __future__ import annotations

import json

import pytest

from src.tools import _sources
from src.tools._pit import parse_window
from src.tools._sources import SOURCE_LADDER, Source, search_ladder


# --------------------------------------------------------------------------- #
# Ladder configuration
# --------------------------------------------------------------------------- #


def test_ladder_order_is_exactly_the_configured_policy() -> None:
    assert [s.name for s in SOURCE_LADDER] == [
        "mint",
        "economic_times",
        "reuters",
        "rbi",
        "sebi",
        "nse",
        "bse",
        "rating_agencies",
        "moneycontrol",
        "times_of_india",
        "yahoo_finance",
        "google_finance",
    ]


def test_rating_agency_rung_covers_all_three() -> None:
    rung = next(s for s in SOURCE_LADDER if s.name == "rating_agencies")
    assert set(rung.domains) == {"icra.in", "careratings.com", "crisil.com"}


# --------------------------------------------------------------------------- #
# Ladder walking
# --------------------------------------------------------------------------- #


class _FakeDDGS:
    """DDGS stand-in returning per-domain canned news."""

    by_domain: dict[str, list[dict]] = {}
    queries: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def news(self, query, max_results=None):  # noqa: ARG002
        _FakeDDGS.queries.append(query)
        for domain, items in self.by_domain.items():
            if f"site:{domain}" in query:
                return list(items)
        return []

    def text(self, query, max_results=None):  # noqa: ARG002
        return []


@pytest.fixture
def fake_ddgs(monkeypatch):
    _FakeDDGS.by_domain = {}
    _FakeDDGS.queries = []
    monkeypatch.setattr(_sources, "_ddgs", lambda: _FakeDDGS)
    return _FakeDDGS


def _article(domain: str, date: str = "2016-05-02") -> dict:
    return {"title": "t", "url": f"https://{domain}/story", "date": date, "body": "b"}


def test_first_rung_with_evidence_wins_and_walk_stops(fake_ddgs) -> None:
    fake_ddgs.by_domain = {
        "livemint.com": [_article("livemint.com")],
        "reuters.com": [_article("reuters.com")],
    }
    out = search_ladder("q", parse_window(year=2016))
    assert out["status"] == "ok"
    assert out["source"] == "mint"
    # Walk stopped: lower rungs were never queried.
    assert not any("reuters.com" in q for q in fake_ddgs.queries)


def test_walk_falls_through_empty_rungs_in_order(fake_ddgs) -> None:
    fake_ddgs.by_domain = {"reuters.com": [_article("reuters.com")]}
    out = search_ladder("q", parse_window(year=2016))
    assert out["source"] == "reuters"
    tried = [a["source"] for a in out["ladder"]]
    assert tried == ["mint", "economic_times", "reuters"]


def test_sweep_collects_from_every_rung(fake_ddgs) -> None:
    fake_ddgs.by_domain = {
        "livemint.com": [_article("livemint.com")],
        "reuters.com": [_article("reuters.com")],
    }
    out = search_ladder("q", parse_window(year=2016), sweep=True)
    assert {r["source"] for r in out["results"]} == {"mint", "reuters"}
    assert len(out["ladder"]) == len(SOURCE_LADDER)


def test_out_of_window_evidence_never_surfaces(fake_ddgs) -> None:
    fake_ddgs.by_domain = {"livemint.com": [_article("livemint.com", date="2019-05-02")]}
    out = search_ladder("q", parse_window(year=2016))
    assert out["status"] == "unavailable"
    assert "2016" in out["reason"]


def test_offdomain_results_are_rejected(fake_ddgs) -> None:
    """`site:` is a hint the engine may ignore; an off-domain hit would forge attribution."""
    fake_ddgs.by_domain = {"livemint.com": [_article("someblog.example", date="2016-05-02")]}
    out = search_ladder("q", parse_window(year=2016))
    assert out["status"] == "unavailable"


def test_a_dead_rung_does_not_abort_the_ladder(fake_ddgs, monkeypatch) -> None:
    class Boom(_FakeDDGS):
        def news(self, query, max_results=None):  # noqa: ARG002
            if "livemint.com" in query:
                raise RuntimeError("rung down")
            return [_article("reuters.com")] if "reuters.com" in query else []

    monkeypatch.setattr(_sources, "_ddgs", lambda: Boom)
    out = search_ladder("q", parse_window(year=2016))
    assert out["status"] == "ok" and out["source"] == "reuters"
    assert "error" in out["ladder"][0]


def test_unavailable_lists_every_rung_tried(fake_ddgs) -> None:
    out = search_ladder("q", parse_window(year=2016))
    assert out["status"] == "unavailable"
    assert [a["source"] for a in out["ladder"]] == [s.name for s in SOURCE_LADDER]


# --------------------------------------------------------------------------- #
# Official-domain resolution — correct or refuse, never wrong
# --------------------------------------------------------------------------- #


def test_name_tokens_keep_distinguishing_words() -> None:
    """'industries' must survive: dropping it collapsed Reliance Industries onto Reliance, Inc."""
    assert _sources._name_tokens("Reliance Industries") == ["reliance", "industries"]
    assert _sources._name_tokens("HDFC Bank") == ["hdfc", "bank"]
    # Legal-form words carry no signal and are still dropped.
    assert "limited" not in _sources._name_tokens("Infosys Limited")


class _Resp:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def _patch_fetch(monkeypatch, pages: dict[str, _Resp]):
    def fake_get(url, **_kw):
        for host, resp in pages.items():
            if f"//{host}" in url:
                return resp
        raise RuntimeError("unreachable")

    monkeypatch.setattr("backtest.loaders._http.throttled_get", fake_get)


def test_site_identity_confirms_the_real_issuer(monkeypatch) -> None:
    _patch_fetch(monkeypatch, {"ril.com": _Resp(200, "<title>Reliance Industries Limited</title>")})
    ok, why = _sources._verify_domain("ril.com", ["reliance", "industries"])
    assert ok and "identity" in why


def test_sibling_company_mentioning_the_name_in_body_is_rejected(monkeypatch) -> None:
    """Tata group sites list their siblings; a body mention is not ownership."""
    html = "<title>Tata Consulting Engineers</title><body>part of the Tata group with Tata Consultancy Services</body>"
    _patch_fetch(monkeypatch, {"tataconsultingengineers.com": _Resp(200, html)})
    ok, _ = _sources._verify_domain(
        "tataconsultingengineers.com", ["tata", "consultancy", "services"]
    )
    assert ok is False


def test_us_namesake_is_rejected_for_the_indian_issuer(monkeypatch) -> None:
    """reliance.com is Reliance, Inc. — a different company on another continent."""
    _patch_fetch(monkeypatch, {"reliance.com": _Resp(200, "<title>Reliance, Inc.</title>")})
    ok, _ = _sources._verify_domain("reliance.com", ["reliance", "industries"])
    assert ok is False


def test_domain_spelling_the_name_verifies_when_site_blocks_fetch(monkeypatch) -> None:
    _patch_fetch(monkeypatch, {"hdfcbank.com": _Resp(403, "blocked")})
    ok, why = _sources._verify_domain("hdfcbank.com", ["hdfc", "bank"])
    assert ok and "registered domain" in why


def test_url_paths_mentioning_a_company_do_not_confer_ownership(monkeypatch) -> None:
    """bank.in/hdfc-bank-ifsc mentions the bank without being it."""
    _patch_fetch(monkeypatch, {"bank.in": _Resp(403, "blocked")})
    ok, _ = _sources._verify_domain("bank.in", ["hdfc", "bank"], " https://bank.in/hdfc-bank-ifsc ")
    assert ok is False


def test_unreachable_site_is_not_treated_as_verified(monkeypatch) -> None:
    _patch_fetch(monkeypatch, {})
    ok, _ = _sources._verify_domain("mystery.example", ["acme", "widgets"])
    assert ok is False


def test_aggregators_are_never_official() -> None:
    for host in ("moneycontrol.com", "en.wikipedia.org", "screener.in", "trendlyne.com"):
        assert _sources._is_aggregator(host)
    assert not _sources._is_aggregator("ril.com")


# --------------------------------------------------------------------------- #
# Fiscal-year labelling of documents
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://ril.com/reports/RIL-Integrated-Annual-Report-2016-17.pdf", 2016),
        ("https://x.com/ar/AnnualReport2016.pdf", 2016),
        ("https://x.com/investors/overview", None),
    ],
)
def test_document_year_comes_from_the_report_identity(url, expected) -> None:
    assert _sources._document_year(url, "") == expected


def test_tool_reports_unavailable_rather_than_guessing(monkeypatch) -> None:
    from src.tools.official_evidence_tool import CompanyDocumentsTool

    monkeypatch.setattr(
        _sources,
        "resolve_official_domain",
        lambda c: {"status": "unavailable", "reason": "unconfirmed"},
    )
    out = json.loads(CompanyDocumentsTool().execute(company="Mystery Corp"))
    assert out["status"] == "unavailable"
    assert "documents" not in out
