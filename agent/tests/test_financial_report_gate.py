"""Regression tests for the annual-report substance gate.

The gate must admit genuine issuer annual reports — including BANK/NBFC reports
whose statement terminology differs from corporates and whose audited statements
may fall outside the extracted window — while still rejecting tiny ancillary
filings (secretarial-compliance certificates, notices, single annexures).
"""

from src.analysis.execution_backbone import _looks_like_financial_report, _MIN_REPORT_CHARS


def _pad(text: str, size: int = _MIN_REPORT_CHARS + 5_000) -> str:
    """Pad to a report-sized length without adding financial markers."""
    return text + (" lorem ipsum narrative" * ((size // 22) + 1))


def test_bank_report_front_matter_is_accepted() -> None:
    """A bank report window with bank-style signals passes (regression: ICICIBANK).

    Banks say "profit and loss account" / "net interest income", not "revenue
    from operations", and the audited statements can sit past the read window —
    the front matter still carries enough signal to recognise a real report.
    """
    text = _pad("balance sheet ... financial statements ... auditor's report ... shareholders ... deposits")
    assert _looks_like_financial_report(text) is True


def test_corporate_report_is_accepted() -> None:
    text = _pad("statement of profit and loss ... cash flow ... total assets ... notes to accounts")
    assert _looks_like_financial_report(text) is True


def test_small_compliance_filing_is_rejected() -> None:
    """A few-KB secretarial-compliance certificate is not an annual report."""
    ascr = "annual secretarial compliance report balance sheet financial statements " * 60
    assert len(ascr) < _MIN_REPORT_CHARS
    assert _looks_like_financial_report(ascr) is False


def test_large_non_financial_document_is_rejected() -> None:
    """Report-sized but with no financial-statement signal → rejected."""
    assert _looks_like_financial_report(_pad("company sustainability narrative only")) is False


def test_empty_is_rejected() -> None:
    assert _looks_like_financial_report("") is False
