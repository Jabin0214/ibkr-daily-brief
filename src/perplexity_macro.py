"""Portfolio-aware market and news retrieval via Perplexity API."""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

from src.networking import get_openai_compatible_client

MACRO_FALLBACK = "宏观数据暂时不可用：请关注美股期货、VIX、美债收益率、DXY、黄金和原油的最新变化。"
NEWS_FALLBACK = "主新闻快讯暂时不可用：请稍后重试 Perplexity 搜索。"
PORTFOLIO_NEWS_FALLBACK = "组合相关资讯暂时不可用：请关注核心持仓财报、监管、行业景气和利率变化。"


def get_macro_data(research_plan: dict[str, Any] | None = None) -> str:
    """Fetch key macro indicators from Perplexity with portfolio-aware emphasis."""
    print("[Perplexity] Starting macro data request...")

    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        print("[Perplexity] Missing PERPLEXITY_API_KEY.")
        return MACRO_FALLBACK

    focus_themes = ", ".join(research_plan.get("focus_themes", [])) if research_plan else ""
    prompt = f"""请整理一版面向“美股 + 港股持仓用户”的宏观看板。

当前组合最相关的主题是：{focus_themes or "利率、科技股、港股风险偏好、油价与美元流动性"}。

只输出 5 到 6 行项目符号，每行格式固定为：
- 指标名 | 最新值 | 方向/变化 | 一句话含义

必须尽量覆盖：
- 美股主要指数或期货
- VIX
- 10年期美债收益率
- 美元指数 DXY
- 黄金
- 原油

硬性要求：
- 用简洁中文
- 优先写美国市场和全球风险因子
- 如果某个指标和 focus_themes 直接相关，优先保留
- 不要输出链接、引用编号、来源说明、免责声明
- 没拿到可靠数字就跳过，不要编造
- 最后不要补总结段落"""

    return _run_perplexity(prompt, "macro")


def get_market_brief(research_plan: dict[str, Any] | None = None) -> str:
    """Fetch the main market brief with portfolio-aware prioritization."""
    print("[Perplexity] Starting verified market brief request...")

    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        print("[Perplexity] Missing PERPLEXITY_API_KEY for market brief.")
        return NEWS_FALLBACK

    focus_symbols = ", ".join(research_plan.get("focus_symbols", [])) if research_plan else ""
    focus_themes = ", ".join(research_plan.get("focus_themes", [])) if research_plan else ""
    prompt = f"""请基于实时搜索生成一版面向“美股 + 港股持仓用户”的市场主线摘要。

当前组合最相关的代码：{focus_symbols or "AAPL, SGOV, 港股互联网/高股息, options"}。
当前组合最相关的主题：{focus_themes or "美联储、科技股、利率、油价、港股风险偏好"}。

输出要求：
- 用中文
- 只输出 5 条以内项目符号
- 每条格式固定为：- 事实。市场含义。
- 先写可核实事实，再写一句市场影响
- 只保留最近 24 小时最重要的内容

硬性要求：
- 优先级必须是：美联储/美国利率 > 美股指数与科技 > 地缘与油价 > 与港股直接相关的因子
- 不要输出标题、编号、链接、引用编号、来源说明
- 不要写套话，不要写拒答语
- 没有可靠事实就跳过，不要硬凑"""

    return _run_perplexity(prompt, "brief")


def get_portfolio_relevant_news(research_plan: dict[str, Any], positions: dict[str, Any]) -> str:
    """Fetch the most portfolio-relevant news and drivers for the current holdings."""
    print("[Perplexity] Starting portfolio-relevant news request...")

    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        print("[Perplexity] Missing PERPLEXITY_API_KEY for portfolio news.")
        return PORTFOLIO_NEWS_FALLBACK

    focus_symbols = ", ".join(research_plan.get("focus_symbols", []))
    focus_themes = ", ".join(research_plan.get("focus_themes", []))
    news_questions = "\n".join(f"- {item}" for item in research_plan.get("news_questions", []))
    top_holdings = "\n".join(
        (
            f"- {position.get('symbol', 'UNKNOWN')} | "
            f"绝对仓位 {float(position.get('weight_pct', 0.0)):.1f}% | "
            f"净敞口 {float(position.get('net_weight_pct', 0.0)):+.1f}% | "
            f"盈亏 {float(position.get('pnl_pct', 0.0)):+.1f}%"
        )
        for position in positions.get("positions", [])[:6]
    )

    prompt = f"""请基于实时搜索，只找“最可能影响这份组合”的最新资讯。

【关注代码】
{focus_symbols}

【关注主题】
{focus_themes}

【重点持仓】
{top_holdings}

【要重点回答的问题】
{news_questions or "- 哪些最新事件最可能影响这些持仓？"}

输出要求：
- 只输出 6 条以内项目符号
- 每条格式固定为：- 代码/主题 | 最新事实 | 为什么影响这份组合
- 优先覆盖：核心持仓公司、对应行业、利率/汇率/油价等传导因子
- 只保留最近 72 小时内最相关的内容

硬性要求：
- 不要输出链接、引用编号、来源说明
- 不要写宏观空话
- 如果某条新闻和组合关系弱，就不要写
- 不能编造事实"""

    return _run_perplexity(prompt, "portfolio")


def _run_perplexity(prompt: str, kind: str) -> str:
    """Run a Perplexity chat completion for the requested market task."""
    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        return {
            "macro": MACRO_FALLBACK,
            "brief": NEWS_FALLBACK,
            "portfolio": PORTFOLIO_NEWS_FALLBACK,
        }[kind]

    try:
        client = _build_client(api_key)
        response = client.chat.completions.create(
            model="sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是金融新闻编辑。只输出经过搜索确认的简洁事实行，不要链接，"
                        "不要引用编号，不要标题，不要免责声明，不要空话。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        print(f"[Perplexity] {kind} request completed.")
        cleaned = content.strip()
        if cleaned:
            return cleaned
    except Exception as exc:
        print(f"[Perplexity] {kind} request failed: {exc}")

    return {
        "macro": MACRO_FALLBACK,
        "brief": NEWS_FALLBACK,
        "portfolio": PORTFOLIO_NEWS_FALLBACK,
    }[kind]


def _build_client(api_key: str) -> OpenAI:
    """Build a Perplexity OpenAI-compatible client."""
    return get_openai_compatible_client(api_key, "https://api.perplexity.ai")
