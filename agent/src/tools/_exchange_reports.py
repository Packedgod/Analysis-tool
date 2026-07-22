"""Structured exchange annual-report discovery and robust report extraction.

Search engines (Google/Brave HTML scraping) get CAPTCHA-blocked and JavaScript
investor-relations pages cannot be crawled with plain ``requests``. That made
report discovery fail for many perfectly ordinary Indian listings even though
every issuer files its annual reports with the exchange.

This module fetches those reports from the sources that are both authoritative
and machine-friendly: the National Stock Exchange and BSE annual-report indices,
which return direct PDF links for any listed symbol. The two exchanges back each
other up, so a dead or missing link on one is recovered from the other. It also
provides a single robust extractor that turns a downloaded report (PDF, or the
ZIP wrapper NSE sometimes serves) into text, and a raw-file store so a report is
only fetched once and is then available offline for future runs.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_REPORT_STORE = _DATA_DIR / "report_pdf_store"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_NSE_HOME = "https://www.nseindia.com"
_NSE_REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-annual-reports"
_NSE_API = "https://www.nseindia.com/api/annual-reports"

_BSE_HOME = "https://www.bseindia.com/"
_BSE_AR_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w"
_BSE_SCRIP_API = (
    "https://api.bseindia.com/BseIndiaAPI/api/ListOfScripData/w"
    "?Group=&Scripcode=&industry=&segment=Equity&status=Active"
)
_BSE_SCRIP_CACHE = _DATA_DIR / "bse_scrip_master.json"
_BSE_SCRIP_TTL = 30 * 24 * 3600  # refresh the scrip master monthly

# Keep concurrent pressure on the exchanges polite so their bot filters hold.
_NSE_GATE = threading.BoundedSemaphore(4)
_BSE_GATE = threading.BoundedSemaphore(4)
_BSE_MAP_LOCK = threading.Lock()
_BSE_SCRIP_MAP: dict[str, str] | None = None
_LOCAL = threading.local()

# PDFium is not thread-safe. The backbone extracts several reports concurrently,
# so every call into the native library must hold this process-wide lock or the
# interpreter aborts (SIGABRT). Extraction is CPU-bound and short, so serializing
# it is acceptable; downloads and discovery stay fully parallel.
_PDFIUM_LOCK = threading.Lock()


def _india_symbol(code: str) -> str | None:
    """Return the bare NSE symbol for an Indian listing, or ``None``."""
    upper = code.strip().upper()
    if not upper:
        return None
    base, _, suffix = upper.partition(".")
    # NSE covers .NS and .BO (dual-listed) plus suffix-less Indian tickers.
    # Explicitly non-Indian venues are skipped.
    if suffix in {"US", "HK", "SH", "SZ", "BJ", "L", "TO", "AX", "SS", "T", "KS", "TW"}:
        return None
    return base or None


def _nse_session() -> requests.Session:
    """Thread-local NSE session warmed with the cookies its API requires."""
    session = getattr(_LOCAL, "nse_session", None)
    if session is not None:
        return session
    session = requests.Session()
    session.headers.update({
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    _LOCAL.nse_session = session
    _warm_nse_session(session)
    return session


def _warm_nse_session(session: requests.Session) -> None:
    """Prime NSE cookies; safe to call again to recover from an expiry block."""
    try:
        session.get(_NSE_HOME, timeout=15)
        session.get(_NSE_REFERER, timeout=15)
    except requests.RequestException:
        pass


def nse_annual_reports(code: str) -> list[dict[str, Any]]:
    """Return NSE-hosted annual reports for a listing, newest fiscal year first.

    Each row is ``{"fiscal_year", "from_yr", "to_yr", "url", "title"}``. The
    fiscal year follows the Indian convention of the year the reporting period
    ends (a 2022-2023 report is FY2023), matching the rest of the backbone.
    Returns an empty list for non-Indian listings or when NSE has no filing.
    """
    symbol = _india_symbol(code)
    if not symbol:
        return []

    with _NSE_GATE:
        payload = _nse_api_call(symbol)
    if payload is None:
        return []

    rows: list[dict[str, Any]] = []
    seen_years: set[int] = set()
    for entry in payload.get("data") or []:
        url = str(entry.get("fileName") or "").strip()
        to_yr = str(entry.get("toYr") or "").strip()
        from_yr = str(entry.get("fromYr") or "").strip()
        if not url or not url.lower().startswith("http") or not to_yr.isdigit():
            continue
        year = int(to_yr)
        # Keep the first (primary) filing per fiscal year; later duplicates are
        # usually XBRL/unaudited variants of the same report.
        if year in seen_years:
            continue
        seen_years.add(year)
        label = f"{entry.get('companyName') or symbol} Annual Report {from_yr}-{to_yr}".strip()
        rows.append({
            "fiscal_year": year, "from_yr": from_yr, "to_yr": to_yr,
            "url": url, "title": label,
        })
    rows.sort(key=lambda row: row["fiscal_year"], reverse=True)
    return rows


def _nse_api_call(symbol: str) -> dict[str, Any] | None:
    """Call the NSE annual-reports API with one warm-and-retry on a bot block."""
    session = _nse_session()
    api_headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": _NSE_REFERER,
        "X-Requested-With": "XMLHttpRequest",
    }
    params = {"index": "equities", "symbol": symbol}
    for attempt in range(3):
        try:
            response = session.get(_NSE_API, headers=api_headers, params=params, timeout=25)
        except requests.RequestException:
            time.sleep(0.6 * (attempt + 1))
            _warm_nse_session(session)
            continue
        if response.status_code == 200:
            try:
                return response.json()
            except ValueError:
                return None
        if response.status_code in {401, 403, 429} and attempt < 2:
            time.sleep(0.8 * (attempt + 1))
            _warm_nse_session(session)
            continue
        break
    return None


def _bse_session() -> requests.Session:
    """Thread-local BSE session with the headers its JSON API expects."""
    session = getattr(_LOCAL, "bse_session", None)
    if session is not None:
        return session
    session = requests.Session()
    session.headers.update({
        "User-Agent": _USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": _BSE_HOME,
        "Origin": "https://www.bseindia.com",
    })
    _LOCAL.bse_session = session
    return session


def _load_bse_scrip_map() -> dict[str, str]:
    """Map NSE-style symbol and ISIN to BSE scrip code (cached on disk monthly)."""
    global _BSE_SCRIP_MAP
    if _BSE_SCRIP_MAP is not None:
        return _BSE_SCRIP_MAP
    with _BSE_MAP_LOCK:
        if _BSE_SCRIP_MAP is not None:
            return _BSE_SCRIP_MAP
        rows = _read_bse_scrip_cache()
        if rows is None:
            rows = _fetch_bse_scrip_master()
        mapping: dict[str, str] = {}
        for row in rows or []:
            code = str(row.get("SCRIP_CD") or "").strip()
            if not code:
                continue
            symbol = str(row.get("scrip_id") or "").strip().upper()
            isin = str(row.get("ISIN_NUMBER") or "").strip().upper()
            if symbol:
                mapping.setdefault(symbol, code)
            if isin:
                mapping.setdefault(isin, code)
        _BSE_SCRIP_MAP = mapping
        return mapping


def _read_bse_scrip_cache() -> list[dict[str, Any]] | None:
    try:
        age = time.time() - os.path.getmtime(_BSE_SCRIP_CACHE)
        if age > _BSE_SCRIP_TTL:
            return None
        return json.loads(_BSE_SCRIP_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _fetch_bse_scrip_master() -> list[dict[str, Any]]:
    try:
        with _BSE_GATE:
            response = _bse_session().get(_BSE_SCRIP_API, timeout=60)
        response.raise_for_status()
        payload = response.json()
        rows = payload if isinstance(payload, list) else payload.get("Table") or []
    except (requests.RequestException, ValueError):
        return []
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _BSE_SCRIP_CACHE.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_BSE_SCRIP_CACHE)
    except OSError:
        pass
    return rows


def _bse_scrip_code(code: str) -> str | None:
    symbol = _india_symbol(code)
    if not symbol:
        return None
    return _load_bse_scrip_map().get(symbol.upper())


def bse_annual_reports(code: str) -> list[dict[str, Any]]:
    """Return BSE-hosted annual reports for a listing, newest fiscal year first.

    Rows are ``{"fiscal_year", "url", "title"}``. BSE labels each report by the
    year the fiscal period ends, matching NSE and the rest of the backbone.
    """
    scrip = _bse_scrip_code(code)
    if not scrip:
        return []
    try:
        with _BSE_GATE:
            response = _bse_session().get(_BSE_AR_API, params={"scripcode": scrip}, timeout=25)
        response.raise_for_status()
        table = response.json().get("Table") or []
    except (requests.RequestException, ValueError):
        return []

    rows: list[dict[str, Any]] = []
    seen_years: set[int] = set()
    for entry in table:
        url = str(entry.get("PDFDownload") or "").strip()
        year_text = str(entry.get("Year") or "").strip()
        if not url or not url.lower().startswith("http") or not year_text.isdigit():
            continue
        year = int(year_text)
        if year in seen_years:
            continue
        seen_years.add(year)
        name = str(entry.get("scrip_name") or _india_symbol(code) or "").strip()
        rows.append({"fiscal_year": year, "url": url, "title": f"{name} Annual Report {year}"})
    rows.sort(key=lambda row: row["fiscal_year"], reverse=True)
    return rows


def _raw_store_path(url: str, data: bytes) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    if data[:2] == b"PK":
        suffix = ".zip"
    elif data[:4] == b"%PDF":
        suffix = ".pdf"
    else:
        suffix = ".bin"
    return RAW_REPORT_STORE / f"{key}{suffix}"


def _cached_raw(url: str) -> bytes | None:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    for suffix in (".pdf", ".zip", ".bin"):
        path = RAW_REPORT_STORE / f"{key}{suffix}"
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if data:
            return data
    return None


def _store_raw(url: str, data: bytes) -> None:
    if len(data) < 1024:
        return
    try:
        RAW_REPORT_STORE.mkdir(parents=True, exist_ok=True)
        path = _raw_store_path(url, data)
        tmp = path.with_suffix(path.suffix + f".{threading.get_ident()}.tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        pass


def fetch_document_bytes(url: str, *, timeout: float = 90.0) -> bytes:
    """Download a report once and keep the raw file for offline reuse.

    Exchange hosts are fetched through the warmed NSE session (with the referer
    they expect); everything else uses the shared throttled HTTP client. A file
    already in the raw store is returned without touching the network.
    """
    cached = _cached_raw(url)
    if cached is not None:
        return cached

    host = url.split("/", 3)[2].lower() if "://" in url else ""
    if "nseindia.com" in host:
        session = _nse_session()
        response = session.get(url, headers={"Referer": _NSE_REFERER}, timeout=timeout)
        if response.status_code in {401, 403, 429}:
            _warm_nse_session(session)
            response = session.get(url, headers={"Referer": _NSE_REFERER}, timeout=timeout)
        response.raise_for_status()
        data = bytes(response.content)
    elif "bseindia.com" in host:
        response = _bse_session().get(url, headers={"Referer": _BSE_HOME}, timeout=timeout)
        response.raise_for_status()
        data = bytes(response.content)
    else:
        from backtest.loaders._http import throttled_get  # noqa: PLC0415

        response = throttled_get(
            url, host_key=f"report-download:{host or url}",
            min_interval=0.4, timeout=timeout,
        )
        response.raise_for_status()
        data = bytes(response.content)

    _store_raw(url, data)
    return data


def _pdf_to_text(data: bytes, *, max_pages: int = 400, char_budget: int = 260_000) -> str:
    """Extract text page by page, stopping once the stored-text budget is met.

    Downstream storage caps report text at 250k characters, so there is no need
    to hold an entire 700-page filing in memory; stopping early bounds both time
    and peak memory when baskets contain very large conglomerate reports.
    """
    import pypdfium2 as pdfium  # noqa: PLC0415

    with _PDFIUM_LOCK:
        document = pdfium.PdfDocument(data)
        try:
            parts: list[str] = []
            total = 0
            for index in range(min(len(document), max_pages)):
                page = document[index]
                textpage = page.get_textpage()
                chunk = textpage.get_text_range()
                textpage.close()
                page.close()
                parts.append(chunk)
                total += len(chunk) + 1
                if total >= char_budget:
                    break
            return "\n".join(parts)
        finally:
            document.close()


def document_bytes_to_text(data: bytes) -> str:
    """Turn report bytes into text, transparently unwrapping a ZIP-packed PDF.

    Corrupt or truncated downloads return an empty string rather than raising, so
    the caller cleanly moves on to the next candidate source.
    """
    try:
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                pdf_names = [name for name in bundle.namelist() if name.lower().endswith(".pdf")]
                pdf_names.sort(key=lambda name: bundle.getinfo(name).file_size, reverse=True)
                if not pdf_names:
                    return ""
                return _pdf_to_text(bundle.read(pdf_names[0]))
        if data[:4] == b"%PDF":
            return _pdf_to_text(data)
    except Exception:  # noqa: BLE001 - unreadable file, let the caller fall back
        return ""
    return ""
