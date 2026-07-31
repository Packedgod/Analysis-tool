"""Tests for the numeric-provenance auditor.

Covers extraction (percent / currency+magnitude / multiples / year exclusion)
and the grounding audit (rounding tolerance, percent-fraction equivalence, and
detection of un-sourced figures).
"""

from __future__ import annotations

import json

from src.agent.grounding_audit import audit_grounding, extract_numeric_claims


class TestExtraction:
    def test_percent_currency_magnitude(self) -> None:
        claims = {c.raw: (c.kind, c.value) for c in extract_numeric_claims("grew 23% to ₹4,500 cr")}
        assert claims["23%"][0] == "percent" and claims["23%"][1] == 23.0
        # ₹4,500 cr -> 4500 * 1e7
        cur = next(v for k, v in claims.items() if "4,500" in k)
        assert cur[0] == "currency" and cur[1] == 4_500 * 1e7

    def test_multiple_and_indian_grouping(self) -> None:
        vals = {c.raw: c.value for c in extract_numeric_claims("trading at 1.5x with ₹4,50,000 in cash")}
        assert vals["1.5x"] == 1.5
        assert any(v == 450000 for v in vals.values())  # 4,50,000 lakh-style grouping

    def test_years_excluded_by_default(self) -> None:
        raws = [c.raw for c in extract_numeric_claims("in 2024 revenue rose")]
        assert "2024" not in raws
        assert "2024" in [c.raw for c in extract_numeric_claims("in 2024", include_years=True)]


class TestAuditGrounding:
    def test_fully_grounded(self) -> None:
        answer = "Revenue grew 23% to ₹4,500 cr."
        sources = ["FY24 revenue was ₹4,500 crore, up 23% YoY."]
        rep = audit_grounding(answer, sources)
        assert rep["n_ungrounded"] == 0
        assert rep["grounding_ratio"] == 1.0

    def test_hallucinated_number_flagged(self) -> None:
        answer = "Revenue grew 23% to ₹4,500 cr, with a net margin of 91%."
        sources = ["FY24 revenue was ₹4,500 crore, up 23% YoY."]
        rep = audit_grounding(answer, sources)
        assert "91%" in rep["ungrounded"]
        assert rep["n_claims"] == 3 and rep["n_grounded"] == 2

    def test_rounding_and_separators_tolerated(self) -> None:
        rep = audit_grounding("value is 4,500", ["the figure 4500 appears here"])
        assert rep["n_ungrounded"] == 0

    def test_percent_fraction_equivalence(self) -> None:
        rep = audit_grounding("margin of 23%", ["ratio recorded as 0.23"])
        assert rep["n_ungrounded"] == 0

    def test_empty_answer_is_trivially_grounded(self) -> None:
        rep = audit_grounding("", ["anything"])
        assert rep["n_claims"] == 0 and rep["grounding_ratio"] == 1.0

    def test_no_sources_flags_everything(self) -> None:
        rep = audit_grounding("EPS was 12.4 and ROE 18%", [])
        assert rep["n_ungrounded"] == rep["n_claims"] == 2

    def test_json_safe(self) -> None:
        rep = audit_grounding("grew 23% to ₹4,500 cr, margin 91%", ["₹4,500 crore, 23%"])
        json.loads(json.dumps(rep))


class TestReportAuditGroundingCommand:
    """The auditor exposed via the report_audit tool's 'grounding' command."""

    def _tool(self):
        from src.tools.report_audit_tool import ReportAuditTool

        return ReportAuditTool()

    def test_grounding_command_flags_unsourced(self) -> None:
        out = json.loads(
            self._tool().execute(
                command="grounding",
                report_text="Revenue grew 23% to ₹4,500 cr, net margin 91%.",
                sources=["FY24 revenue ₹4,500 crore, up 23% YoY."],
            )
        )
        assert out["status"] == "ok"
        assert out["ungrounded"] == ["91%"]

    def test_grounding_command_requires_report_text(self) -> None:
        out = json.loads(self._tool().execute(command="grounding", sources=["x"]))
        assert out["status"] == "error"

    def test_grounding_command_accepts_string_source(self) -> None:
        out = json.loads(
            self._tool().execute(command="grounding", report_text="value 42", sources="the value 42")
        )
        assert out["status"] == "ok" and out["n_ungrounded"] == 0
