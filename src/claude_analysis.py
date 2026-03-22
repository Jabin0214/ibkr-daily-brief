"""Portfolio-first research and recommendation generation."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from anthropic import Anthropic
from openai import OpenAI

from src.networking import get_openai_compatible_client

PERPLEXITY_AGENT_BASE_URL = "https://api.perplexity.ai/v1"
PERPLEXITY_CLAUDE_MODEL = "anthropic/claude-sonnet-4-6"
PERPLEXITY_FALLBACK_MODEL = "sonar-pro"

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


def analyze_portfolio(positions: dict[str, Any]) -> dict[str, Any]:
    """Create a deterministic portfolio-first research plan without an extra AI call."""
    print("[Analysis] Building portfolio research plan...")
    holdings = positions.get("positions", [])
    risk_holdings = [position for position in holdings if _is_risk_focus(position)]
    core_holdings = [position for position in holdings if not _is_cash_equivalent_position(position)]
    ranked = sorted(
        core_holdings,
        key=lambda item: (
            _is_risk_focus(item),
            float(item.get("weight_pct", 0.0)),
            abs(float(item.get("pnl_pct", 0.0))),
        ),
        reverse=True,
    )
    focus_positions = ranked[:5] or holdings[:5]

    focus_symbols = [str(position.get("symbol", "UNKNOWN")) for position in focus_positions]
    focus_themes = _build_focus_themes(focus_positions)
    risk_flags = _build_portfolio_flags(holdings)
    news_questions = _build_news_questions(focus_positions, risk_flags)

    return {
        "portfolio_view": _build_portfolio_view(positions, focus_positions, risk_flags),
        "focus_symbols": focus_symbols[:5],
        "focus_themes": focus_themes[:6],
        "risk_flags": risk_flags[:6],
        "news_questions": news_questions[:6],
    }


def generate_analysis(
    positions: dict[str, Any],
    research_plan: dict[str, Any],
    market_context: str,
) -> str:
    """Generate the final daily recommendation using targeted portfolio research."""
    print("[Analysis] Starting final portfolio analysis...")

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
- 不要写套话，不要写“根据搜索结果”，不要写输入里没有的新新闻"""

    return _run_primary_model(FINAL_SYSTEM_PROMPT, prompt, max_output_tokens=1800)


def _run_primary_model(system_prompt: str, user_prompt: str, max_output_tokens: int) -> str:
    """Run the preferred model stack: Perplexity Claude -> direct Claude -> Perplexity Sonar."""
    perplexity_key = os.getenv("PERPLEXITY_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")

    if perplexity_key:
        try:
            result = _run_with_perplexity_responses(
                api_key=perplexity_key,
                model=PERPLEXITY_CLAUDE_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=max_output_tokens,
            )
            print("[Analysis] Perplexity Claude completed.")
            return result
        except Exception as exc:
            print(f"[Analysis] Perplexity Claude failed: {exc}")

    if anthropic_key:
        try:
            result = _run_with_anthropic(
                api_key=anthropic_key,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=max_output_tokens,
            )
            print("[Analysis] Direct Claude completed.")
            return result
        except Exception as exc:
            print(f"[Analysis] Direct Claude failed: {exc}")

    if perplexity_key:
        try:
            result = _run_with_perplexity_chat(
                api_key=perplexity_key,
                model=PERPLEXITY_FALLBACK_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            print("[Analysis] Perplexity Sonar fallback completed.")
            return result
        except Exception as exc:
            print(f"[Analysis] Perplexity Sonar fallback failed: {exc}")

    return "分析生成失败：请检查 Perplexity 或 Claude API 配置。"


def _run_with_perplexity_responses(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
) -> str:
    """Call Perplexity Agent API with a third-party model."""
    http_client = httpx.Client(
        base_url=PERPLEXITY_AGENT_BASE_URL,
        timeout=90.0,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )
    client = OpenAI(
        api_key=api_key,
        base_url=PERPLEXITY_AGENT_BASE_URL,
        timeout=90.0,
        http_client=http_client,
    )
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_output_tokens=max_output_tokens,
    )
    text = _extract_response_text(response)
    if not text:
        raise ValueError("Empty text returned from Perplexity responses API")
    return text


def _run_with_anthropic(
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
) -> str:
    """Call Anthropic directly as a secondary fallback."""
    client = Anthropic(api_key=api_key, timeout=40)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_output_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    result = "\n".join(text_blocks).strip()
    if not result:
        raise ValueError("Empty text returned from Anthropic")
    return result


def _run_with_perplexity_chat(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> str:
    """Call Perplexity chat completions as a final fallback."""
    client = get_openai_compatible_client(api_key, "https://api.perplexity.ai")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise ValueError("Empty text returned from Perplexity chat completions")
    return content.strip()


def _extract_response_text(response: Any) -> str:
    """Read text safely from an OpenAI-style responses API object."""
    output_text = getattr(response, "output_text", "")
    if output_text:
        return str(output_text).strip()

    fragments: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", "")
            if text:
                fragments.append(str(text))
    return "\n".join(fragment.strip() for fragment in fragments if fragment.strip()).strip()


def _build_portfolio_payload(positions: dict[str, Any]) -> dict[str, Any]:
    """Build a stable portfolio payload for research and writing."""
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
        "portfolio_flags": _build_portfolio_flags(holdings),
        "top_holdings": _build_top_holdings(holdings, base_currency),
    }


def _build_market_facts(market_context: str) -> dict[str, list[str]]:
    """Extract cleaner market facts from the multi-source market context text."""
    sections = {
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


def _is_risk_focus(position: dict[str, Any]) -> bool:
    """Identify holdings that deserve extra research priority."""
    weight_pct = float(position.get("weight_pct", 0.0))
    pnl_pct = float(position.get("pnl_pct", 0.0))
    side = str(position.get("side", "Long")).strip().lower()
    return pnl_pct <= -10 or weight_pct >= 20 or side == "short"


def _build_focus_themes(focus_positions: list[dict[str, Any]]) -> list[str]:
    """Map the current holdings into the most relevant research themes."""
    themes: list[str] = []

    for position in focus_positions:
        symbol = str(position.get("symbol", "")).upper()
        asset_category = str(position.get("asset_category", "")).upper()
        currency = str(position.get("currency", "")).upper()
        description = str(position.get("description", "")).upper()

        if symbol in {"AAPL", "QQQ", "JEPQ", "NVDA", "MSFT"}:
            themes.append("美股科技与纳斯达克风险偏好")
        if symbol in {"700", "3416"} or currency == "HKD":
            themes.append("港股风险偏好与中国互联网/高股息情绪")
        if asset_category == "OPT":
            themes.append("期权到期与波动率风险")
        if symbol in {"SGOV", "BIL", "SHV", "JPST"} or "TREASURY" in description:
            themes.append("美联储路径与短端利率")
        if currency == "USD":
            themes.append("美元利率与美元资产表现")

    return _dedupe_strings(themes)[:6]


def _build_news_questions(focus_positions: list[dict[str, Any]], risk_flags: list[str]) -> list[str]:
    """Generate targeted news questions without using an extra model call."""
    questions: list[str] = []

    for position in focus_positions:
        symbol = str(position.get("symbol", "UNKNOWN"))
        side = str(position.get("side", "Long")).strip().lower()
        asset_category = str(position.get("asset_category", "")).upper()

        questions.append(f"{symbol} 最近 72 小时有哪些最可能影响股价或估值的消息？")
        if asset_category == "OPT":
            questions.append(f"{symbol} 距到期前最关键的标的价格、波动率或事件风险是什么？")
        if side == "short":
            questions.append(f"{symbol} 这类 short 仓位现在最需要防范的反向风险是什么？")

    if any("利率" in flag or "仓位" in flag for flag in risk_flags):
        questions.append("美联储、10年美债和美元最近的变化，哪个最可能影响这份组合？")
    if any("港" in position.get("currency", "") or position.get("symbol", "") in {"700", "3416"} for position in focus_positions):
        questions.append("港股互联网与高股息相关资产最近的情绪和催化剂是什么？")

    return _dedupe_strings(questions)[:6]


def _build_portfolio_view(
    positions: dict[str, Any],
    focus_positions: list[dict[str, Any]],
    risk_flags: list[str],
) -> str:
    """Create a short plain-language summary of the portfolio state."""
    total_value = float(positions.get("total_value", 0.0))
    cash_pct = float(positions.get("cash_pct", 0.0))
    daily_return_pct = float(positions.get("daily_return_pct", 0.0))
    biggest = focus_positions[0].get("symbol", "核心持仓") if focus_positions else "核心持仓"

    if risk_flags:
        return (
            f"总资产约 {total_value:,.0f}，单日回报 {daily_return_pct:+.1f}%，"
            f"现金 {cash_pct:.1f}%，当前最需要盯 {biggest} 和已触发的风险位。"
        )
    return (
        f"总资产约 {total_value:,.0f}，单日回报 {daily_return_pct:+.1f}%，"
        f"现金 {cash_pct:.1f}%，当前主要波动来自 {biggest}。"
    )


def _dedupe_strings(values: list[str]) -> list[str]:
    """Preserve order while removing duplicate strings."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
