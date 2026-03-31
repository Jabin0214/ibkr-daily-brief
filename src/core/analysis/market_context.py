"""Structured daily market context for downstream analysis."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from typing import Any

from src.core.providers.news_client import get_market_bundle, get_market_sentiment


@dataclass
class MarketContext:
    """Structured daily market context built from news and sentiment sources."""

    brief: str
    macro: str
    portfolio_news: str
    sentiment: str


def build_market_context(
    research_plan: dict[str, Any] | None = None,
    positions: dict[str, Any] | None = None,
) -> MarketContext:
    """Fetch bundled market news and sentiment, then return a structured context."""
    with ThreadPoolExecutor(max_workers=2) as executor:
        bundle_future = executor.submit(get_market_bundle, research_plan or {}, positions or {})
        sentiment_future = executor.submit(get_market_sentiment, research_plan)
        bundle = bundle_future.result()
        return MarketContext(
            brief=str(bundle.get("brief", "")).strip(),
            macro=str(bundle.get("macro", "")).strip(),
            portfolio_news=str(bundle.get("portfolio_news", "")).strip(),
            sentiment=str(sentiment_future.result()).strip(),
        )


def market_context_to_dict(context: MarketContext) -> dict[str, str]:
    """Convert a market context dataclass into a serializable dictionary."""
    return asdict(context)
