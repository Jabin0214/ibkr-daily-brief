"""Telegram-facing rendering layer for pipeline outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.analysis.market_context import (
    MarketContext,
    NEWS_MARKET_FALLBACK,
    PORTFOLIO_NEWS_FALLBACK,
    clean_market_text,
    normalize_market_text,
)
from src.interface.telegram.brief_builder import (
    MarketSnapshot,
    build_daily_brief,
    build_news_flash,
    build_portfolio_snapshot,
    normalize_analysis,
)
from src.interface.telegram.html_report import write_daily_report


def render_market_snapshot(market: MarketContext) -> MarketSnapshot:
    """Convert a core market context into a Telegram-facing snapshot."""
    return MarketSnapshot(
        brief=normalize_market_text(market.brief, NEWS_MARKET_FALLBACK),
        macro=market.macro,
        portfolio_news=normalize_market_text(market.portfolio_news, PORTFOLIO_NEWS_FALLBACK),
        sentiment=market.sentiment,
    )


def render_news_flash(market: MarketContext) -> str:
    """Render a news-only Telegram message from core market context."""
    return build_news_flash(render_market_snapshot(market))


def render_portfolio_snapshot(positions: dict[str, Any]) -> str:
    """Render an IBKR-only Telegram snapshot from normalized positions."""
    return build_portfolio_snapshot(positions)


def render_daily_report(
    market: MarketContext,
    positions: dict[str, Any],
    analysis: str,
    research_plan: dict[str, Any],
    output_dir: Path,
) -> tuple[str, Path]:
    """Render Telegram message plus HTML report from pipeline outputs."""
    snapshot = render_market_snapshot(market)
    message = build_daily_brief(snapshot, positions, analysis)
    report_path = write_daily_report(
        analysis=normalize_analysis(analysis),
        market={
            "brief": clean_market_text(snapshot.brief),
            "macro": clean_market_text(snapshot.macro),
            "portfolio_news": clean_market_text(snapshot.portfolio_news),
            "sentiment": clean_market_text(snapshot.sentiment),
        },
        positions=positions,
        research=research_plan,
        output_dir=output_dir,
    )
    return message, report_path
