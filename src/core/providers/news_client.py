"""News and sentiment connectors for daily market context."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from openai import OpenAI

from src.core.providers.networking import get_openai_compatible_client

MARKET_BUNDLE_FALLBACK = {
    "brief": "主新闻快讯暂时不可用：请稍后重试 Perplexity 搜索。",
    "macro": "宏观数据暂时不可用：请关注美股期货、VIX、美债收益率、DXY、黄金和原油的最新变化。",
    "portfolio_news": "组合相关资讯暂时不可用：请关注核心持仓财报、监管、行业景气和利率变化。",
}
GROK_FALLBACK = "市场情绪暂时不可用：请重点关注科技股风险偏好、利率敏感资产与港股情绪。"


def get_market_bundle(research_plan: dict[str, Any], positions: dict[str, Any]) -> dict[str, str]:
    """Fetch headline news, macro board, and portfolio-relevant news in one search call."""
    print("[Perplexity] Starting combined market bundle request...")

    api_key = os.getenv("PERPLEXITY_API_KEY")
    if not api_key:
        print("[Perplexity] Missing PERPLEXITY_API_KEY.")
        return dict(MARKET_BUNDLE_FALLBACK)

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

    prompt = f"""请基于实时搜索，为一份投资日报一次性输出 3 个 section：主线新闻、宏观看板、组合相关资讯。

【关注代码】
{focus_symbols}

【关注主题】
{focus_themes}

【重点持仓】
{top_holdings}

【要重点回答的问题】
{news_questions or "- 哪些最新事件最可能影响这些持仓？"}

请严格输出 JSON，格式必须为：
{{
  "brief": ["主线新闻项目"],
  "macro": ["宏观看板项目"],
  "portfolio_news": ["最相关的组合资讯项目"]
}}

每个字段要求：
- brief: 3 到 5 条，每条格式为“事实。市场含义。”
- macro: 3 到 5 条，每条格式为“指标 | 最新值 | 方向/变化 | 一句话含义”
- portfolio_news: 3 到 6 条，每条格式为“代码/主题 | 最新事实 | 为什么影响这份组合”

硬性要求：
- 只保留最近 72 小时最相关的内容
- 优先级必须是：美联储/美国利率 > 美股指数与科技 > 地缘与油价 > 与港股直接相关的因子
- 组合相关资讯必须优先覆盖真正影响仓位的新闻，不要宏观空话
- 不要输出链接、引用编号、来源说明、markdown、JSON 以外的文字
- 如果某项没有可靠事实就返回空数组，不要编造"""

    try:
        client = _build_client(api_key)
        response = client.chat.completions.create(
            model="sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是金融新闻编辑。只输出经过搜索确认的简洁 JSON，"
                        "不要链接，不要引用编号，不要标题，不要免责声明，不要空话。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        payload = _extract_json_object(content)
        print("[Perplexity] Combined market bundle request completed.")
        return {
            "brief": _join_lines(payload.get("brief"), MARKET_BUNDLE_FALLBACK["brief"]),
            "macro": _join_lines(payload.get("macro"), MARKET_BUNDLE_FALLBACK["macro"]),
            "portfolio_news": _join_lines(
                payload.get("portfolio_news"),
                MARKET_BUNDLE_FALLBACK["portfolio_news"],
            ),
        }
    except Exception as exc:
        print(f"[Perplexity] Combined market bundle request failed: {exc}")
        return dict(MARKET_BUNDLE_FALLBACK)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model output."""
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Could not parse JSON from Perplexity response: {stripped[:500]}")
    return json.loads(match.group(0))


def _join_lines(value: Any, fallback: str) -> str:
    """Normalize a JSON array into a newline-joined text block."""
    if not isinstance(value, list):
        return fallback
    lines = []
    for item in value:
        text = str(item).strip()
        if not text or _is_empty_market_line(text):
            continue
        lines.append(text)
    return "\n".join(lines) if lines else fallback


def _is_empty_market_line(text: str) -> bool:
    """Filter out placeholder items that look like empty or useless news."""
    normalized = text.strip().lower()
    empty_markers = (
        "无72小时内直接新闻",
        "暂无直接新闻",
        "暂无相关新闻",
        "无可靠最新值",
        "无可靠最新数据",
        "暂无可靠最新值",
        "空。",
        "空 |",
        "| 空",
        "暂无更新",
        "没有可靠事实",
    )
    return any(marker in normalized for marker in empty_markers)


def _build_client(api_key: str) -> OpenAI:
    """Build a Perplexity OpenAI-compatible client."""
    return get_openai_compatible_client(api_key, "https://api.perplexity.ai")


def get_market_sentiment(research_plan: dict[str, Any] | None = None) -> str:
    """Fetch today's X sentiment focused on the current portfolio."""
    print("[Grok] Starting X sentiment request...")

    api_key = os.getenv("GROK_API_KEY")
    if not api_key:
        print("[Grok] Missing GROK_API_KEY.")
        return GROK_FALLBACK

    today = datetime.now().strftime("%Y-%m-%d")
    focus_symbols = ", ".join(research_plan.get("focus_symbols", [])) if research_plan else ""
    focus_themes = ", ".join(research_plan.get("focus_themes", [])) if research_plan else ""

    prompt = f"""今天是{today}。请你总结 X 平台上和这份组合最相关的市场情绪。

重点代码：{focus_symbols or "AAPL, SGOV, 港股互联网/高股息, options"}。
重点主题：{focus_themes or "科技股风险偏好、利率、港股情绪、油价与避险"}。

只输出 4 到 5 条项目符号，每条格式固定为：
- 主题 | 情绪方向 | 为什么会影响这份组合

硬性要求：
- 只总结情绪和讨论方向，不要输出未经核实的新闻事实
- 不要编号
- 不要长段落
- 如果某条情绪和组合关系弱，就不要写"""

    try:
        client = get_openai_compatible_client(api_key, "https://api.x.ai/v1")
        response = client.chat.completions.create(
            model="grok-3",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是市场情绪助手。只总结 X 平台上的情绪、热度和讨论方向，"
                        "不要新闻事实，不要编号，不要长段落。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content or ""
        print("[Grok] X sentiment request completed.")
        return content.strip() or GROK_FALLBACK
    except Exception as exc:
        print(f"[Grok] Request failed: {exc}")
        return GROK_FALLBACK
