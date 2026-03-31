"""Joint analysis engine combining holdings with market intelligence."""

from __future__ import annotations

import json
import re
from typing import Any

from src.core.analysis.position_analysis import build_portfolio_flags
from src.core.providers.llm_client import run_analysis_model

FINAL_SYSTEM_PROMPT = """你是私人投资简报撰写助手。

你的职责不是重新计算数字，而是基于系统已经算好的账户事实、研究计划和最新资讯做解释。

硬性规则：
- 只能使用输入提供的数字、新闻和结论，不能补造、不能猜测
- 如果系统给的是 short/空头仓位，盈亏方向必须按系统提供的 pnl_pct 解读
- 绝对仓位看 weight_pct，净敞口看 net_weight_pct，不能混用
- 跨币种持仓已经被系统换算到基币，不能再拿本币市值重算
- 新闻部分只总结输入里最相关的持仓驱动，不要泛泛而谈
- 输出必须短、清楚、克制，像严谨的投顾日报
- 不要使用 markdown 表格

输出结构固定为：
市场判断
- ...

相关资讯
- ...

组合解读
- ...

风险提醒
- ...

今日动作
- ..."""

_BLOCKED_LINE_FRAGMENTS = (
    "暂无可靠最新数据",
    "说明：",
    "市场主线",
    "科技与个股",
    "今晚关注",
    "我能提供的最新",
)


def build_analysis(
    positions: dict[str, Any],
    research_plan: dict[str, Any],
    market_context: str,
) -> str:
    """Generate the final daily brief from portfolio data and market context.

    Assembles a structured JSON payload and calls the LLM client.
    Returns a 5-section analysis string ready for display.
    """
    print("[PortfolioMarketAnalysis] Starting final portfolio analysis...")

    payload = {
        "portfolio": _build_portfolio_payload(positions),
        "research_plan": research_plan,
        "market_context": _build_market_facts(market_context),
    }
    prompt = f"""下面是系统整理好的账户事实、研究计划和相关资讯。
请写成一份短、硬、实用的投资简报。

【输入 JSON】
{json.dumps(payload, ensure_ascii=False, indent=2)}

写作要求：
- 市场判断：2 到 3 条，只写与当前组合最相关的大环境
- 相关资讯：3 到 5 条，只写最可能影响持仓的新闻或情绪
- 组合解读：3 到 5 条，优先点评前几大仓位和净敞口
- 风险提醒：2 到 4 条，只写真正有阈值意义的风险
- 今日动作：2 到 4 条，给建议，不要替用户下命令
- 引用数字时必须直接使用 JSON 里的值
- 不要写套话，不要写"根据搜索结果"，不要写输入里没有的新新闻"""

    return run_analysis_model(FINAL_SYSTEM_PROMPT, prompt, max_output_tokens=1800)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_portfolio_payload(positions: dict[str, Any]) -> dict[str, Any]:
    """Build a concise, stable portfolio payload for the LLM."""
    total_value = float(positions.get("total_value", 0.0))
    cash = float(positions.get("cash", 0.0))
    cash_pct = float(positions.get("cash_pct", 0.0))
    daily_pnl = float(positions.get("daily_pnl", 0.0))
    daily_return_pct = float(positions.get("daily_return_pct", 0.0))
    base_currency = str(positions.get("base_currency", "BASE"))
    holdings = positions.get("positions", [])

    return {
        "portfolio_summary": {
            "report_date": str(positions.get("report_date", "")),
            "scope": str(positions.get("scope", "")),
            "account_id": str(positions.get("account_id", "")),
            "account_alias": str(positions.get("account_alias", "")),
            "base_currency": base_currency,
            "total_value": round(total_value, 2),
            "cash": round(cash, 2),
            "cash_pct": round(cash_pct, 2),
            "daily_pnl": round(daily_pnl, 2),
            "daily_return_pct": round(daily_return_pct, 2),
            "gross_exposure_pct": round(
                sum(abs(float(h.get("net_weight_pct", 0.0))) for h in holdings), 2
            ),
            "holding_count": len(holdings),
        },
        "portfolio_flags": build_portfolio_flags(holdings),
        "top_holdings": _build_top_holdings(holdings, base_currency),
    }


def _build_top_holdings(holdings: list[dict[str, Any]], base_currency: str) -> list[dict[str, Any]]:
    """Prepare the largest exposures with stable field names for the LLM."""
    return [
        {
            "symbol": str(h.get("symbol", "UNKNOWN")),
            "description": str(h.get("description", "")),
            "side": str(h.get("side", "Long")),
            "asset_category": str(h.get("asset_category", "")),
            "currency": str(h.get("currency", "")),
            "quantity": round(float(h.get("quantity", 0.0)), 4),
            "weight_pct": round(float(h.get("weight_pct", 0.0)), 2),
            "net_weight_pct": round(float(h.get("net_weight_pct", 0.0)), 2),
            "pnl_pct": round(float(h.get("pnl_pct", 0.0)), 2),
            "market_value_base": round(float(h.get("market_value_base", 0.0)), 2),
            "market_value_local": round(float(h.get("market_value", 0.0)), 2),
            "base_currency": base_currency,
            "account_nav_pct": round(float(h.get("account_nav_pct", 0.0)), 2),
            "unrealized_pnl_base": round(float(h.get("unrealized_pnl_base", 0.0)), 2),
        }
        for h in holdings[:6]
    ]


def _build_market_facts(market_context: str) -> dict[str, list[str]]:
    """Parse the structured market context string into section lists for the LLM."""
    sections: dict[str, list[str]] = {
        "Perplexity 主新闻": [],
        "Perplexity 宏观看板": [],
        "Perplexity 组合相关资讯": [],
        "Grok X 情绪": [],
    }
    current_section = ""

    for raw_line in market_context.splitlines():
        line = _clean_market_line(raw_line)
        if not line:
            continue
        if line.startswith("【") and line.endswith("】"):
            current_section = line.strip("【】")
            continue
        if current_section in sections:
            sections[current_section].append(line)

    return {
        "news": sections["Perplexity 主新闻"][:5],
        "macro": sections["Perplexity 宏观看板"][:5],
        "portfolio_news": sections["Perplexity 组合相关资讯"][:6],
        "sentiment": sections["Grok X 情绪"][:4],
    }


def _clean_market_line(line: str) -> str:
    """Strip noise from market context lines before passing to the LLM."""
    cleaned = line.strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"\[[0-9,\s]+\]", "", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = cleaned.replace("根据搜索结果，", "")
    cleaned = cleaned.replace("根据搜索结果", "")
    cleaned = cleaned.replace("链接：", "")
    cleaned = cleaned.replace("来源：", "")
    cleaned = cleaned.strip(" -•")

    if any(frag in cleaned for frag in _BLOCKED_LINE_FRAGMENTS):
        return ""
    return cleaned.strip()
