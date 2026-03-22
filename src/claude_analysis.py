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

RESEARCH_SYSTEM_PROMPT = """你是投资研究助手。

任务顺序：
1. 先读账户与持仓事实
2. 提炼最该研究的持仓、风险和新闻方向
3. 输出严格 JSON，不要解释，不要 markdown，不要额外文字

硬性规则：
- 只能使用输入里已有的数字和持仓
- 不要自己改写百分比
- 绝对仓位看 weight_pct，净敞口看 net_weight_pct
- 如果持仓是 short，必须明确标记为 short
- SGOV / BIL / SHV / JPST 这类现金等价物不应被当成高 beta 个股风险
- focus_symbols 最多 5 个
- focus_themes 最多 6 个
- risk_flags 最多 6 条
- news_questions 最多 6 条"""

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
    """Create a portfolio-first research plan before external news collection."""
    print("[Analysis] Building portfolio research plan...")

    payload = _build_portfolio_payload(positions)
    prompt = f"""下面是已经算好的账户事实。
请先判断这份组合最需要研究哪些持仓、哪些风险、哪些新闻问题。

【账户事实 JSON】
{json.dumps(payload, ensure_ascii=False, indent=2)}

请严格输出 JSON，格式必须为：
{{
  "portfolio_view": "一句话概括组合现在的状态",
  "focus_symbols": ["最该跟踪的代码"],
  "focus_themes": ["最该跟踪的主题"],
  "risk_flags": ["最重要的风险点"],
  "news_questions": ["接下来应重点搜索的问题"]
}}

要求：
- portfolio_view 只写一句话
- focus_symbols 优先放真正影响组合波动的持仓
- news_questions 要能直接拿去搜新闻
- 不要输出 JSON 以外的任何文字"""

    raw = _run_primary_model(RESEARCH_SYSTEM_PROMPT, prompt, max_output_tokens=1200)
    plan = _extract_json_object(raw)

    return {
        "portfolio_view": str(plan.get("portfolio_view", "")).strip(),
        "focus_symbols": _limit_string_list(plan.get("focus_symbols"), 5),
        "focus_themes": _limit_string_list(plan.get("focus_themes"), 6),
        "risk_flags": _limit_string_list(plan.get("risk_flags"), 6),
        "news_questions": _limit_string_list(plan.get("news_questions"), 6),
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


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model text safely."""
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return json.loads(stripped)

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        raise ValueError(f"Could not find JSON object in model response: {stripped[:500]}")
    return json.loads(match.group(0))


def _limit_string_list(value: Any, limit: int) -> list[str]:
    """Normalize arbitrary list-like model output into a bounded string list."""
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


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
