"""Verified public-source ladder and conservative official-issuer discovery."""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from backtest.loaders._http import throttled_get
from src.tools._pit import EvidenceWindow


@dataclass(frozen=True)
class Source:
    name: str
    domains: tuple[str, ...]


@dataclass(frozen=True)
class IssuerArchive:
    domain: str
    pages: tuple[str, ...]
    asset_domains: tuple[str, ...] = ()


SOURCE_LADDER = (
    Source("mint", ("livemint.com",)),
    Source("economic_times", ("economictimes.indiatimes.com",)),
    Source("reuters", ("reuters.com",)),
    Source("rbi", ("rbi.org.in",)),
    Source("sebi", ("sebi.gov.in",)),
    Source("nse", ("nseindia.com",)),
    Source("bse", ("bseindia.com",)),
    Source("rating_agencies", ("icra.in", "careratings.com", "crisil.com")),
    Source("moneycontrol", ("moneycontrol.com",)),
    Source("times_of_india", ("timesofindia.indiatimes.com",)),
    Source("yahoo_finance", ("finance.yahoo.com",)),
    Source("google_finance", ("google.com",)),
)

_AGGREGATORS = {
    "moneycontrol.com", "wikipedia.org", "en.wikipedia.org", "screener.in",
    "trendlyne.com", "marketscreener.com", "bloomberg.com", "reuters.com",
    "finance.yahoo.com", "google.com", "linkedin.com", "annualreports.com",
}
_LEGAL_WORDS = {"ltd", "limited", "inc", "incorporated", "corp", "corporation", "plc", "llc", "the"}
_REPORT_SEARCH_GATE = threading.BoundedSemaphore(1)
_ISSUER_CRAWL_GATE = threading.BoundedSemaphore(8)
_REPORT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "report_discovery_cache"
_SEARCH_COOLDOWN_UNTIL: dict[str, float] = {}
_REPORT_CACHE_LOCK = threading.RLock()


def _discovery_cache_path(code: str) -> Path:
    safe = re.sub(r"[^A-Z0-9]+", "_", code.strip().upper()) or "UNKNOWN"
    return _REPORT_CACHE_DIR / f"{safe}.json"


def _read_discovery_cache(code: str, company: str) -> list[dict[str, Any]]:
    path = _discovery_cache_path(code)
    try:
        with _REPORT_CACHE_LOCK:
            payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("code") != code.strip().upper():
            return []
        if _name_tokens(str(payload.get("company") or "")) != _name_tokens(company):
            return []
        rows = payload.get("documents") or []
        return [dict(row) for row in rows if isinstance(row, dict) and row.get("url")]
    except (OSError, ValueError, TypeError):
        return []


def _write_discovery_cache(code: str, company: str, documents: list[dict[str, Any]]) -> None:
    if not code:
        return
    path = _discovery_cache_path(code)
    payload = {
        "schema_version": 1, "code": code.strip().upper(), "company": company,
        "updated_at": datetime.utcnow().isoformat() + "Z", "documents": documents,
    }
    try:
        with _REPORT_CACHE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f".{threading.get_ident()}.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
    except OSError:
        pass


def mark_cached_document_verified(code: str, company: str, url: str, digest: str) -> None:
    """Promote a discovered URL only after extracted content passes issuer checks."""
    with _REPORT_CACHE_LOCK:
        rows = _read_discovery_cache(code, company)
        changed = False
        for row in rows:
            if str(row.get("url") or "") == url:
                row["content_verified"] = True
                row["content_sha256"] = digest
                changed = True
        if changed:
            _write_discovery_cache(code, company, rows)


def reject_cached_document(code: str, company: str, url: str) -> None:
    """Remove unreadable or wrong-issuer candidates so retries do not get poisoned."""
    with _REPORT_CACHE_LOCK:
        rows = _read_discovery_cache(code, company)
        retained = [row for row in rows if str(row.get("url") or "") != url]
        if len(retained) != len(rows):
            _write_discovery_cache(code, company, retained)

# Ticker-bound issuer archives are the deterministic first path. Search engines
# are discovery fallbacks, never the identity authority for these issuers.
_ISSUER_ARCHIVES: dict[str, IssuerArchive] = {
    "LT.NS": IssuerArchive("larsentoubro.com", (
        "https://investors.larsentoubro.com/Annual-Reports-Archives.aspx",
        "https://annualreview.larsentoubro.com/download-pdf.html",
    )),
    "HDFCBANK.NS": IssuerArchive("hdfcbank.com", (
        "https://www.hdfcbank.com/personal/about-us/investor-relations/annual-reports",
    )),
    "ITC.NS": IssuerArchive("itcportal.com", (
        "https://itcportal.com/investors/itc-reports-and-accounts.html",
    )),
    "DIVISLAB.NS": IssuerArchive("divislabs.com", (
        "https://www.divislabs.com/investor-relations/reports-and-filings/annual-reporting/",
    )),
    "JSWSTEEL.NS": IssuerArchive("jswsteel.in", (
        "https://www.jswsteel.in/investors/annual-reports",
    ), ("jsw.in",)),
    "TATAPOWER.NS": IssuerArchive("tatapower.com", (
        "https://www.tatapower.com/investor-relations/annual-reports",
    )),
    "ASIANPAINT.NS": IssuerArchive("asianpaints.com", (
        "https://www.asianpaints.com/more/investors.html",
        "https://www.asianpaints.com/content/annualreport/annual-report-25-26.html",
    ), ("static.asianpaints.com",)),
    "MARUTI.NS": IssuerArchive("marutisuzuki.com", (
        "https://www.marutisuzuki.com/corporate/investors",
    ), ("azurefd.net",)),
    "HINDPETRO.NS": IssuerArchive("hindustanpetroleum.com", (
        "https://www.hindustanpetroleum.com/Annual%20Reports",
    )),
    "IRFC.NS": IssuerArchive("irfc.co.in", (
        "https://irfc.co.in/",
    )),
    "INFY.NS": IssuerArchive("infosys.com", (
        "https://www.infosys.com/investors/reports-filings/annual-report.html",
    )),
}


def _ddgs():
    from ddgs import DDGS
    return DDGS


def _ddgs_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """Search via DuckDuckGo, a free engine that answers automated queries.

    This is the primary report-discovery backend because Google/Brave HTML
    scraping is routinely served consent walls and CAPTCHAs, which silently
    starved the issuer-website fallback of results.
    """
    from ddgs import DDGS  # noqa: PLC0415

    rows: list[dict[str, Any]] = []
    with DDGS() as engine:
        results = engine.text(query, max_results=max_results) or []
    for result in results:
        href = str(result.get("href") or result.get("url") or "")
        if not href.startswith("http"):
            continue
        rows.append({
            "href": href, "title": result.get("title") or "",
            "body": result.get("body") or result.get("description") or "",
            "engine": "duckduckgo",
        })
    if not rows:
        raise RuntimeError("DuckDuckGo returned no parseable search results")
    return rows


def _google_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """Search Google HTML with a browser-shaped, throttled request."""
    from bs4 import BeautifulSoup  # noqa: PLC0415

    response = throttled_get(
        "https://www.google.com/search", host_key="report-search-google",
        min_interval=0.8, params={"q": query, "num": min(max_results, 50)},
        headers={"Accept-Language": "en-IN,en;q=0.9"}, timeout=20.0,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    rows: list[dict[str, Any]] = []
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "")
        if href.startswith("/url?"):
            params = parse_qs(urlsplit(href).query)
            href = (params.get("q") or params.get("url") or [""])[0]
        href = unquote(href)
        host = _host(href)
        if not href.startswith("http") or not host or host.endswith("google.com"):
            continue
        title = anchor.get_text(" ", strip=True)
        if not title:
            continue
        container = anchor.find_parent(["div", "article"])
        body = container.get_text(" ", strip=True) if container else title
        rows.append({"href": href, "title": title, "body": body, "engine": "google"})
        if len(rows) >= max_results:
            break
    if not rows:
        raise RuntimeError("Google returned no parseable search results")
    return rows


def _brave_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """Search Brave HTML when Google is unavailable or yields no results."""
    from bs4 import BeautifulSoup  # noqa: PLC0415

    response = throttled_get(
        "https://search.brave.com/search", host_key="report-search-brave",
        min_interval=0.8, params={"q": query, "source": "web"},
        headers={"Accept-Language": "en-IN,en;q=0.9"}, timeout=20.0,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    rows: list[dict[str, Any]] = []
    for anchor in soup.select("a[href]"):
        href = unquote(str(anchor.get("href") or ""))
        host = _host(href)
        if not href.startswith("http") or not host or host.endswith("brave.com"):
            continue
        title = anchor.get_text(" ", strip=True)
        if not title:
            continue
        container = anchor.find_parent(["div", "article"])
        body = container.get_text(" ", strip=True) if container else title
        rows.append({"href": href, "title": title, "body": body, "engine": "brave"})
        if len(rows) >= max_results:
            break
    if not rows:
        raise RuntimeError("Brave returned no parseable search results")
    return rows


def _search_text(query: str, max_results: int = 20) -> list[dict[str, Any]]:
    """Search DuckDuckGo first, then Google and Brave as automatic fallbacks."""
    errors: list[str] = []
    engines = (
        ("duckduckgo", _ddgs_search),
        ("google", _google_search),
        ("brave", _brave_search),
    )
    with _REPORT_SEARCH_GATE:
        for name, search in engines:
            if _SEARCH_COOLDOWN_UNTIL.get(name, 0.0) > time.monotonic():
                errors.append(f"{name}: temporarily rate-limited")
                continue
            try:
                return search(query, max_results)
            except Exception as exc:  # noqa: BLE001 - move to next configured engine
                errors.append(f"{name}: {exc}")
                blob = str(exc).casefold()
                if "429" in blob or "too many requests" in blob or "ratelimit" in blob:
                    _SEARCH_COOLDOWN_UNTIL[name] = time.monotonic() + 300.0
    raise RuntimeError("; ".join(errors))


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _on_domain(url: str, domain: str) -> bool:
    host = _host(url)
    domain = domain.lower().removeprefix("www.")
    return host == domain or host.endswith("." + domain)


def _is_aggregator(host: str) -> bool:
    host = host.lower().removeprefix("www.")
    return any(host == item or host.endswith("." + item) for item in _AGGREGATORS)


def _name_tokens(company: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", company.casefold())
    return [word for word in words if word not in _LEGAL_WORDS and len(word) > 1]


def _verify_domain(domain: str, tokens: list[str], candidate_url: str = "") -> tuple[bool, str]:
    """Verify issuer ownership from registered domain/title, or refuse."""
    domain = domain.lower().removeprefix("www.")
    if not tokens or _is_aggregator(domain):
        return False, "aggregator or insufficient issuer identity"
    compact_domain = re.sub(r"[^a-z0-9]", "", domain.split(".", 1)[0])
    token_domain_match = all(token in compact_domain for token in tokens)
    try:
        response = throttled_get(f"https://{domain}", host_key=f"issuer:{domain}", min_interval=0.2, timeout=12.0)
    except Exception:
        return False, "issuer site unreachable"
    title_match = False
    if response.status_code < 400:
        title = " ".join(re.findall(r"<title[^>]*>(.*?)</title>", response.text, flags=re.I | re.S)).casefold()
        title_tokens = set(re.findall(r"[a-z0-9]+", title))
        title_match = all(token in title_tokens for token in tokens)
        return (title_match, "site title confirms issuer identity" if title_match else "site identity mismatch")
    if response.status_code in {401, 403, 429} and token_domain_match:
        return True, "registered domain spells complete issuer identity; site blocks automated fetch"
    return False, f"issuer site returned HTTP {response.status_code}"


def _document_year(url: str, title: str) -> int | None:
    identity = f"{url} {title}"
    match = re.search(r"((?:19|20)\d{2})(?:\s*[-_/]\s*(\d{2}|(?:19|20)\d{2}))?", identity)
    if not match:
        return None
    start = int(match.group(1))
    if not match.group(2):
        return start
    suffix = match.group(2)
    end = int(suffix) if len(suffix) == 4 else (start // 100) * 100 + int(suffix)
    if end < start:
        end += 100
    return end if end - start <= 1 else start


def _looks_like_full_report(label: str, url: str) -> bool:
    identity = re.sub(r"[^a-z0-9]+", " ", f"{label} {unquote(url)}".casefold())
    rejected = (
        "subsidiary", "secretarial", "annual return", "csr", "brsr",
        "governance report", "agm notice", "notice of", "sustainability report",
        "quarterly", "transcript", "presentation", "chairman address",
        "management discussion", "financial results", "earnings release",
    )
    if any(term in identity for term in rejected):
        return False
    return any(term in identity for term in (
        "annual report", "integrated report", "report and accounts",
        "report accounts",
    ))


def _link_target(anchor: Any, page_url: str) -> str:
    """Resolve ordinary and JavaScript/data-attribute download links."""
    candidates = [
        anchor.get("href"), anchor.get("data-href"), anchor.get("data-url"),
        anchor.get("data-download"), anchor.get("data-file"), anchor.get("onclick"),
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        match = re.search(r"https?://[^'\"\s)]+|(?:/|\.\.?/)[^'\"\s)]+", value)
        target = match.group(0) if match else value
        if target and target not in {"#", "javascript:void(0)", "javascript:;"}:
            return urljoin(page_url, target)
    return ""


def _is_document_or_page(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return not path.endswith((
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
        ".css", ".js", ".woff", ".woff2", ".ttf", ".mp4", ".mp3",
    ))


@lru_cache(maxsize=4096)
def _archive_page_links(page_url: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Extract contextual links from an issuer archive using direct + reader views."""
    from bs4 import BeautifulSoup  # noqa: PLC0415

    links: list[tuple[str, str]] = []
    errors: list[str] = []
    bodies: list[tuple[str, str]] = []
    try:
        response = throttled_get(
            page_url, host_key=f"issuer-archive:{_host(page_url)}",
            min_interval=0.3, timeout=25.0,
        )
        response.raise_for_status()
        bodies.append(("html", response.text))
    except Exception as exc:
        errors.append(f"direct: {exc}")
    try:
        reader_url = f"https://r.jina.ai/{page_url}"
        response = throttled_get(
            reader_url, host_key="issuer-archive-reader", min_interval=0.4,
            headers={"Accept": "text/markdown", "x-no-cache": "true"}, timeout=30.0,
        )
        response.raise_for_status()
        bodies.append(("markdown", response.text))
    except Exception as exc:
        errors.append(f"reader: {exc}")

    for kind, body in bodies:
        if kind == "html":
            soup = BeautifulSoup(body, "html.parser")
            for anchor in soup.select("a, [data-href], [data-url], [data-download], [data-file]"):
                href = _link_target(anchor, page_url)
                if not href or not _is_document_or_page(href):
                    continue
                context = anchor.get_text(" ", strip=True)
                node = anchor
                if _document_year(href, context) is None or not _looks_like_full_report(context, href):
                    for _ in range(4):
                        node = node.parent
                        if node is None:
                            break
                        candidate = node.get_text(" ", strip=True)
                        if len(candidate) <= 350:
                            context = candidate
                        if _document_year(href, context) is not None and _looks_like_full_report(context, href):
                            break
                links.append((href, context))
        else:
            for match in re.finditer(r"https?://[^\s<>()\]\[\"']+", body):
                href = match.group(0).rstrip(".,;:")
                if not _is_document_or_page(href):
                    continue
                start = max(0, match.start() - 220)
                end = min(len(body), match.end() + 220)
                context = re.sub(r"\s+", " ", body[start:end])
                links.append((href, context))
    return links, errors


def _issuer_archive_rows(
    code: str, requested_years: set[int], *, official_domain: str | None = None,
    seed_pages: tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Crawl ticker-bound investor archives before invoking a search engine."""
    archive = _ISSUER_ARCHIVES.get(code.strip().upper())
    domain = archive.domain if archive else official_domain
    if not domain:
        return [], []
    allowed = (domain, *(archive.asset_domains if archive else ()))
    initial_pages = list(dict.fromkeys([
        *(archive.pages if archive else ()), *seed_pages,
        f"https://{domain}/investors", f"https://{domain}/investor-relations",
        f"https://{domain}/annual-reports", f"https://{domain}/investors/annual-reports",
    ]))
    rows: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    seen: set[str] = set()
    queue = list(initial_pages)
    crawled: set[str] = set()
    while queue and len(crawled) < 16 and requested_years - {
        _document_year(str(row.get("url") or ""), str(row.get("title") or "")) for row in rows
    }:
        page = queue.pop(0)
        if page in crawled:
            continue
        crawled.add(page)
        with _ISSUER_CRAWL_GATE:
            links, errors = _archive_page_links(page)
        accepted = 0
        for href, context in links:
            if not any(_on_domain(href, item) for item in allowed):
                continue
            year = _document_year(href, context)
            if year in requested_years and href not in seen and _looks_like_full_report(context, href):
                seen.add(href)
                rows.append({
                    "title": context[:500], "url": href, "date": None,
                    "snippet": context[:1000], "engine": "issuer_archive_crawl",
                })
                accepted += 1
            path = urlsplit(href).path.casefold()
            crawl_hint = re.search(r"invest|annual|report|financial|shareholder", f"{path} {context}".casefold())
            if (
                crawl_hint and href not in crawled and href not in queue
                and not path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx"))
                and len(queue) < 40
            ):
                queue.append(href)
        # A year-specific report page can itself be the readable report.
        page_year = _document_year(page, page)
        if page_year in requested_years and page not in seen and _looks_like_full_report(page, page):
            rows.append({"title": page, "url": page, "date": None, "snippet": page, "engine": "issuer_archive_seed"})
            seen.add(page)
            accepted += 1
        attempts.append({"page": page, "accepted": accepted, "errors": errors})
    return rows, attempts


def _result_matches_issuer(item: dict[str, Any], company: str, code: str) -> bool:
    """Reject search hits whose title/URL identifies a different issuer."""
    identity = f"{item.get('title') or ''} {unquote(str(item.get('url') or ''))}".casefold()
    compact = re.sub(r"[^a-z0-9]+", " ", identity)
    tokens = _name_tokens(company)
    bare = code.rsplit(".", 1)[0].casefold()
    ticker_match = len(bare) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(bare)}(?![a-z0-9])", compact)
    company_match = bool(tokens) and all(re.search(rf"\b{re.escape(token)}\b", compact) for token in tokens)
    return bool(ticker_match or company_match)


def _normalize_result(row: dict[str, Any], domain: str) -> dict[str, Any] | None:
    url = str(row.get("url") or row.get("href") or "").strip()
    if not url or not _on_domain(url, domain):
        return None
    return {
        "title": row.get("title"), "url": url,
        "date": row.get("date"), "snippet": row.get("body") or row.get("description"),
    }


def _in_window(item: dict[str, Any], window: EvidenceWindow) -> bool:
    value = item.get("date")
    if not value:
        return False
    try:
        found = datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return False
    return window.start <= found <= window.end


def search_ladder(query: str, window: EvidenceWindow, *, sweep: bool = False) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    collected: list[dict[str, Any]] = []
    for source in SOURCE_LADDER:
        rung: list[dict[str, Any]] = []
        attempt: dict[str, Any] = {"source": source.name}
        try:
            with _ddgs()() as search:
                for domain in source.domains:
                    rows = search.news(f"{query} site:{domain}", max_results=12) or []
                    rung.extend(item for row in rows if (item := _normalize_result(row, domain)) and _in_window(item, window))
        except Exception as exc:
            attempt["error"] = str(exc)
        attempt["count"] = len(rung)
        attempts.append(attempt)
        if rung:
            collected.extend({**item, "source": source.name} for item in rung)
            if not sweep:
                return {"status": "ok", "source": source.name, "results": rung, "ladder": attempts}
    if collected:
        return {"status": "ok", "source": "sweep", "results": collected, "ladder": attempts}
    return {"status": "unavailable", "reason": f"No verified evidence in {window.start}..{window.end}", "ladder": attempts}


def resolve_official_domain(company: str, code: str = "") -> dict[str, Any]:
    archive = _ISSUER_ARCHIVES.get(code.strip().upper())
    if archive is not None:
        return {
            "status": "ok", "company": company, "domain": archive.domain,
            "url": f"https://{archive.domain}",
            "verification": "ticker-bound issuer archive registry",
        }
    for cached in _read_discovery_cache(code, company):
        domain = str(cached.get("official_domain") or "").strip()
        if domain and not _is_aggregator(domain):
            return {
                "status": "ok", "company": company, "domain": domain,
                "url": f"https://{domain}",
                "verification": "persistent issuer/report index",
            }
    tokens = _name_tokens(company)
    candidates: list[tuple[str, str]] = []
    try:
        rows = _search_text(f'"{company}" official website investor relations', max_results=12)
        for row in rows:
            url = str(row.get("href") or row.get("url") or "")
            host = _host(url)
            if host and not _is_aggregator(host) and host not in {item[0] for item in candidates}:
                candidates.append((host, url))
    except Exception as exc:
        return {"status": "unavailable", "reason": f"Google/Brave official-domain search failed: {exc}"}
    for host, url in candidates:
        ok, reason = _verify_domain(host, tokens, url)
        if ok:
            return {
                "status": "ok", "company": company, "domain": host,
                "url": f"https://{host}", "investor_url": url, "verification": reason,
            }
    return {"status": "unavailable", "reason": "no candidate passed issuer-identity verification"}


def _report_sources(code: str, official_domain: str | None) -> list[Source]:
    """Return the strict report fallback order for a resolved listing."""
    sources: list[Source] = []
    if official_domain:
        sources.append(Source("issuer_website", (official_domain,)))
    upper = code.strip().upper()
    if upper.endswith(".NS"):
        sources.extend((
            Source("nse", ("nseindia.com", "nsearchives.nseindia.com")),
            Source("bse", ("bseindia.com",)),
            Source("sebi", ("sebi.gov.in",)),
            Source("moneycontrol", ("moneycontrol.com",)),
        ))
    elif upper.endswith(".BO"):
        sources.extend((
            Source("bse", ("bseindia.com",)),
            Source("nse", ("nseindia.com", "nsearchives.nseindia.com")),
            Source("sebi", ("sebi.gov.in",)),
            Source("moneycontrol", ("moneycontrol.com",)),
        ))
    elif upper.endswith(".US"):
        sources.append(Source("sec_edgar", ("sec.gov",)))
    elif upper.endswith(".HK"):
        sources.append(Source("hkex", ("hkexnews.hk", "hkex.com.hk")))
    elif upper.endswith(".SH"):
        sources.extend((
            Source("sse", ("sse.com.cn",)),
            Source("cninfo", ("cninfo.com.cn",)),
        ))
    elif upper.endswith((".SZ", ".BJ")):
        sources.extend((
            Source("cninfo", ("cninfo.com.cn",)),
            Source("szse_or_bse_cn", ("szse.cn", "bse.cn")),
        ))
    else:
        sources.extend((
            Source("nse", ("nseindia.com", "nsearchives.nseindia.com")),
            Source("bse", ("bseindia.com",)),
            Source("sebi", ("sebi.gov.in",)),
            Source("moneycontrol", ("moneycontrol.com",)),
        ))
    sources.append(Source("annualreports_archive", ("annualreports.com",)))
    return sources


def _search_report_rows(
    *, company: str, code: str, source: Source,
    start_year: int, end_year: int, missing_years: set[int],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Search a source broadly, then issue focused queries for remaining years."""
    found: list[dict[str, Any]] = []
    queries: list[str] = []
    bare_code = code.rsplit(".", 1)[0]
    for domain in source.domains:
        broad = (
            f'site:{domain} "{company}" {bare_code} '
            f'("annual report" OR "integrated report" OR "financial statements") '
            f'{start_year}..{end_year} filetype:pdf'
        )
        queries.append(broad)
        rows = _search_text(broad, max_results=min(50, max(15, len(missing_years) * 4)))
        for row in rows:
            item = _normalize_result(row, domain)
            if item and (source.name == "issuer_website" or _result_matches_issuer(item, company, code)):
                item["search_engine"] = row.get("engine")
                found.append(item)

        years_seen = {
            year for item in found
            if (year := _document_year(item["url"], str(item.get("title") or ""))) is not None
        }
        for year in sorted(missing_years - years_seen, reverse=True):
            focused = (
                f'site:{domain} "{company}" {bare_code} "annual report" '
                f'("{year}" OR "{year}-{str(year + 1)[-2:]}") filetype:pdf'
            )
            queries.append(focused)
            rows = _search_text(focused, max_results=8)
            for row in rows:
                item = _normalize_result(row, domain)
                if item and (source.name == "issuer_website" or _result_matches_issuer(item, company, code)):
                    item["search_engine"] = row.get("engine")
                    found.append(item)
    return found, queries


_SEARCH_JUNK_HOSTS = (
    "scribd.com", "youtube.com", "fliphtml5.com", "slideshare.net",
    "companiesmarketcap.com", "investing.com", "researchgate.net",
)
_REPORT_URL_HINTS = (
    "annualrep", "annual-report", "annual_report", "annualreport",
    "integratedreport", "integrated-report", "integrated_report",
    "ir-20", "ir+20", "ir_20", "/ir/", "report-and-accounts",
)
_NON_REPORT_URL_HINTS = (
    "ascr", "secretarial", "compliance", "brsr", "csr", "policy", "notice",
    "agm", "circular", "annexure", "governance", "transcript", "presentation",
    "postal-ballot", "outcome", "intimation", "newspaper",
)


def _candidate_rank(url: str, official_domain: str | None) -> int:
    """Order search candidates so full annual reports are tried before ancillary
    filings (compliance certificates, BRSR, notices) that lack financials."""
    low = url.casefold()
    score = 0
    if official_domain and _on_domain(url, official_domain):
        score -= 2
    if any(hint in low for hint in _REPORT_URL_HINTS):
        score -= 3
    if any(hint in low for hint in _NON_REPORT_URL_HINTS):
        score += 5
    return score


def search_report_candidates(
    company: str, *, code: str = "", year: int, official_domain: str | None = None,
    max_urls: int = 16,
) -> list[str]:
    """Find candidate annual-report PDFs for one fiscal year via web search.

    Used to recover a year whose primary (exchange) link is dead: it queries the
    issuer's own website first, then the open web, and returns an ordered list of
    PDF URLs (official domain first). Every candidate is still downloaded and
    identity-verified by the ingestion layer, so this only has to be plausible,
    not authoritative.
    """
    previous = year - 1
    short = str(year)[-2:]
    bare = code.rsplit(".", 1)[0]
    queries: list[str] = []
    if official_domain:
        queries += [
            f'site:{official_domain} annual report {previous}-{short} filetype:pdf',
            f'site:{official_domain} annual report {year} filetype:pdf',
            f'site:{official_domain} integrated report {year} filetype:pdf',
        ]
    queries += [
        f'"{company}" annual report {previous}-{short} filetype:pdf',
        f'"{company}" annual report {year} filetype:pdf',
        f'{company} {bare} integrated annual report {year} pdf',
    ]

    found: list[str] = []
    seen: set[str] = set()
    for query in queries:
        try:
            rows = _search_text(query, max_results=8)
        except Exception:  # noqa: BLE001 - a dry engine is not fatal here
            continue
        for row in rows:
            url = str(row.get("href") or row.get("url") or "").strip()
            low = url.casefold()
            if not url.startswith("http") or ".pdf" not in low or url in seen:
                continue
            host = _host(url)
            if _is_aggregator(host) or any(junk in host for junk in _SEARCH_JUNK_HOSTS):
                continue
            title = str(row.get("title") or "")
            # Require the URL/title to resolve to exactly this fiscal year so a
            # neighbouring year's report is never mislabelled as evidence.
            if _document_year(url, title) == year:
                seen.add(url)
                found.append(url)
    # Full annual reports first, ancillary filings last; download-time checks
    # still reject anything without real financial statements.
    found.sort(key=lambda url: _candidate_rank(url, official_domain))
    return found[:max_urls]


def recover_report_candidates(
    company: str, *, code: str = "", year: int, official_domain: str | None = None,
) -> list[str]:
    """Ordered recovery URLs for one fiscal year when its primary link failed.

    The other exchange is authoritative and tried first, then any alternate
    exchange links, then the issuer-website web search. Callers try each in turn
    and keep the first that downloads and passes verification.
    """
    from src.tools._exchange_reports import bse_annual_reports, nse_annual_reports  # noqa: PLC0415

    urls: list[str] = []
    for loader in (bse_annual_reports, nse_annual_reports):
        try:
            for row in loader(code):
                if int(row.get("fiscal_year") or 0) == year and row.get("url"):
                    urls.append(str(row["url"]))
        except Exception:  # noqa: BLE001 - a dry exchange is not fatal
            continue
    urls.extend(search_report_candidates(
        company, code=code, year=year, official_domain=official_domain,
    ))
    return list(dict.fromkeys(urls))


def company_documents(
    company: str, *, code: str = "", history_years: int = 5,
    start_year: int | None = None, end_year: int | None = None,
    exclude_sources: set[str] | None = None,
) -> dict[str, Any]:
    """Search issuer-first for annual reports across an exact fiscal-year span.

    Missing years are retried, in order, against NSE/BSE, SEBI, Moneycontrol,
    and AnnualReports. The returned attempt ledger proves that a partial result
    is exhausted rather than silently incomplete.
    """
    if end_year is None:
        end_year = date.today().year - 1
    if start_year is None:
        start_year = end_year - max(5, int(history_years)) + 1
    start_year, end_year = int(start_year), int(end_year)
    if start_year > end_year:
        start_year, end_year = end_year, start_year
    if end_year - start_year < 4:
        start_year = end_year - 4
    if end_year - start_year > 60:
        start_year = end_year - 60
    requested = set(range(start_year, end_year + 1))

    resolved = resolve_official_domain(company, code)
    official_domain = resolved.get("domain") if resolved.get("status") == "ok" else None
    selected_by_year: dict[int, dict[str, Any]] = {}
    attempts: list[dict[str, Any]] = []

    excluded = exclude_sources or set()
    cached_rows = _read_discovery_cache(code, company)
    for item in cached_rows:
        year = int(item.get("fiscal_year") or 0)
        if year in requested and str(item.get("source") or "") not in excluded:
            selected_by_year[year] = {**item, "cache_hit": True}
    attempts.append({
        "source": "persistent_report_index", "requested_missing_years": sorted(requested),
        "accepted": len(selected_by_year), "cache_hit": bool(selected_by_year),
    })

    # Authoritative structured exchange index. NSE publishes direct annual-report
    # links for every listed symbol, so this deterministically covers Indian
    # listings that JavaScript issuer pages and search engines cannot.
    if "nse" not in excluded and requested - set(selected_by_year):
        from src.tools._exchange_reports import nse_annual_reports  # noqa: PLC0415

        attempt: dict[str, Any] = {
            "source": "nse", "method": "nse_annual_reports_api",
            "requested_missing_years": sorted(requested - set(selected_by_year)),
        }
        try:
            accepted = 0
            for row in nse_annual_reports(code):
                year = int(row.get("fiscal_year") or 0)
                if year not in requested or year in selected_by_year:
                    continue
                selected_by_year[year] = {
                    "title": row.get("title"), "url": row.get("url"), "date": None,
                    "snippet": row.get("title"), "engine": "nse_annual_reports_api",
                    "fiscal_year": year, "source": "nse", "source_tier": 1,
                    "source_type": "exchange_annual_report",
                    "authoritative_repository": True, "official_domain": official_domain,
                }
                accepted += 1
            attempt["accepted"] = accepted
        except Exception as exc:  # noqa: BLE001 - fall through to other sources
            attempt["error"] = str(exc)
        attempts.append(attempt)

    # BSE is the second authoritative exchange index and backs NSE up for any
    # year NSE does not list. (A year NSE lists but whose link is dead is
    # recovered later, at ingestion time, via recover_report_candidates.)
    if "bse" not in excluded and requested - set(selected_by_year):
        from src.tools._exchange_reports import bse_annual_reports  # noqa: PLC0415

        attempt = {
            "source": "bse", "method": "bse_annual_reports_api",
            "requested_missing_years": sorted(requested - set(selected_by_year)),
        }
        try:
            accepted = 0
            for row in bse_annual_reports(code):
                year = int(row.get("fiscal_year") or 0)
                if year not in requested or year in selected_by_year:
                    continue
                selected_by_year[year] = {
                    "title": row.get("title"), "url": row.get("url"), "date": None,
                    "snippet": row.get("title"), "engine": "bse_annual_reports_api",
                    "fiscal_year": year, "source": "bse", "source_tier": 1,
                    "source_type": "exchange_annual_report",
                    "authoritative_repository": True, "official_domain": official_domain,
                }
                accepted += 1
            attempt["accepted"] = accepted
        except Exception as exc:  # noqa: BLE001 - fall through to other sources
            attempt["error"] = str(exc)
        attempts.append(attempt)

    archive = _ISSUER_ARCHIVES.get(code.strip().upper())
    seed_pages = tuple(
        value for value in (resolved.get("investor_url"), resolved.get("url"))
        if isinstance(value, str) and value.startswith("http")
    )
    if "issuer_website" not in excluded and requested - set(selected_by_year):
        archive_rows, archive_attempts = _issuer_archive_rows(
            code, requested - set(selected_by_year), official_domain=official_domain,
            seed_pages=seed_pages,
        )
        accepted = 0
        for item in archive_rows:
            year = _document_year(str(item.get("url") or ""), str(item.get("title") or ""))
            if year not in requested or year in selected_by_year:
                continue
            item.update({
                "fiscal_year": year, "source": "issuer_website", "source_tier": 1,
                "source_type": "issuer_annual_report", "authoritative_repository": True,
                "official_domain": official_domain,
            })
            selected_by_year[year] = item
            accepted += 1
        attempts.append({
            "source": "issuer_website", "method": "ticker_bound_archive_crawl",
            "search_engine": None, "requested_missing_years": sorted(requested),
            "pages": archive_attempts, "accepted": accepted,
            "registry_seeded": archive is not None,
        })

    for tier, source in enumerate(_report_sources(code, official_domain), start=1):
        if source.name in excluded:
            continue
        missing = requested - set(selected_by_year)
        if not missing:
            break
        attempt: dict[str, Any] = {
            "source": source.name, "domains": list(source.domains),
            "requested_missing_years": sorted(missing), "queries": [],
            "search_engine": "google_then_brave",
        }
        try:
            rows, queries = _search_report_rows(
                company=company, code=code, source=source,
                start_year=start_year, end_year=end_year, missing_years=missing,
            )
            attempt["queries"] = queries
            accepted = 0
            for item in rows:
                year = _document_year(item["url"], str(item.get("title") or ""))
                if year not in missing or year in selected_by_year:
                    continue
                item.update({
                    "fiscal_year": year,
                    "source": source.name,
                    "source_tier": tier,
                    "source_type": "issuer_annual_report" if source.name == "issuer_website" else "fallback_annual_report",
                    "authoritative_repository": source.name in {
                        "issuer_website", "nse", "bse", "sebi", "sec_edgar",
                        "hkex", "sse", "cninfo", "szse_or_bse_cn",
                    },
                    "official_domain": official_domain,
                })
                selected_by_year[year] = item
                accepted += 1
            attempt["accepted"] = accepted
        except Exception as exc:
            attempt["error"] = str(exc)
        attempts.append(attempt)

    documents = sorted(selected_by_year.values(), key=lambda item: item["fiscal_year"], reverse=True)
    if documents:
        merged = {int(item.get("fiscal_year") or 0): item for item in cached_rows}
        merged.update({int(item["fiscal_year"]): item for item in documents})
        _write_discovery_cache(code, company, sorted(merged.values(), key=lambda row: int(row.get("fiscal_year") or 0), reverse=True))
    missing_years = sorted(requested - set(selected_by_year))
    base = {
        "company": company,
        "code": code,
        "domain": official_domain,
        "domain_verification": resolved.get("verification"),
        "official_domain_status": resolved.get("status"),
        "official_domain_reason": resolved.get("reason"),
        "requested_span": {"start_year": start_year, "end_year": end_year},
        "coverage": {
            "requested_years": sorted(requested),
            "found_years": sorted(selected_by_year),
            "missing_years": missing_years,
            "status": "complete" if not missing_years else ("partial" if documents else "unavailable"),
        },
        "attempts": attempts,
    }
    if not documents:
        return {**base, "status": "unavailable", "reason": "no annual reports found after exhausting issuer, exchange, regulator, and archive sources"}
    return {**base, "status": "ok", "documents": documents}
