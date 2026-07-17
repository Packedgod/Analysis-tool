"""Derive safe, presentation-ready visual insights from run artifacts.

Research runs frequently persist their useful numerical output as Markdown or
CSV instead of backtest-specific ``equity.csv`` files.  This module turns those
artifacts into a small declarative chart payload without executing artifact
content or exposing arbitrary filesystem paths.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


_MAX_ARTIFACT_BYTES = 2_000_000
_MAX_CHARTS = 12
_MAX_KPIS = 18
_MAX_ROWS = 240
_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
_NUMERIC_RE = re.compile(
    r"(?P<prefix>₹|\$|€|£|Rs\.?|INR|USD)?\s*"
    r"(?P<number>[-+]?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<suffix>%|x|bps|crores?|cr|lakhs?|mn|bn|million|billion|MWh|GWh|kWh|GWp?|MW)?",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)]\s+)(?P<label>[^:]{2,100}):\s*(?P<value>.+?)\s*$")
_DATE_LIKE_RE = re.compile(r"^(?:FY\s*)?\d{4}(?:[-/]\d{2,4})?$|^\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?$", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedNumber:
    value: float
    unit: str
    display: str


def _clean_label(value: str) -> str:
    value = re.sub(r"[*_`#]", "", value)
    value = re.sub(r"\s+", " ", value).strip(" :-")
    return value[:120]


def _normalise_unit(prefix: str | None, suffix: str | None) -> str:
    p = (prefix or "").lower().replace(".", "")
    s = (suffix or "").lower()
    currency = ""
    if p in {"₹", "rs", "inr"}:
        currency = "₹"
    elif p in {"$", "usd"}:
        currency = "$"
    elif p in {"€", "£"}:
        currency = prefix or ""
    suffix_map = {
        "crore": "cr", "crores": "cr", "cr": "cr",
        "lakh": "lakh", "lakhs": "lakh",
        "million": "mn", "mn": "mn", "billion": "bn", "bn": "bn",
        "mw": "MW", "gw": "GW", "gwp": "GWp", "mwh": "MWh", "gwh": "GWh", "kwh": "kWh",
        "%": "%", "x": "×", "bps": "bps",
    }
    normalized_suffix = suffix_map.get(s, suffix or "")
    return " ".join(part for part in (currency, normalized_suffix) if part).strip() or "value"


def parse_number(value: Any) -> ParsedNumber | None:
    """Parse the first explicit numeric value and its display unit."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            return None
        return ParsedNumber(number, "value", f"{number:g}")
    text = str(value).strip()
    match = _NUMERIC_RE.search(text)
    if not match:
        return None
    try:
        number = float(match.group("number").replace(",", ""))
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    unit = _normalise_unit(match.group("prefix"), match.group("suffix"))
    display = match.group(0).strip()
    return ParsedNumber(number, unit, display)


def _stable_id(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]


def _is_date_like(values: Iterable[str]) -> bool:
    rows = [str(value).strip() for value in values]
    if len(rows) < 2:
        return False
    return sum(bool(_DATE_LIKE_RE.match(value)) for value in rows) >= max(2, len(rows) // 2)


def _chart_from_rows(title: str, source: str, headers: list[str], rows: list[list[str]]) -> dict[str, Any] | None:
    if len(headers) < 2 or len(rows) < 2:
        return None
    width = len(headers)
    normalized_rows = [(row + [""] * width)[:width] for row in rows[:_MAX_ROWS]]
    category_index = 0
    numeric_columns: list[tuple[int, str, str]] = []
    for index in range(1, width):
        parsed = [parse_number(row[index]) for row in normalized_rows]
        present = [item for item in parsed if item is not None]
        if len(present) < max(2, len(normalized_rows) // 2):
            continue
        units = defaultdict(int)
        for item in present:
            units[item.unit] += 1
        unit = max(units, key=units.get)
        numeric_columns.append((index, _clean_label(headers[index]) or f"Series {index}", unit))
    if not numeric_columns:
        return None
    categories = [_clean_label(row[category_index]) or str(row_index + 1) for row_index, row in enumerate(normalized_rows)]
    chart_type = "line" if _is_date_like(categories) and len(categories) >= 3 else "bar"
    series = []
    for index, name, unit in numeric_columns[:5]:
        values = []
        for row in normalized_rows:
            parsed = parse_number(row[index])
            values.append(parsed.value if parsed else None)
        series.append({"name": name, "unit": unit, "values": values})
    return {
        "id": _stable_id(source, title, "|".join(headers)),
        "title": _clean_label(title) or "Numerical trend",
        "type": chart_type,
        "categories": categories,
        "series": series,
        "source": source,
    }


def _parse_markdown_tables(text: str, source: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lines = text.splitlines()
    charts: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    current_heading = "Report data"
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        heading = re.match(r"^#{1,6}\s+(.+)$", line)
        if heading:
            current_heading = _clean_label(heading.group(1))
            index += 1
            continue
        if line.startswith("|") and index + 1 < len(lines):
            separator = lines[index + 1].strip()
            if separator.startswith("|") and re.fullmatch(r"[|:\-\s]+", separator):
                headers = [_clean_label(cell) for cell in line.strip("|").split("|")]
                rows: list[list[str]] = []
                index += 2
                while index < len(lines) and lines[index].strip().startswith("|"):
                    rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                    index += 1
                if rows:
                    chart = _chart_from_rows(current_heading, source, headers, rows)
                    if chart:
                        charts.append(chart)
                    tables.append({"title": current_heading, "columns": headers, "rows": rows[:30], "source": source})
                continue
        index += 1
    return charts, tables


def _parse_bullet_kpis(text: str, source: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kpis: list[dict[str, Any]] = []
    for line in text.splitlines():
        match = _BULLET_RE.match(line)
        if not match:
            continue
        label = _clean_label(match.group("label"))
        value_text = match.group("value").strip()
        if "://" in value_text or value_text.startswith(("www.", "mailto:")):
            continue
        parsed = parse_number(value_text)
        if not parsed or len(label) < 2:
            continue
        kpis.append({
            "label": label,
            "value": parsed.value,
            "display": value_text[:80],
            "unit": parsed.unit,
            "source": source,
        })
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in kpis:
        groups[item["unit"]].append(item)
    charts = []
    for unit, items in groups.items():
        if len(items) < 2:
            continue
        selected = items[:12]
        if unit.startswith(("₹", "$", "€", "£")):
            scale = unit.split(maxsplit=1)[1] if " " in unit else "currency"
            title = f"Financial metrics · {scale}"
        else:
            title = f"Key metrics · {unit}"
        charts.append({
            "id": _stable_id(source, title, unit),
            "title": title,
            "type": "bar",
            "categories": [item["label"] for item in selected],
            "series": [{"name": unit, "unit": unit, "values": [item["value"] for item in selected]}],
            "source": source,
        })
    return kpis, charts


def _parse_csv(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        rows = list(reader)
    if len(rows) < 3:
        return [], []
    headers = [_clean_label(value) for value in rows[0]]
    data_rows = rows[1:_MAX_ROWS + 1]
    chart = _chart_from_rows(path.stem.replace("_", " ").title(), path.name, headers, data_rows)
    table = {"title": path.stem.replace("_", " ").title(), "columns": headers, "rows": data_rows[:30], "source": path.name}
    return ([chart] if chart else []), [table]


def _parse_json(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) < 2 or not all(isinstance(row, dict) for row in payload[:20]):
        return [], []
    headers = list(dict.fromkeys(key for row in payload[:20] for key in row.keys()))
    rows = [[str(row.get(header, "")) for header in headers] for row in payload[:_MAX_ROWS]]
    chart = _chart_from_rows(path.stem.replace("_", " ").title(), path.name, headers, rows)
    table = {"title": path.stem.replace("_", " ").title(), "columns": headers, "rows": rows[:30], "source": path.name}
    return ([chart] if chart else []), [table]


def build_visual_insights(run_dir: Path) -> dict[str, Any]:
    """Return derived KPI, chart, and table specs for a validated run directory."""
    artifacts_dir = run_dir / "artifacts"
    kpis: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    sources: list[str] = []
    if artifacts_dir.is_dir():
        artifact_root = artifacts_dir.resolve()
        for path in sorted(artifacts_dir.iterdir(), key=lambda item: item.name.lower()):
            resolved = path.resolve()
            if not resolved.is_relative_to(artifact_root) or not path.is_file() or path.stat().st_size > _MAX_ARTIFACT_BYTES:
                continue
            suffix = path.suffix.lower()
            try:
                if suffix in _TEXT_SUFFIXES:
                    text = path.read_text(encoding="utf-8", errors="replace")
                    table_charts, parsed_tables = _parse_markdown_tables(text, path.name)
                    bullet_kpis, bullet_charts = _parse_bullet_kpis(text, path.name)
                    charts.extend(table_charts)
                    charts.extend(bullet_charts)
                    tables.extend(parsed_tables)
                    kpis.extend(bullet_kpis)
                elif suffix == ".csv":
                    parsed_charts, parsed_tables = _parse_csv(path)
                    charts.extend(parsed_charts)
                    tables.extend(parsed_tables)
                elif suffix == ".json":
                    parsed_charts, parsed_tables = _parse_json(path)
                    charts.extend(parsed_charts)
                    tables.extend(parsed_tables)
                else:
                    continue
                sources.append(path.name)
            except (OSError, UnicodeError, ValueError, csv.Error, json.JSONDecodeError):
                continue
    seen = set()
    unique_charts = []
    for chart in charts:
        if chart["id"] in seen:
            continue
        seen.add(chart["id"])
        unique_charts.append(chart)
    return {
        "run_id": run_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "kpis": kpis[:_MAX_KPIS],
        "charts": unique_charts[:_MAX_CHARTS],
        "tables": tables[:8],
        "sources": list(dict.fromkeys(sources)),
    }
