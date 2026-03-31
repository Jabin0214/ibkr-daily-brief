"""Pipeline helpers for the daily portfolio report flow."""

from __future__ import annotations

from typing import Any

from src.core.analysis.market_context import MarketContext, build_market_context
from src.core.analysis.portfolio_context import (
    build_ibkr_analysis_payload,
    build_mock_ibkr_analysis_payload,
)
from src.core.providers.ibkr_client import get_ibkr_positions, get_ibkr_statement_xml


def run_ibkr_fetch_step() -> str:
    """Fetch the latest raw IBKR statement XML."""
    return get_ibkr_statement_xml()


def run_portfolio_positions_step() -> dict[str, Any]:
    """Fetch the parsed IBKR positions payload."""
    return get_ibkr_positions()


def run_portfolio_context_step(xml_text: str) -> dict[str, Any]:
    """Build structured portfolio context from raw IBKR XML."""
    return build_ibkr_analysis_payload(xml_text)


def run_mock_portfolio_context_step() -> dict[str, Any]:
    """Build a mock portfolio context payload for local testing."""
    return build_mock_ibkr_analysis_payload()


def run_market_context_step(
    research_plan: dict[str, Any] | None = None,
    positions: dict[str, Any] | None = None,
) -> MarketContext:
    """Build the daily market context for the report pipeline."""
    return build_market_context(research_plan=research_plan, positions=positions)

