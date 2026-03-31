"""Structured daily market context for downstream analysis."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
import re
from typing import Any

from src.core.providers.ai_client import get_market_bundle, get_market_sentiment

NEWS_MARKET_FALLBACK = (
    "市场主线暂时不完整，但当前可确认的重点仍是："
    "央行路径、油价与地缘风险、以及科技股风险偏好的变化。"
)
PORTFOLIO_NEWS_FALLBACK = "组合相关资讯暂时不完整，请优先关注核心持仓财报、利率与行业景气变化。"


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


def clean_market_text(text: str) -> str:
    """Strip formatting noise from market text before analysis or rendering."""
    cleaned = text.strip()
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\[[0-9,\s]+\]", "", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("```", "")
    cleaned = cleaned.replace("根据搜索结果，", "").replace("根据搜索结果", "")
    cleaned = cleaned.replace("链接：", "").replace("来源：", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def normalize_market_text(text: str, fallback: str) -> str:
    """Remove refusal-style language and return a stable fallback when needed."""
    cleaned = clean_market_text(text)
    refusal_markers = (
        "我无法",
        "不能按照您的要求",
        "无法按照您的要求",
        "原因如下",
        "不符合",
        "无法生成",
    )
    if any(marker in cleaned for marker in refusal_markers):
        return fallback
    return cleaned.strip() or fallback


def build_analysis_news_context(market: MarketContext) -> str:
    """Build the market context string passed into the final analysis model."""
    return (
        "【Perplexity 主新闻】\n"
        f"{market.brief}\n\n"
        "【Perplexity 宏观看板】\n"
        f"{market.macro}\n\n"
        "【Perplexity 组合相关资讯】\n"
        f"{market.portfolio_news}\n\n"
        "【Grok X 情绪】\n"
        f"{market.sentiment}"
    )
