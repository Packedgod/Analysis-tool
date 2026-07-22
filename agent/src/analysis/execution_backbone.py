"""Enforce the issuer-report + two-workbook contract before simulations run."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.analysis.master_factors import factor_pack, load_master_factor_registry
from src.tools import _sources
from src.tools.web_reader_tool import read_url

MANIFEST_NAME = "analysis_backbone.json"
SCHEMA_VERSION = 1
REPORT_TEXT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "report_text_cache"


def _cached_report_text(url: str) -> str | None:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    text_path = REPORT_TEXT_CACHE_DIR / f"{key}.txt"
    hash_path = REPORT_TEXT_CACHE_DIR / f"{key}.sha256"
    try:
        content = text_path.read_text(encoding="utf-8")
        expected = hash_path.read_text(encoding="ascii").strip()
        if len(content) >= 200 and hashlib.sha256(content.encode("utf-8")).hexdigest() == expected:
            return content
    except OSError:
        pass
    return None


def _store_report_text(url: str, content: str) -> None:
    if len(content) < 200:
        return
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    try:
        REPORT_TEXT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        text_path = REPORT_TEXT_CACHE_DIR / f"{key}.txt"
        hash_path = REPORT_TEXT_CACHE_DIR / f"{key}.sha256"
        text_tmp = text_path.with_suffix(f".{threading.get_ident()}.tmp")
        hash_tmp = hash_path.with_suffix(f".{threading.get_ident()}.tmp")
        text_tmp.write_text(content, encoding="utf-8")
        hash_tmp.write_text(digest, encoding="ascii")
        text_tmp.replace(text_path)
        hash_tmp.replace(hash_path)
    except OSError:
        pass


def _codes(config: dict[str, Any]) -> set[str]:
    raw = config.get("codes") or config.get("symbols") or config.get("tickers") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    return {str(item).strip().upper() for item in raw if str(item).strip()}


def _workbook_identity() -> list[dict[str, Any]]:
    return [
        {key: source[key] for key in ("filename", "sha256", "role", "verification_status")}
        for source in load_master_factor_registry()["sources"]
    ]


def _read_report(url: str) -> tuple[str, str]:
    """Read report text: cache, then direct PDF/ZIP download, then web reader."""
    cached = _cached_report_text(url)
    if cached is not None:
        return cached, "persistent_integrity_checked_cache"

    # Direct download first. It is deterministic, keeps a reusable raw copy, and
    # unwraps the ZIP-packed PDFs exchanges sometimes serve. The remote reader is
    # only a fallback because it rate-limits and mangles large filings.
    from src.tools._exchange_reports import (  # noqa: PLC0415
        document_bytes_to_text, fetch_document_bytes,
    )

    direct_error: str | None = None
    try:
        raw = fetch_document_bytes(url)
        if raw[:2] == b"PK" or raw[:4] == b"%PDF":
            text = document_bytes_to_text(raw)[:250_000]
            if len(text) >= 200:
                return text, "direct_pdf"
        else:
            from bs4 import BeautifulSoup  # noqa: PLC0415

            text = BeautifulSoup(raw, "html.parser").get_text("\n", strip=True)[:250_000]
            if len(text) >= 200:
                return text, "direct_html"
    except Exception as exc:  # noqa: BLE001 - fall through to the remote reader
        direct_error = str(exc)

    try:
        parsed = json.loads(read_url(url, no_cache=True))
        content = str(parsed.get("content") or "")
        if parsed.get("status") == "ok" and len(content) >= 200:
            return content, "web_reader"
    except Exception:
        pass

    if direct_error:
        raise RuntimeError(f"report download failed: {direct_error}")
    raise RuntimeError("report could not be read from any source")


def _config_report_span(config: dict[str, Any]) -> tuple[int, int] | None:
    try:
        start = int(str(config["start_date"])[:4])
        end = min(int(str(config["end_date"])[:4]), datetime.now(timezone.utc).year - 1)
        return (min(start, end), max(start, end))
    except (KeyError, TypeError, ValueError):
        return None


def _required_report_fallbacks(code: str) -> set[str]:
    upper = code.upper()
    if upper.endswith((".NS", ".BO")):
        return {"nse", "bse", "sebi", "moneycontrol", "annualreports_archive"}
    if upper.endswith(".US"):
        return {"sec_edgar", "annualreports_archive"}
    if upper.endswith(".HK"):
        return {"hkex", "annualreports_archive"}
    if upper.endswith(".SH"):
        return {"sse", "cninfo", "annualreports_archive"}
    if upper.endswith((".SZ", ".BJ")):
        return {"cninfo", "szse_or_bse_cn", "annualreports_archive"}
    return {"nse", "bse", "sebi", "moneycontrol", "annualreports_archive"}


def _ingest_document(
    *, run_path: Path, evidence_dir: Path, company: str, code: str,
    document: dict[str, Any], official_domain: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Read and persist one report candidate, returning a manifest record."""
    try:
        content, reader = _read_report(str(document["url"]))
    except Exception as exc:  # noqa: BLE001
        _sources.reject_cached_document(code, company, str(document.get("url") or ""))
        return None, str(exc)
    if len(content) < 200:
        _sources.reject_cached_document(code, company, str(document.get("url") or ""))
        return None, "extracted report text was too short"
    if not _report_content_matches(content, company, code):
        _sources.reject_cached_document(code, company, str(document.get("url") or ""))
        return None, "extracted document does not identify the requested issuer"
    if not _looks_like_financial_report(content):
        _sources.reject_cached_document(code, company, str(document.get("url") or ""))
        return None, "document lacks financial statements (not a full annual report)"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    _store_report_text(str(document["url"]), content)
    _sources.mark_cached_document_verified(code, company, str(document["url"]), digest)
    safe_code = re.sub(r"[^A-Z0-9]+", "_", code)
    local_path = evidence_dir / f"{safe_code}_{document.get('fiscal_year')}_{digest[:12]}.md"
    local_path.write_text(content, encoding="utf-8")
    return ({
        "fiscal_year": document.get("fiscal_year"),
        "url": document["url"],
        "title": document.get("title"),
        "repository": document.get("source"),
        "source_tier": document.get("source_tier"),
        "authoritative_repository": document.get("authoritative_repository"),
        "official_domain": official_domain,
        "read_status": "verified", "reader": reader,
        "content_bytes": len(content.encode("utf-8")),
        "content_sha256": digest,
        "evidence_path": str(local_path.relative_to(run_path)),
    }, None)


_FINANCIAL_MARKERS = (
    "balance sheet", "cash flow", "profit and loss", "statement of profit",
    "statement of financial position", "revenue from operations", "total equity",
    "total assets", "earnings per share", "independent auditor", "notes to",
    "financial statements",
)


def _looks_like_financial_report(content: str) -> bool:
    """Require a real annual report: substantial text with financial statements.

    Guards against accepting an issuer's ancillary filings (secretarial
    compliance reports, BRSR, notices) that mention the company but contain no
    income statement, balance sheet, or cash-flow data to analyse.
    """
    low = content.casefold()
    hits = sum(1 for marker in _FINANCIAL_MARKERS if marker in low)
    return len(content) >= 40_000 and hits >= 3


def _report_content_matches(content: str, company: str, code: str) -> bool:
    """Require repeated issuer identity inside the document, not merely its URL."""
    normalized = re.sub(r"[^a-z0-9]+", " ", content.casefold())
    tokens = [
        token for token in re.findall(r"[a-z0-9]+", company.casefold())
        if token not in {"the", "ltd", "limited", "inc", "corp", "corporation", "plc"}
        and len(token) > 1
    ]
    if tokens and all(len(re.findall(rf"\b{re.escape(token)}\b", normalized)) >= 2 for token in tokens):
        return True
    phrase = " ".join(tokens)
    if len(phrase) >= 5 and normalized.count(phrase) >= 2:
        return True
    # Many issuers brand themselves by acronym and rarely spell the full legal
    # name in the report body (e.g. "L&T" for Larsen & Toubro, "M&M" for Mahindra
    # & Mahindra). Accept a frequent, distinctively-punctuated initialism.
    if len(tokens) >= 2:
        initials = "".join(token[0] for token in tokens)
        if len(initials) >= 2:
            raw = content.casefold()
            branded = ["&".join(initials), ".".join(initials) + ".", " & ".join(initials)]
            if any(raw.count(form) >= 3 for form in branded):
                return True
            if len(re.findall(rf"\b{re.escape(initials)}\b", normalized)) >= 4:
                return True
    bare_code = code.rsplit(".", 1)[0].casefold()
    return len(bare_code) >= 3 and len(re.findall(rf"\b{re.escape(bare_code)}\b", normalized)) >= 3


def prepare_company_backbone(
    *, run_path: Path, companies: list[dict[str, Any]], history_years: int = 5,
    start_year: int | None = None, end_year: int | None = None,
) -> dict[str, Any]:
    """Fetch and ingest official reports, load both workbooks, then persist proof."""
    history_years = max(1, min(int(history_years), 60))
    if not companies:
        return {"status": "blocked", "error": "at least one resolved company is required"}

    records: list[dict[str, Any]] = []
    blockers: list[str] = []
    valid_companies: list[tuple[dict[str, Any], str, str, str, Any, Any]] = []
    for company in companies:
        name = str(company.get("company") or company.get("name") or "").strip()
        code = str(company.get("code") or company.get("ticker") or "").strip().upper()
        sector = str(company.get("sector") or "").strip()
        if not name or not code or not sector:
            blockers.append(f"company entry requires verified company, code, and sector: {company!r}")
            continue
        company_start = company.get("start_year", start_year)
        company_end = company.get("end_year", end_year)
        valid_companies.append((company, name, code, sector, company_start, company_end))

    def discover(item: tuple[dict[str, Any], str, str, str, Any, Any]) -> dict[str, Any]:
        _, name, code, _, company_start, company_end = item
        try:
            return _sources.company_documents(
                name, code=code, history_years=max(5, history_years),
                start_year=company_start, end_year=company_end,
            )
        except Exception as exc:  # noqa: BLE001 - isolate failures in large baskets
            return {"status": "unavailable", "reason": f"report discovery failed: {exc}"}

    workers = min(12, max(1, len(valid_companies)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="report-discovery") as pool:
        discovered = list(pool.map(discover, valid_companies))

    for company_item, documents in zip(valid_companies, discovered, strict=True):
        _, name, code, sector, company_start, company_end = company_item
        if documents.get("status") != "ok":
            blockers.append(f"{code}: {documents.get('reason', 'official reports unavailable')}")
            continue

        ingested: list[dict[str, Any]] = []
        evidence_dir = run_path / "evidence" / "financial_reports"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        ingestion_failures: list[dict[str, Any]] = []
        candidates = list(documents.get("documents", []))

        def ingest(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
            record, error = _ingest_document(
                run_path=run_path, evidence_dir=evidence_dir, company=name, code=code,
                document=document, official_domain=documents.get("domain"),
            )
            return document, record, error

        with ThreadPoolExecutor(
            max_workers=min(5, max(1, len(candidates))), thread_name_prefix="report-ingestion"
        ) as pool:
            ingestion_results = list(pool.map(ingest, candidates))
        for document, record, error in ingestion_results:
            if record is None:
                ingestion_failures.append({
                    "fiscal_year": document.get("fiscal_year"),
                    "url": document.get("url"), "repository": document.get("source"),
                    "error": error,
                })
                continue
            ingested.append(record)

        # A discovered link is not evidence until it can be read. When a primary
        # (exchange) link is dead or a file has moved, recover that exact fiscal
        # year from the other exchange and then the issuer's own website, trying
        # every candidate until one downloads and passes verification.
        satisfied = {int(r["fiscal_year"]) for r in ingested if r.get("fiscal_year")}
        failed_years = {
            int(item["fiscal_year"]) for item in ingestion_failures
            if item.get("fiscal_year") and int(item["fiscal_year"]) not in satisfied
        }
        tried_urls = {str(item.get("url")) for item in ingestion_failures if item.get("url")}
        retry_attempts: list[dict[str, Any]] = []
        for year in sorted(failed_years):
            candidates = _sources.recover_report_candidates(
                name, code=code, year=year, official_domain=documents.get("domain"),
            )
            retry_attempts.append({
                "source": "exchange_and_issuer_recovery", "fiscal_year": year,
                "candidates_found": len(candidates),
            })
            for url in candidates:
                if url in tried_urls:
                    continue
                tried_urls.add(url)
                repository = "bse" if "bseindia.com" in url else (
                    "nse" if "nseindia.com" in url else "issuer_website_search"
                )
                candidate = {
                    "url": url, "fiscal_year": year,
                    "title": f"{name} annual report {year}",
                    "source": repository, "source_tier": 1,
                    "source_type": "issuer_annual_report",
                    "authoritative_repository": True,
                    "official_domain": documents.get("domain"),
                }
                record, error = _ingest_document(
                    run_path=run_path, evidence_dir=evidence_dir, company=name, code=code,
                    document=candidate, official_domain=documents.get("domain"),
                )
                if record is not None:
                    ingested.append(record)
                    break
                ingestion_failures.append({
                    "fiscal_year": year, "url": url,
                    "repository": repository, "error": error,
                })
        distinct_years = {item["fiscal_year"] for item in ingested if item.get("fiscal_year")}
        requested_years = set(documents.get("coverage", {}).get("requested_years") or [])
        minimum = min(5, len(requested_years))
        if len(distinct_years) < minimum:
            blockers.append(
                f"{code}: only {len(distinct_years)} report year(s) could be ingested after "
                "exhausting issuer, NSE/BSE, regulator, and archive fallbacks"
            )
            continue
        pack = factor_pack(sector, code=code)
        if pack.get("status") != "ok":
            blockers.append(f"{code}: sector '{sector}' did not match the two-workbook backbone")
            continue
        records.append({
            "company": name, "code": code, "sector": sector,
            "official_domain": documents.get("domain"),
            "domain_verification": documents.get("domain_verification"),
            "requested_report_span": documents.get("requested_span"),
            "report_coverage": {
                **documents.get("coverage", {}),
                "ingested_years": sorted(distinct_years),
                "unreadable_years": sorted(set(documents.get("coverage", {}).get("found_years") or []) - distinct_years),
            },
            "report_search_attempts": [*documents.get("attempts", []), *retry_attempts],
            "report_ingestion_failures": ingestion_failures,
            "historical_reports": ingested,
            "reports_ingested": True,
            "workbook_factor_pack_loaded": True,
            "matched_sector": pack.get("matched_sector"),
            "analysis_status": "ready_for_constrained_analysis",
        })

    if blockers:
        return {"status": "blocked", "error": "Official-report/backbone preflight failed", "blockers": blockers}

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "ready",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "policy": "official_historical_reports_then_two_workbook_analysis",
        "authoritative_workbooks": _workbook_identity(),
        "companies": records,
    }
    path = run_path / MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**manifest, "manifest_path": str(path)}


def validate_backbone_manifest(run_path: Path, config: dict[str, Any]) -> str | None:
    """Return a blocking reason when the simulation lacks verified research proof."""
    path = run_path / MANIFEST_NAME
    if not path.is_file():
        return (
            f"{MANIFEST_NAME} not found. Call prepare_analysis_backbone for every company "
            "before backtest; official historical reports and both workbooks are mandatory."
        )
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"{MANIFEST_NAME} is unreadable: {exc}"
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("status") != "ready":
        return f"{MANIFEST_NAME} is not a ready schema-v{SCHEMA_VERSION} manifest"
    expected = {(item["filename"], item["sha256"]) for item in _workbook_identity()}
    actual = {
        (item.get("filename"), item.get("sha256"))
        for item in manifest.get("authoritative_workbooks", []) if isinstance(item, dict)
    }
    if actual != expected:
        return "analysis backbone workbook identities do not match the current two authoritative files"
    records = manifest.get("companies") or []
    by_code = {str(item.get("code") or "").upper(): item for item in records if isinstance(item, dict)}
    missing = sorted(_codes(config) - set(by_code))
    if missing:
        return f"official-report/backbone coverage missing for configured codes: {', '.join(missing)}"
    for code, item in by_code.items():
        reports = item.get("historical_reports") or []
        years = {report.get("fiscal_year") for report in reports if report.get("read_status") == "verified"}
        coverage = item.get("report_coverage") or {}
        requested = set(coverage.get("requested_years") or [])
        minimum = min(5, len(requested))
        if len(years) < minimum or not item.get("reports_ingested"):
            return f"{code}: required financial-report evidence was not ingested"
        span = _config_report_span(config)
        manifest_span = item.get("requested_report_span") or {}
        if span and (
            int(manifest_span.get("start_year", span[0] + 1)) > span[0]
            or int(manifest_span.get("end_year", span[1] - 1)) < span[1]
        ):
            return f"{code}: report search did not cover the configured backtest span {span[0]}-{span[1]}"
        attempted = {row.get("source") for row in item.get("report_search_attempts", [])}
        missing_years = set(coverage.get("missing_years") or []) | set(coverage.get("unreadable_years") or [])
        if missing_years and not _required_report_fallbacks(code).issubset(attempted):
            return f"{code}: missing report years were not exhausted through the required fallback sources"
        if not item.get("workbook_factor_pack_loaded") or item.get("analysis_status") != "ready_for_constrained_analysis":
            return f"{code}: two-workbook analysis pack was not completed"
    return None
