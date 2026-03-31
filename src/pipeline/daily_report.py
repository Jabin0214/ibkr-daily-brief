"""Daily report pipeline — orchestrates all five stages of the automated brief."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.analysis.market_context import MarketContext, build_analysis_news_context, build_market_context
from src.core.analysis.portfolio_context import (
    build_ibkr_analysis_payload,
    build_mock_ibkr_analysis_payload,
    mock_portfolio_data,
    parse_portfolio_xml,
)
from src.core.analysis.portfolio_market_analysis import build_analysis
from src.core.analysis.position_analysis import build_research_plan, normalize_portfolio
from src.core.providers.ibkr_client import get_ibkr_statement_xml


@dataclass
class DailyReportArtifacts:
    """Structured outputs produced by the daily pipeline before presentation."""

    positions: dict[str, Any]
    research_plan: dict[str, Any]
    market: MarketContext
    analysis: str


def run_daily_report_pipeline(
    test_mode: bool = False,
    output_dir: Path | None = None,
) -> DailyReportArtifacts:
    """Run all five stages and return structured artifacts for presentation.

    Stages:
    1. Fetch IBKR portfolio
    2. Build portfolio research plan
    3. Fetch targeted market intelligence
    4. Generate AI analysis
    5. Return structured artifacts for interface rendering
    """
    positions = _stage_fetch_portfolio(test_mode)
    research_plan = _stage_build_research_plan(positions)
    market = _stage_fetch_market_context(research_plan, positions)
    analysis = _stage_generate_analysis(positions, research_plan, market)
    return DailyReportArtifacts(
        positions=positions,
        research_plan=research_plan,
        market=market,
        analysis=analysis,
    )


# ---------------------------------------------------------------------------
# News-only pipeline
# ---------------------------------------------------------------------------


def run_news_only_pipeline() -> MarketContext:
    """Fetch and return the structured market context."""
    return _stage_fetch_market_context()


# ---------------------------------------------------------------------------
# IBKR-only pipeline
# ---------------------------------------------------------------------------


def run_ibkr_snapshot_pipeline(test_mode: bool = False) -> dict[str, Any]:
    """Fetch and return normalized portfolio data."""
    return _stage_fetch_portfolio(test_mode)


def run_ibkr_payload_pipeline(test_mode: bool = False) -> dict[str, Any]:
    """Fetch IBKR data and return an analysis-ready JSON payload."""
    print("[Pipeline] Step 1/1: Fetching IBKR analysis payload...")
    if test_mode:
        print("[Pipeline] Using mock portfolio payload for test mode.")
        return build_mock_ibkr_analysis_payload()

    xml_text = get_ibkr_statement_xml()
    if not xml_text:
        return build_mock_ibkr_analysis_payload()
    return build_ibkr_analysis_payload(xml_text)


def _stage_fetch_portfolio(test_mode: bool) -> dict[str, Any]:
    print("[Pipeline] Step 1/5: Fetching portfolio snapshot...")
    if test_mode:
        print("[Pipeline] Using mock positions for test mode.")
        return normalize_portfolio(mock_portfolio_data())
    xml_text = get_ibkr_statement_xml()
    if not xml_text:
        return normalize_portfolio(mock_portfolio_data())
    return normalize_portfolio(parse_portfolio_xml(xml_text))


def _stage_build_research_plan(positions: dict[str, Any]) -> dict[str, Any]:
    print("[Pipeline] Step 2/5: Building portfolio research plan...")
    return build_research_plan(positions)


def _stage_fetch_market_context(
    research_plan: dict[str, Any] | None = None,
    positions: dict[str, Any] | None = None,
) -> MarketContext:
    print("[Pipeline] Step 3/5: Fetching targeted market intelligence...")
    return build_market_context(research_plan=research_plan, positions=positions)


def _stage_generate_analysis(
    positions: dict[str, Any],
    research_plan: dict[str, Any],
    market: MarketContext,
) -> str:
    print("[Pipeline] Step 4/5: Generating final investment analysis...")
    news_context = build_analysis_news_context(market)
    return build_analysis(positions, research_plan, news_context)
