"""Stage 03: build structured market context from daily news and market data."""

from __future__ import annotations

from typing import Any

from src.core.analysis.market_context import MarketContext, build_market_context, market_context_to_dict


def run_market_context_stage(
    research_plan: dict[str, Any] | None = None,
    positions: dict[str, Any] | None = None,
) -> MarketContext:
    """Build a structured market context for downstream analysis stages."""
    return build_market_context(research_plan=research_plan, positions=positions)


def run_market_context_stage_as_dict(
    research_plan: dict[str, Any] | None = None,
    positions: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build a market context and return a plain dictionary."""
    return market_context_to_dict(build_market_context(research_plan=research_plan, positions=positions))
