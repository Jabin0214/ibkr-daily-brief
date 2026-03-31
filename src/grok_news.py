"""Compatibility wrapper for legacy market sentiment imports."""

from src.core.providers.news_client import GROK_FALLBACK, get_market_sentiment


def get_market_news(research_plan=None):
    """Backward-compatible alias for the new market sentiment connector."""
    return get_market_sentiment(research_plan)
