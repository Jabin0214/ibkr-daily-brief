"""Telegram message builder for the daily investment brief."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NEWS_MARKET_FALLBACK = (
    "市场主线暂时不完整，但当前可确认的重点仍是："
    "央行路径、油价与地缘风险、以及科技股风险偏好的变化。"
)
PORTFOLIO_NEWS_FALLBACK = "组合相关资讯暂时不完整，请优先关注核心持仓财报、利率与行业景气变化。"

_BAD_SOURCE_MARKERS = (
    "sina",
    "eastmoney",
    "cls",
    "wallstreetcn",
    "stcn",
    "10jqka",
    "moomoo.com/hans",
    "lets-gold.net",
)
_BAD_TEXT_MARKERS = (
    "根据搜索结果",
    "我能提供的最新",
    "市场主线",
    "科技与个股",
    "今晚关注",
    "链接：",
    "暂无直接新闻",
    "暂无相关新闻",
    "暂无更新",
    "没有可靠事实",
    "无72小时内直接新闻",
    "无可靠最新值",
    "空。",
)

_CASH_EQUIVALENT_SYMBOLS = {"SGOV", "BIL", "SHV", "JPST"}


# ---------------------------------------------------------------------------
# Public data contract
# ---------------------------------------------------------------------------


@dataclass
class MarketSnapshot:
    """Structured market context passed between pipeline stages."""

    brief: str
    macro: str
    portfolio_news: str
    sentiment: str


# ---------------------------------------------------------------------------
# Top-level builders
# ---------------------------------------------------------------------------


def build_daily_brief(market: MarketSnapshot, positions: dict[str, Any], analysis: str) -> str:
    """Assemble the full Telegram daily brief from all pipeline outputs."""
    today = datetime.now().strftime("%Y-%m-%d")
    sections = [
        f"📊 每日投资简报 | {today}",
        _build_brief_header(positions),
        _build_daily_highlights(positions),
        _build_market_snapshot(market),
        _build_portfolio_snapshot(positions),
        "🤖 AI 判断\n" + normalize_analysis(analysis),
    ]
    return "\n\n".join(s.strip() for s in sections if s.strip())


def build_news_flash(market: MarketSnapshot) -> str:
    """Build a Telegram-friendly market news flash (news-only mode)."""
    today = datetime.now().strftime("%Y-%m-%d")
    sections = [
        f"📰 每日新闻快讯 | {today}",
        _build_news_summary(market),
        _build_market_snapshot(market),
    ]
    return "\n\n".join(s.strip() for s in sections if s.strip())


def build_portfolio_snapshot(positions: dict[str, Any]) -> str:
    """Build a compact portfolio snapshot for ibkr-only mode."""
    return _build_portfolio_snapshot(positions)


# ---------------------------------------------------------------------------
# Text normalisation helpers (used by pipeline)
# ---------------------------------------------------------------------------


def normalize_market_text(text: str, fallback: str = NEWS_MARKET_FALLBACK) -> str:
    """Remove refusal-style language and provide a graceful fallback."""
    cleaned = clean_for_telegram(text)
    refusal_markers = (
        "我无法",
        "不能按照您的要求",
        "无法按照您的要求",
        "原因如下",
        "不符合",
        "无法生成",
    )
    if any(m in cleaned for m in refusal_markers):
        return fallback
    return cleaned.strip() or fallback


def clean_for_telegram(text: str) -> str:
    """Strip markdown-like formatting that renders poorly in Telegram plain text."""
    cleaned = text.strip()
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\[[0-9,\s]+\]", "", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("```", "")
    cleaned = cleaned.replace("根据搜索结果，", "").replace("根据搜索结果", "")
    cleaned = cleaned.replace("链接：", "").replace("来源：", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def normalize_analysis(text: str) -> str:
    """Light cleanup to keep model output readable in Telegram."""
    cleaned = clean_for_telegram(text)
    cleaned = re.sub(r"^\|\s*.*\|\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.replace("倾向倾向继续持有", "倾向继续持有")
    cleaned = cleaned.replace("减仓至", "更适合逐步减仓至")
    cleaned = cleaned.replace("继续持有", "倾向继续持有")
    cleaned = cleaned.replace("立即警告", "需要重点警惕")
    cleaned = cleaned.replace("暂不加仓", "更适合暂不加仓")
    cleaned = re.sub(r"^\s*市场判断\s*$", "市场判断", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*相关资讯\s*$", "\n相关资讯", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*组合解读\s*$", "\n组合解读", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*风险提醒\s*$", "\n风险提醒", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*今日动作\s*$", "\n今日动作", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def build_analysis_news_context(market: MarketSnapshot) -> str:
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


# ---------------------------------------------------------------------------
# Section builders (private)
# ---------------------------------------------------------------------------


def _build_brief_header(positions: dict[str, Any]) -> str:
    holdings = positions.get("positions", [])
    top = next(
        (p for p in holdings if not _is_cash_equivalent(p)),
        holdings[0] if holdings else {},
    )
    top_symbol = top.get("symbol", "暂无")
    daily_pnl = float(positions.get("daily_pnl", 0.0))
    cash_pct = float(positions.get("cash_pct", 0.0))
    report_date = str(positions.get("report_date", "")).strip()
    return "\n".join([
        "一句话先看：",
        f"- 这份报告基于 {report_date or '最新可用'} 的 IBKR 报表，你的账户今天 {_describe_daily_pnl(daily_pnl)}。",
        f"- 当前仓位感觉：{_describe_cash_level(cash_pct)}，影响最大的持仓是 {top_symbol}。",
    ])


def _build_daily_highlights(positions: dict[str, Any]) -> str:
    total_value = float(positions.get("total_value", 0.0))
    cash_pct = float(positions.get("cash_pct", 0.0))
    daily_pnl = float(positions.get("daily_pnl", 0.0))
    daily_return_pct = float(positions.get("daily_return_pct", 0.0))
    holdings = positions.get("positions", [])

    lines = [
        "⚡ 今日要点",
        f"- 账户今天 {_describe_daily_pnl(daily_pnl)}，总资产约 {total_value:,.0f}，"
        f"单日回报 {_fmt_signed_pct(daily_return_pct)}。",
        f"- 现金占比 {cash_pct:.1f}%，{_describe_cash_level(cash_pct)}。",
    ]
    alert_lines = _build_portfolio_alert_lines(holdings)
    lines.extend(alert_lines or ["- 目前没有看到特别刺眼的止损或仓位过重信号。"])
    return "\n".join(lines)


def _build_market_snapshot(market: MarketSnapshot) -> str:
    brief_lines = _extract_key_lines(market.brief, limit=3)
    macro_lines = _extract_key_lines(market.macro, limit=3)
    portfolio_lines = _extract_key_lines(market.portfolio_news, limit=4)
    sentiment_lines = _extract_key_lines(market.sentiment, limit=2)

    return "\n".join([
        "🌍 市场情报",
        "先看这 4 组信息：",
        _fmt_section_block("主线新闻", brief_lines, "暂无主线新闻"),
        _fmt_section_block("宏观看板", macro_lines, "暂无宏观数据"),
        _fmt_section_block("组合相关资讯", portfolio_lines, "暂无组合相关资讯"),
        _fmt_section_block("市场情绪", sentiment_lines, "暂无情绪摘要"),
    ])


def _build_portfolio_snapshot(positions: dict[str, Any]) -> str:
    total_value = float(positions.get("total_value", 0.0))
    cash = float(positions.get("cash", 0.0))
    daily_pnl = float(positions.get("daily_pnl", 0.0))
    daily_return_pct = float(positions.get("daily_return_pct", 0.0))
    cash_pct = float(positions.get("cash_pct", 0.0))
    base_currency = positions.get("base_currency", "BASE")
    scope = positions.get("scope", "")
    account_id = positions.get("account_id", "")
    report_date = positions.get("report_date", "")
    holdings = positions.get("positions", [])

    lines = [
        "💼 账户快照",
        f"账户范围：{_fmt_account_scope(scope, account_id)}",
        f"报表日期：{report_date or '未知'}",
        (
            f"总资产 {total_value:,.2f} {base_currency} | "
            f"现金 {cash:,.2f} ({cash_pct:.1f}%) | "
            f"当日盈亏 {_fmt_signed_num(daily_pnl)} {base_currency} "
            f"({_fmt_signed_pct(daily_return_pct)})"
        ),
        "",
        "📌 当前持仓",
        "按绝对仓位排序，先看最影响账户波动的几笔：",
    ]

    if not holdings:
        lines.append("暂无持仓数据")
        return "\n".join(lines)

    for position in holdings[:5]:
        market_value_base = float(position.get("market_value_base", 0.0))
        risk_marker = _risk_marker(position)
        weight_pct = float(position.get("weight_pct", 0.0))
        net_weight_pct = float(position.get("net_weight_pct", 0.0))
        pnl_pct = float(position.get("pnl_pct", 0.0))
        lines.append(f"{risk_marker} {_fmt_position_label(position)} | {_describe_position(position)}")
        lines.append(
            "   "
            f"绝对仓位 {weight_pct:.1f}% · 净敞口 {_fmt_signed_pct(net_weight_pct)} · "
            f"盈亏 {_fmt_signed_pct(pnl_pct)} · 市值 {market_value_base:,.0f} {base_currency}"
        )

    if len(holdings) > 5:
        lines.append(f"其余 {len(holdings) - 5} 笔持仓已省略，避免消息过长。")
    return "\n".join(lines)


def _build_news_summary(market: MarketSnapshot) -> str:
    news_lines = _extract_key_lines(market.brief, limit=2)
    macro_lines = _extract_key_lines(market.macro, limit=2)
    sentiment_lines = _extract_key_lines(market.sentiment, limit=1)
    combined = news_lines + macro_lines + sentiment_lines
    return "先看重点：\n" + ("\n".join(combined) if combined else "- 今天的新闻摘要暂时不完整。")


def _build_portfolio_alert_lines(holdings: list[dict[str, Any]]) -> list[str]:
    alerts: list[str] = []
    for position in holdings:
        symbol = position.get("symbol", "UNKNOWN")
        pnl_pct = float(position.get("pnl_pct", 0.0))
        weight_pct = float(position.get("weight_pct", 0.0))
        if pnl_pct <= -20:
            alerts.append(f"- 🚨 {symbol} 已亏损 {_fmt_signed_pct(pnl_pct)}，这已经是很重的回撤。")
        elif pnl_pct <= -15:
            alerts.append(f"- ⚠️ {symbol} 已亏损 {_fmt_signed_pct(pnl_pct)}，已经接近你的止损纪律。")
        if weight_pct >= 30 and not _is_cash_equivalent(position):
            alerts.append(f"- ⚠️ {symbol} 仓位 {weight_pct:.1f}%，已经接近或超过单仓上限。")
    return alerts[:4]


# ---------------------------------------------------------------------------
# Format helpers (private)
# ---------------------------------------------------------------------------


def _extract_key_lines(text: str, limit: int) -> list[str]:
    cleaned = clean_for_telegram(text)
    raw_lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    lines: list[str] = []
    for line in raw_lines:
        normalized = re.sub(r"^\d+\.\s*", "", line)
        normalized = re.sub(r"^[-•]\s*", "", normalized)
        lowered = normalized.lower()
        if any(m in lowered for m in _BAD_SOURCE_MARKERS):
            continue
        if any(m in normalized for m in _BAD_TEXT_MARKERS):
            continue
        if normalized.startswith("说明：") or "暂无可靠最新数据" in normalized:
            continue
        lines.append(f"- {normalized}")
        if len(lines) >= limit:
            break
    return lines


def _fmt_section_block(title: str, lines: list[str], fallback: str) -> str:
    return f"{title}\n" + ("\n".join(lines) if lines else fallback)


def _risk_marker(position: dict[str, Any]) -> str:
    pnl_pct = float(position.get("pnl_pct", 0.0))
    weight_pct = float(position.get("weight_pct", 0.0))
    if pnl_pct <= -20:
        return "🚨"
    if pnl_pct <= -15 or (weight_pct >= 30 and not _is_cash_equivalent(position)):
        return "⚠️"
    return "•"


def _describe_position(position: dict[str, Any]) -> str:
    pnl_pct = float(position.get("pnl_pct", 0.0))
    side = str(position.get("side", "Long")).strip()
    asset_category = str(position.get("asset_category", "")).strip()
    market_value = float(position.get("market_value", 0.0))
    currency = str(position.get("currency", "")).strip()
    fx_rate = float(position.get("fx_rate_to_base", 0.0))

    if pnl_pct <= -20:
        mood = "回撤很重"
    elif pnl_pct <= -8:
        mood = "偏弱"
    elif pnl_pct >= 15:
        mood = "表现很强"
    elif pnl_pct > 0:
        mood = "小幅盈利"
    else:
        mood = "接近平盘"

    local_note = ""
    if currency and market_value:
        local_note = f"，本币市值 {market_value:,.0f} {currency}"
        if fx_rate and fx_rate != 1:
            local_note += f"，汇率 {fx_rate:.4f}"

    return (
        f"{mood}，{side.lower()} {asset_category.lower() or 'position'}，"
        f"成本 {float(position.get('avg_cost', 0.0)):.2f}，"
        f"现价 {float(position.get('current_price', 0.0)):.2f}"
        f"{local_note}"
    )


def _describe_daily_pnl(daily_pnl: float) -> str:
    if daily_pnl >= 1000:
        return f"明显赚钱（+{daily_pnl:,.0f}）"
    if daily_pnl > 0:
        return f"小幅赚钱（+{daily_pnl:,.0f}）"
    if daily_pnl <= -1000:
        return f"回撤较明显（{daily_pnl:,.0f}）"
    if daily_pnl < 0:
        return f"小幅回撤（{daily_pnl:,.0f}）"
    return "基本走平"


def _describe_cash_level(cash_pct: float) -> str:
    if cash_pct >= 40:
        return "现金很多，整体偏防守"
    if cash_pct >= 25:
        return "现金不低，手上还有腾挪空间"
    if cash_pct >= 10:
        return "现金处于正常区间"
    return "现金偏少，仓位比较满"


def _fmt_signed_pct(value: float) -> str:
    return f"{value:+.1f}%"


def _fmt_signed_num(value: float) -> str:
    return f"{value:+,.2f}"


def _fmt_account_scope(scope: str, account_id: str) -> str:
    if scope == "aggregate":
        count = len([x for x in account_id.split(",") if x.strip()])
        return f"合并账户视图（{count} 个账户）"
    if scope == "single":
        return "单账户视图"
    if scope == "mock":
        return "测试数据"
    return "账户视图"


def _fmt_position_label(position: dict[str, Any]) -> str:
    symbol = str(position.get("symbol", "UNKNOWN"))
    side = str(position.get("side", "Long")).strip().lower()
    asset_category = str(position.get("asset_category", "")).strip()
    if side == "short":
        return f"{symbol}（Short {asset_category or 'Position'}）"
    if asset_category and asset_category != "STK":
        return f"{symbol}（{asset_category}）"
    return symbol


def _is_cash_equivalent(position: dict[str, Any]) -> bool:
    symbol = str(position.get("symbol", "")).upper()
    description = str(position.get("description", "")).upper()
    return symbol in _CASH_EQUIVALENT_SYMBOLS or "TREASURY" in description
