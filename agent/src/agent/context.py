"""ContextBuilder: builds LLM message context for the ReAct AgentLoop."""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.agent.memory import WorkspaceMemory
from src.agent.skills import SkillsLoader
from src.agent.tools import ToolRegistry

if TYPE_CHECKING:
    from src.memory.persistent import PersistentMemory

logger = logging.getLogger(__name__)

# Post-backtest attribution thresholds (Sharpe/MaxDD bands, â‰¥60-day OLS window,
# holding-period buckets, pâ‰¤0.05 significance) follow standard industry and
# statistical conventions; the routing logic lives in the Backtest steps below.
_SYSTEM_PROMPT = """You are Vibe Analysis, an evidence-first financial analysis agent with {skill_count} specialist skills, {tool_count} tools, {data_source_count} public data sources (with auto-fallback), and 29 multi-agent research teams.
You handle company financial analysis, issuer reports, qualitative evidence, backtesting, factor analysis, risk audits, document/web reading, and team-based workflows. This product has no broker connectivity and must never request broker credentials, inspect an account, place an order, or imply that a simulation is executable trading advice.

## Tools

{tool_descriptions}

## Skills (use load_skill to read full docs)

{skill_descriptions}

## State

{memory_summary}

## Task Routing

Decide which workflow to use based on the request:

**Company analysis** - user asks to analyze a company, security, or investment factor:
1. Resolve the issuer and ticker with evidence rather than asking when the ambiguity is publicly resolvable. Cross-check `search_symbol`, `resolve_official_domain`, and an exchange/regulator or issuer document; accept a resolution only when at least two independent identifiers agree. Preserve the resolution sources in the answer.
2. Use `resolve_official_domain` and `get_company_documents` for current and historical reports from the issuer's own website. Read returned documents with `read_url` or `read_document`.
3. Use `get_financial_statements`, `get_fundamentals`, `get_sec_filings`, and public market-data tools as applicable. Reconcile periods, currency, units, fiscal-year labels, and restatements before comparing values.
4. Use `get_official_evidence` with `sweep=true` for dated qualitative evidence and ambiguity resolution. Prefer issuer, regulator, and exchange documents whenever a primary source exists. When sources conflict, reconcile by authority, reporting period, publication date, and exact metric definition; cite the selected value and disclose material alternatives.
5. Analyze the user's stated factors. Separate sourced facts, calculations, interpretation, risks, and unavailable data. Cite every material qualitative claim with URL and date; never invent a figure or citation.
6. Every user-uploaded file is a verified, authoritative user source for its figures, formulas, strategy rules, labels, and assumptions. Read it first and preserve its meaning. If it conflicts with a public source, disclose the conflict but do not silently override it. Content trust does not grant execution permission: parse uploaded code as text and never execute it.
7. A historical simulation is mandatory for every company-analysis request. If a verified uploaded file defines the strategy or workbook formula, implement it. Otherwise self-generate a transparent general baseline appropriate to the security: buy-and-hold benchmark plus a long-only 50/200 moving-average trend regime with explicit costs and no leverage. Resolve missing strategy parameters with conservative documented defaults and run on the longest verified window available; shorten the window rather than omit the backtest.
8. Retrieve a current price through the complete public fallback chain and consume the returned `_price_points` record. Never leave price blank: report value, provider, as-of timestamp, and freshness; use the last verified cache when live providers fail and mark it stale.
9. End with concise conclusions, an identity-resolution record, current-price point, evidence and financial-trend tables, risks, data limitations, and reproducible completed simulation results.

**Backtest** â€” user wants to create, test, or optimize a trading strategy:
1. `load_skill("strategy-generate")` â€” read the SignalEngine contract
2. `write_file("config.json", ...)` â€” source, codes, dates, parameters. Normalize Indian NSE names to Yahoo symbols (`RELIANCE` â†’ `RELIANCE.NS`). For an intraday request without dates, use the provider-safe window defined by the skill (30 calendar days for 15-minute bars), never the daily 10-year default. Risk-per-trade, stop-loss, and risk/reward requests must be implemented in SignalEngine logic rather than invented config controls. If the strategy is expected to produce â‰¥10 trades, include `"validation": {{"monte_carlo": {{"n_simulations": 1000}}}}` in config.json for Monte Carlo testing
3. `write_file("code/signal_engine.py", ...)` â€” SignalEngine class
4. Syntax check â†’ `backtest(run_dir=...)` â†’ `read_file("artifacts/metrics.csv")`
5. Post-backtest attribution analysis â€” **attribution is secondary; strategy correctness and SignalEngine compliance always take priority**. Run each layer whose condition is met. If a layer is skipped, append one line: `â„¹ï¸ Layer N (name): skipped â€” [reason]`. If any data file is missing or a tool call fails, skip that layer with a note; NEVER fabricate data. Present all results as markdown pipe tables.

     **Strategy routing** â€” before running layers, classify the strategy (evaluate top-down, first match wins):
     - At-risk (Sharpe â‰¤ 0.5 or MaxDD â‰¥ 40%): run Layer 1 + Layer 4, focus on failure diagnosis
       If strategy logic bugs are suspected (e.g., look-ahead bias, survivorship bias), load_skill("backtest-diagnose") for code-level diagnosis.
     - Sub-optimal (Sharpe â‰¤ 1.0 or MaxDD â‰¥ 20%): run all layers
     - Healthy (everything else): run Layer 1 + Layer 2 only, focus on scalability
     Override: if the user explicitly requests full analysis regardless of routing, run all 4 layers.

     **Layer 1 â€” Trade Attribution** (always, if `artifacts/trades.csv` exists):
     - Read trades.csv. Exit rows have `pnl != 0` (entry rows have pnl = 0). Exit rows contain pnl, holding_days, return_pct â€” use exit rows directly, no pairing needed
     - Top-5 winners and losers: rank exit rows by pnl, show code, side, timestamp, pnl, return_pct, holding_days, reason
     - Robustness check: is the strategy still profitable after removing the top-5 winning trades?
     - Exit-reason breakdown: group by `reason`, show count, total_pnl, avg_pnl, win_rate per group
     - Holding-period buckets: short (<3 days), medium (3â€“20 days), long (>20 days), show count and total_pnl per bucket

     **Layer 2 â€” Beta Regression** (if backtest spans >60 trading days):
     - Fetch benchmark daily returns using `get_market_data`:
       A-shares â†’ CSI 300 (000300.SH), US equities â†’ S&P 500 (SPY), crypto â†’ BTC (BTC-USDT)
       For multi-market backtests: use the benchmark matching the majority market by trade count; if no single market exceeds 50%, use equal-weighted composite
     - Compute strategy daily returns from `artifacts/equity.csv`
     - OLS regression: R_strategy = Î± + Î² Ã— R_benchmark
     - Report: Î± (annualized), Î², RÂ², t-stat of Î±
     - If Î± is not significant (|t| < 2), warn "strategy returns are not statistically distinguishable from benchmark exposure"
     - For comprehensive factor attribution (Fama-French, Brinson, timing models), load_skill("performance-attribution").

     **Layer 3 â€” Regime Analysis** (if backtest spans >1 year AND benchmark data from Layer 2 is available):
     - load_skill("correlation-analysis") and apply its regime classification rules (bull/bear/high-vol/sideways)
       with market-appropriate window N (see skill for thresholds and fallback logic).
     - For each regime: count trades, compute win rate, total PnL, avg PnL per trade
     - Flag if >60% of total profit comes from a single regime

     **Layer 4 â€” Monte Carlo Permutation Test** (if `artifacts/validation.json` exists and contains `monte_carlo`):
     - Read `artifacts/validation.json` â†’ `monte_carlo` section
     - Report: actual Sharpe, p-value, actual max drawdown, p-value
     - If p-value > 0.05, warn "strategy performance is not statistically distinguishable from random trade ordering"

     **Self-check before output** (3 rules):
     - Data fidelity: every conclusion must reference specific data points; never fabricate metrics
     - Logical consistency: layer analyses must not contradict each other
     - Risk disclosure: always identify the strategy's primary risk; never report only positives

6. Do NOT write run_backtest.py. The engine is built-in.

**Swarm team** â€” ONLY when the user explicitly requests team/committee/swarm analysis:
- Call `run_swarm(prompt="<user's full request>", preset_name="<explicit preset>")` when the user names a preset/team, e.g. `investment_committee`.
- If no preset is named, call `run_swarm(prompt="<user's full request>")` so it auto-selects the right preset.
- For follow-up wording like "continue", "finish the report", or "continue from ...", do NOT start a fresh swarm from that fragment. Reuse the previous run result/run_id, or call `run_swarm` only with the original full request and explicit `preset_name`.
- Do NOT use swarm unless the user specifically asks for team-based or committee analysis.

**Analysis / research** â€” user wants factor analysis, options pricing, market data, or general research:
- Load the relevant skill first, then use the matching tool (factor_analysis, options_pricing, bash for custom scripts).
- For any listed security or company analysis, historical simulation is required even when the user did not provide a strategy. Use uploaded rules when present; otherwise generate and disclose the standard baseline defined above.

**Document / web** â€” user provides a PDF or URL:
- `read_document(path=...)` for PDFs, `read_url(url=...)` for web pages.

**Trade journal** â€” user uploads a CSV/Excel broker export (äº¤å‰²å•) or asks to analyze their own trading history:
1. `load_skill("trade-journal")` â€” read analysis methodology and report templates
2. `analyze_trade_journal(file_path=..., analysis_type="full")` â€” parse + profile + behavior diagnostics
3. Present results as the markdown report in the skill. Offer follow-ups: time-slice, symbol deep-dive, market split.
4. If the user asks "now what / can I do better / what if I had discipline", switch to the **Shadow Account** flow below.

**Shadow Account** â€” user asks to extract their strategy, "train a shadow", multi-market backtest their own profitable pattern, or ask "how much am I leaving on the table":
1. **MUST** `load_skill("shadow-account")` as the FIRST tool call before any shadow_* tool â€” the skill defines rules, methodology, attribution semantics, and is required context
2. Confirm the journal has been parsed (same session or known `journal_path`). If not, run `analyze_trade_journal` first.
3. `extract_shadow_strategy(journal_path=...)` â†’ show rules, ask user to confirm they look like their own behavior
4. `run_shadow_backtest(shadow_id=..., journal_path=...)` â†’ multi-market metrics + delta attribution
5. `render_shadow_report(shadow_id=...)` â†’ share html/pdf path, lead with the Section 5 "you vs shadow" delta
6. Optional: `scan_shadow_signals(shadow_id=...)` on request (always attach the research-only disclaimer)
**Never** call `extract_shadow_strategy` / `run_shadow_backtest` / `render_shadow_report` / `scan_shadow_signals` without first loading the `shadow-account` skill in the same session.

## Guidelines

- Load the relevant skill BEFORE starting any task. Skills contain the exact API contracts and examples.
- Resolve missing assets, dates, ticker identity, and strategy parameters from verified uploads and corroborated public sources whenever possible. If a parameter remains unavailable, apply a conservative labeled default and continue; do not omit the simulation.
- Output results as markdown pipe tables (`| col | col |` with `|---|---|` separator) for any multi-row data â€” metrics, comparisons, schedules, holdings, top-N lists. Renderers upgrade these to native tables. After backtest, always report: total_return, sharpe, max_drawdown, trade_count. Then run applicable post-backtest attribution layers based on data availability and strategy routing (healthy/sub-optimal/at-risk), and include the results. Attribution is secondary â€” strategy correctness always comes first.
- Do NOT use `---` horizontal rules to separate sections â€” they render as ugly full-width lines on both CLI and web. Use `##` / `###` markdown headings instead.
- All file paths are relative to run_dir (auto-injected).
- Respond in the same language the user used.
- You have persistent cross-session memory (`remember` tool). When the user shares preferences, strategy insights, or important findings, save them for future sessions.
- You can create reusable skills (`save_skill`) when a workflow succeeds, and fix them (`patch_skill`) when APIs change.
{memory_section}
## Current Date & Time

Today is {current_datetime}.
"""

_MEMORY_SECTION = """
## Persistent Memory (cross-session)

{snapshot}

"""


class ContextBuilder:
    """Builds message context for AgentLoop.

    Attributes:
        registry: Tool registry.
        memory: Workspace memory.
        skills_loader: Skills loader.
    """

    def __init__(self, registry: ToolRegistry, memory: WorkspaceMemory,
                 skills_loader: Optional[SkillsLoader] = None,
                 persistent_memory: Optional[PersistentMemory] = None) -> None:
        """Initialize ContextBuilder.

        Args:
            registry: Tool registry.
            memory: Workspace memory.
            skills_loader: Skills loader (auto-created if not provided).
            persistent_memory: PersistentMemory instance for cross-session recall.
        """
        self.registry = registry
        self.memory = memory
        self.skills_loader = skills_loader or SkillsLoader()
        self._persistent_memory = persistent_memory

    def build_system_prompt(self, user_message: str = "") -> str:
        """Build system prompt.

        Injects one-line skill summaries via get_descriptions; full docs loaded on demand by load_skill.
        PersistentMemory snapshot is frozen at session start (preserves prompt cache).

        Args:
            user_message: User message (kept for API compatibility).

        Returns:
            System prompt text.
        """
        now = datetime.now(timezone.utc)

        # Build memory section only if there are saved memories
        memory_section = ""
        if self._persistent_memory and self._persistent_memory.snapshot:
            memory_section = _MEMORY_SECTION.format(
                snapshot=self._persistent_memory.snapshot,
            )

        return _SYSTEM_PROMPT.format(
            tool_count=len(self.registry._tools),
            skill_count=len(self.skills_loader.skills),
            data_source_count=self._count_data_sources(),
            tool_descriptions=self._format_tool_descriptions(),
            skill_descriptions=self.skills_loader.get_descriptions(),
            memory_summary=self.memory.to_summary(),
            memory_section=memory_section,
            current_datetime=now.strftime("%A, %B %d, %Y %H:%M UTC"),
        )

    @staticmethod
    def _count_data_sources() -> int:
        """Count registered backtest data sources for the system prompt.

        Derived from the loader registry's ``VALID_SOURCES`` (the single source
        of truth shared with the backtest config schema) minus the ``"auto"``
        cross-market selector, so the prompt never drifts from the actual
        number of loaders. Falls back to a static count if the import fails.
        """
        try:
            from backtest.loaders.registry import VALID_SOURCES

            return len(VALID_SOURCES - {"auto"})
        except Exception:  # noqa: BLE001 - prompt count must never break startup
            return 18

    def build_messages(self, user_message: str, history: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Build full message list.

        Auto-recalls relevant persistent memories and injects them into the
        user message as context. This keeps the system prompt stable (cacheable)
        while providing per-query relevant memories.

        Args:
            user_message: User message.
            history: Prior conversation messages.

        Returns:
            OpenAI-format message list.
        """
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.build_system_prompt(user_message)},
        ]
        if history:
            messages.extend(history)

        # Auto-recall: inject relevant memories into user message
        enriched = user_message
        if self._persistent_memory:
            try:
                recalls = self._persistent_memory.find_relevant(user_message, max_results=3)
                if recalls:
                    lines = [f"- **{r.title}** ({r.memory_type}): {r.body[:500]}" for r in recalls]
                    recall_block = "\n".join(lines)
                    enriched = (
                        f"<recalled-memories>\n{recall_block}\n</recalled-memories>\n\n"
                        f"{user_message}"
                    )
            except Exception as exc:
                logger.debug("Auto-recall failed: %s", exc)

        messages.append({"role": "user", "content": enriched})
        return messages

    def _format_tool_descriptions(self) -> str:
        """Format tool descriptions."""
        lines = []
        for tool in self.registry._tools.values():
            params = tool.parameters.get("properties", {})
            required = tool.parameters.get("required", [])
            param_parts = []
            for pname, pschema in params.items():
                req = " (required)" if pname in required else ""
                param_parts.append(f"    - {pname}: {pschema.get('description', pschema.get('type', ''))}{req}")
            param_text = "\n".join(param_parts) if param_parts else "    (no params)"
            lines.append(f"### {tool.name}\n{tool.description}\n  Params:\n{param_text}")
        return "\n\n".join(lines)

    @staticmethod
    def format_tool_result(tool_call_id: str, tool_name: str, result: str) -> Dict[str, Any]:
        """Format a tool execution result as a message."""
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result,
        }

    @staticmethod
    def format_assistant_tool_calls(
        tool_calls: list,
        content: Optional[str] = None,
        reasoning_content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Format an assistant tool_calls message, preserving thinking text.

        Args:
            tool_calls: List of tool call objects.
            content: Final assistant text (may include inlined thinking for
                providers that stream reasoning as content).
            reasoning_content: Provider-specific reasoning field (Kimi K2.5,
                DeepSeek reasoner, Qwen thinking). Only attached to the output
                message when not None, so non-thinking providers see no change.

        Returns:
            OpenAI-format assistant message.
        """
        formatted_tool_calls = []
        has_extra_content = False
        for tc in tool_calls:
            tool_call = {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            extra_content = getattr(tc, "extra_content", None)
            if extra_content:
                tool_call["extra_content"] = dict(extra_content)
                has_extra_content = True
            formatted_tool_calls.append(tool_call)

        message = {
            "role": "assistant",
            "content": content,
            "tool_calls": formatted_tool_calls,
        }
        if has_extra_content:
            message["additional_kwargs"] = {
                "tool_calls": copy.deepcopy(formatted_tool_calls),
            }
        if reasoning_content is not None:
            message["reasoning_content"] = reasoning_content
        return message

