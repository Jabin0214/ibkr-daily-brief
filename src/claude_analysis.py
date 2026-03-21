"""Portfolio analysis generation via Anthropic Claude or Perplexity fallback."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from anthropic import Anthropic

from src.networking import get_openai_compatible_client

SYSTEM_PROMPT = """你是私人投资简报撰写助手。

你的职责不是重新计算数字，而是基于系统已经算好的事实做解释。

硬性规则：
- 只能使用系统提供的数字、持仓和市场事实，不能补造、不能猜测、不能改写百分比
- 如果系统给的是 short/空头仓位，盈亏方向必须按系统提供的 `pnl_pct` 解读
- 绝对仓位看 `weight_pct`，净敞口看 `net_weight_pct`，不要混用
- 跨币种持仓已经被系统换算到基币，不能再拿本币市值重算总仓位
- 市场部分只能总结给出的事实，不能引入新的新闻、价格或事件
- 输出必须短、清楚、克制，像严谨的投顾晚报，不要口号，不要空话
- 每个小点尽量 1 到 2 句话
- 不要使用 markdown 表格

输出结构固定为：
市场判断
- ...

组合解读
- ...

风险提醒
- ...

今日动作
- ..."""


def generate_analysis(market_context: str, positions: dict[str, Any]) -> str:
    """Generate a concise daily portfolio brief with Claude or Perplexity."""
    print("[Analysis] Starting portfolio analysis...")

    payload = _build_analysis_payload(market_context, positions)
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    user_prompt = f"""下面是系统已经整理好的账户事实和市场事实。
请严格基于这些事实写简报，不要自己重新计算数字，也不要补充系统里没有的新事实。

【事实 JSON】
{payload_json}

写作要求：
- 市场判断：2 到 3 条，先写大方向，再写驱动因素
- 组合解读：3 到 5 条，优先解释现金、组合整体波动、前几大持仓
- 风险提醒：2 到 4 条，只写真正需要盯的风险
- 今日动作：2 到 4 条，只给建议，不要替用户做交易决定
- 引用数字时，必须直接使用 JSON 里的值
- 如果某个持仓是 short，就明确告诉用户这是空头/卖方仓位
- 如果没有足够依据，不要硬写宏观结论
- 不要写“根据搜索结果”“可能”“大概”“建议关注所有因素”这种空话"""

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return _generate_with_claude(api_key, user_prompt)

    perplexity_key = os.getenv("PERPLEXITY_API_KEY")
    if perplexity_key:
        print("[Analysis] ANTHROPIC_API_KEY missing, using Perplexity fallback.")
        return _generate_with_perplexity(perplexity_key, user_prompt)

    print("[Analysis] Missing ANTHROPIC_API_KEY and PERPLEXITY_API_KEY.")
    return "分析生成失败：请检查分析模型的 API 配置。"


def _generate_with_claude(api_key: str, user_prompt: str) -> str:
    """Generate the final brief with Anthropic Claude."""
    try:
        client = Anthropic(api_key=api_key, timeout=40)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        result = "\n".join(text_blocks).strip()
        print("[Analysis] Claude analysis completed.")
        return result or "分析生成失败：Claude 未返回有效内容。"
    except Exception as exc:
        print(f"[Analysis] Claude analysis failed: {exc}")
        return "分析生成失败：请稍后重试或检查 Claude API。"


def _generate_with_perplexity(api_key: str, user_prompt: str) -> str:
    """Generate the final brief with Perplexity when Anthropic is unavailable."""
    try:
        client = get_openai_compatible_client(api_key, "https://api.perplexity.ai")
        response = client.chat.completions.create(
            model="sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": f"{SYSTEM_PROMPT}\n禁止使用 JSON 之外的数字。不要输出引用标记，不要输出链接。",
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or ""
        print("[Analysis] Perplexity fallback analysis completed.")
        return content.strip() or "分析生成失败：Perplexity 未返回有效内容。"
    except Exception as exc:
        print(f"[Analysis] Perplexity fallback analysis failed: {exc}")
        return "分析生成失败：请稍后重试或检查 Perplexity API。"


def _build_analysis_payload(market_context: str, positions: dict[str, Any]) -> dict[str, Any]:
    """Build a structured fact payload so the model works from stable numbers."""
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
            "gross_exposure_pct": round(sum(abs(float(item.get("net_weight_pct", 0.0))) for item in holdings), 2),
            "holding_count": len(holdings),
        },
        "market_facts": _build_market_facts(market_context),
        "portfolio_flags": _build_portfolio_flags(holdings),
        "top_holdings": _build_top_holdings(holdings, base_currency),
    }


def _build_market_facts(market_context: str) -> dict[str, list[str]]:
    """Extract cleaner market facts from the multi-source market context text."""
    sections = {"Perplexity 主新闻": [], "Perplexity 宏观看板": [], "Grok X 情绪": []}
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
        "news": sections["Perplexity 主新闻"][:6],
        "macro": sections["Perplexity 宏观看板"][:5],
        "sentiment": sections["Grok X 情绪"][:4],
    }


def _build_portfolio_flags(holdings: list[dict[str, Any]]) -> list[str]:
    """Create deterministic portfolio flags before the model starts writing."""
    flags: list[str] = []

    for position in holdings[:8]:
        symbol = str(position.get("symbol", "UNKNOWN"))
        side = str(position.get("side", "Long")).strip()
        weight_pct = float(position.get("weight_pct", 0.0))
        pnl_pct = float(position.get("pnl_pct", 0.0))

        if pnl_pct <= -20:
            flags.append(f"{symbol}: 浮亏 {pnl_pct:.1f}%，已进入重度回撤区")
        elif pnl_pct <= -15:
            flags.append(f"{symbol}: 浮亏 {pnl_pct:.1f}%，接近止损纪律线")

        if weight_pct >= 30 and not _is_cash_equivalent_position(position):
            flags.append(f"{symbol}: 绝对仓位 {weight_pct:.1f}%，接近或超过单仓上限")

        if side.lower() == "short":
            flags.append(f"{symbol}: 这是 short/卖方仓位，方向风险不能按普通多头理解")

    return flags[:6]


def _build_top_holdings(holdings: list[dict[str, Any]], base_currency: str) -> list[dict[str, Any]]:
    """Prepare the largest exposures for the model with stable field names."""
    top_holdings: list[dict[str, Any]] = []

    for position in holdings[:6]:
        top_holdings.append(
            {
                "symbol": str(position.get("symbol", "UNKNOWN")),
                "description": str(position.get("description", "")),
                "side": str(position.get("side", "Long")),
                "asset_category": str(position.get("asset_category", "")),
                "currency": str(position.get("currency", "")),
                "quantity": round(float(position.get("quantity", 0.0)), 4),
                "weight_pct": round(float(position.get("weight_pct", 0.0)), 2),
                "net_weight_pct": round(float(position.get("net_weight_pct", 0.0)), 2),
                "pnl_pct": round(float(position.get("pnl_pct", 0.0)), 2),
                "market_value_base": round(float(position.get("market_value_base", 0.0)), 2),
                "market_value_local": round(float(position.get("market_value", 0.0)), 2),
                "base_currency": base_currency,
                "account_nav_pct": round(float(position.get("account_nav_pct", 0.0)), 2),
                "unrealized_pnl_base": round(float(position.get("unrealized_pnl_base", 0.0)), 2),
            }
        )

    return top_holdings


def _clean_market_line(line: str) -> str:
    """Trim market lines down to facts that are safe to show to the model."""
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

    blocked_fragments = (
        "暂无可靠最新数据",
        "说明：",
        "市场主线",
        "科技与个股",
        "今晚关注",
        "我能提供的最新",
    )
    if any(fragment in cleaned for fragment in blocked_fragments):
        return ""
    return cleaned.strip()


def _is_cash_equivalent_position(position: dict[str, Any]) -> bool:
    """Avoid treating treasury ETFs like high-beta single-name concentration risk."""
    symbol = str(position.get("symbol", "")).upper()
    description = str(position.get("description", "")).upper()
    return symbol in {"SGOV", "BIL", "SHV", "JPST"} or "TREASURY" in description
