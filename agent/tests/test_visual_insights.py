from __future__ import annotations

from pathlib import Path

from src.analysis.visual_insights import build_visual_insights, parse_number


def test_parse_number_preserves_financial_units() -> None:
    parsed = parse_number("Rs 8,257.04 cr")
    assert parsed is not None
    assert parsed.value == 8257.04
    assert parsed.unit == "₹ cr"
    energy = parse_number("2.5 GWh")
    assert energy is not None
    assert energy.unit == "GWh"


def test_markdown_bullets_generate_kpis_and_grouped_chart(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "report.md").write_text(
        """# Company snapshot

- Total income: Rs 8,257.04 cr
- EBITDA: Rs 2,108.25 cr
- PAT: Rs 2,947.83 cr
- ROE: -0.91%
- ROCE: 6.1%
- Filing: https://example.com/documents/2181716/report.pdf
""",
        encoding="utf-8",
    )

    result = build_visual_insights(tmp_path)

    assert len(result["kpis"]) == 5
    financial = next(chart for chart in result["charts"] if chart["title"] == "Financial metrics · cr")
    assert financial["categories"] == ["Total income", "EBITDA", "PAT"]
    assert financial["series"][0]["values"] == [8257.04, 2108.25, 2947.83]
    percentages = next(chart for chart in result["charts"] if chart["title"] == "Key metrics · %")
    assert percentages["series"][0]["values"] == [-0.91, 6.1]


def test_markdown_table_generates_time_series_chart(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "annual.md").write_text(
        """## Annual performance

| Year | Revenue | EBITDA |
| --- | ---: | ---: |
| 2023 | 100 | 20 |
| 2024 | 120 | 28 |
| 2025 | 150 | 39 |
""",
        encoding="utf-8",
    )

    result = build_visual_insights(tmp_path)
    chart = result["charts"][0]

    assert chart["title"] == "Annual performance"
    assert chart["type"] == "line"
    assert chart["categories"] == ["2023", "2024", "2025"]
    assert [series["name"] for series in chart["series"]] == ["Revenue", "EBITDA"]


def test_csv_generates_chart_and_preview_table(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "scores.csv").write_text(
        "factor,score,weight\nQuality,82,30\nGrowth,74,25\nValue,68,20\n",
        encoding="utf-8",
    )

    result = build_visual_insights(tmp_path)

    assert result["charts"][0]["type"] == "bar"
    assert result["tables"][0]["columns"] == ["factor", "score", "weight"]


def test_oversized_and_unsupported_artifacts_are_ignored(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "report.pdf").write_bytes(b"%PDF")
    (artifacts / "huge.md").write_bytes(b"x" * 2_000_001)

    result = build_visual_insights(tmp_path)

    assert result["charts"] == []
    assert result["kpis"] == []
    assert result["sources"] == []


def test_artifact_symlinks_cannot_escape_the_run_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("- Secret balance: Rs 99 cr\n- Secret debt: Rs 42 cr\n", encoding="utf-8")
    artifacts = tmp_path / "run" / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "linked.md").symlink_to(outside)

    result = build_visual_insights(tmp_path / "run")

    assert result["charts"] == []
    assert result["kpis"] == []
