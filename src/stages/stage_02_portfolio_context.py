"""Stage 02: build analysis-ready portfolio context."""

from __future__ import annotations

from typing import Any

from src.core.analysis.portfolio_context import build_ibkr_analysis_payload, build_mock_ibkr_analysis_payload


def run_portfolio_context_stage(xml_text: str) -> dict[str, Any]:
    """Build a portfolio context payload from raw IBKR XML."""
    return build_ibkr_analysis_payload(xml_text)


def run_mock_portfolio_context_stage() -> dict[str, Any]:
    """Build a mock portfolio context payload for local testing."""
    return build_mock_ibkr_analysis_payload()
