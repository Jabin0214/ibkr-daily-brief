"""Entry point for the IBKR daily investment brief workflow."""

from __future__ import annotations

import argparse
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.claude_analysis import generate_analysis
from src.grok_news import get_market_news
from src.ibkr_data import get_ibkr_positions
from src.notify import send_telegram, send_telegram_document
from src.perplexity_macro import get_macro_data, get_market_brief
from src.reporting import write_daily_report

NEWS_MARKET_FALLBACK = (
    "市场主线暂时不完整，但当前可确认的重点仍是："
    "央行路径、油价与地缘风险、以及科技股风险偏好的变化。"
)
BAD_SOURCE_MARKERS = (
    "sina",
    "eastmoney",
    "cls",
    "wallstreetcn",
    "stcn",
    "10jqka",
    "moomoo.com/hans",
    "lets-gold.net",
)
BAD_TEXT_MARKERS = (
    "根据搜索结果",
    "我能提供的最新",
    "市场主线",
    "科技与个股",
    "今晚关注",
    "链接：",
)


@dataclass
class MarketContext:
    """Structured market inputs used by the daily workflow."""

    brief: str
    macro: str
    sentiment: str


def main() -> int:
    """Run the daily investment brief workflow."""
    load_dotenv(Path(__file__).with_name(".env"))
    args = _parse_args()
    start_time = time.perf_counter()

    print("=== 开始每日投资简报 ===")
    print(f"[Main] Test mode: {args.test}")
    print(f"[Main] News-only mode: {args.news_only}")
    print(f"[Main] Send mode: {args.send}")

    try:
        market = _fetch_market_context()

        if args.news_only:
            news_flash = _build_news_flash(market)
            _emit_output(news_flash, args.send, "news flash")
            _print_runtime(start_time, _estimate_news_cost())
            return 0

        positions = _fetch_portfolio(args.test)
        analysis = _generate_investment_analysis(market, positions)
        final_message = _build_daily_brief(market, positions, analysis)
        report_path = _write_detailed_report(analysis, market, positions)

        _emit_output(final_message, args.send, "daily brief", report_path=report_path)
        _print_runtime(start_time, _estimate_cost())
        return 0
    except Exception as exc:
        return _handle_failure(exc, start_time)


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="IBKR Daily Brief")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Use mock IBKR positions while still calling external news and analysis APIs.",
    )
    parser.add_argument(
        "--news-only",
        action="store_true",
        help="Only fetch and print the daily market news flash from Grok and Perplexity.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send the generated output to Telegram.",
    )
    return parser.parse_args()


def _fetch_market_context() -> MarketContext:
    """Fetch market brief, macro data, and X sentiment in parallel."""
    print("[Main] Step 1/4: Fetching market intelligence...")
    with ThreadPoolExecutor(max_workers=3) as executor:
        brief_future = executor.submit(get_market_brief)
        macro_future = executor.submit(get_macro_data)
        sentiment_future = executor.submit(get_market_news)
        return MarketContext(
            brief=_normalize_market_text(brief_future.result(), NEWS_MARKET_FALLBACK),
            macro=macro_future.result(),
            sentiment=sentiment_future.result(),
        )


def _fetch_portfolio(test_mode: bool) -> dict[str, Any]:
    """Fetch live or mock portfolio data."""
    print("[Main] Step 2/4: Fetching portfolio snapshot...")
    if test_mode:
        print("[Main] Using mock positions for test mode.")
        return _normalize_portfolio(_get_test_positions())
    return _normalize_portfolio(get_ibkr_positions())


def _generate_investment_analysis(market: MarketContext, positions: dict[str, Any]) -> str:
    """Generate the final investment analysis from market and portfolio inputs."""
    print("[Main] Step 3/4: Generating investment analysis...")
    news_context = _build_analysis_news_context(market)
    return generate_analysis(news_context, positions)


def _emit_output(message: str, send: bool, label: str, report_path: Path | None = None) -> None:
    """Print the message and optionally send it to Telegram."""
    if report_path is not None:
        print(f"[Main] Detailed report saved to: {report_path}")
    else:
        print(message)
    if not send:
        if report_path is None:
            return
        print(message)
        return

    print(f"[Main] Step 4/4: Sending {label} to Telegram...")
    if report_path is not None:
        document_sent = send_telegram_document(
            report_path,
            caption="今晚的详尽版报告已附上，建议直接用手机打开 HTML 查看。",
        )
        if not document_sent:
            raise RuntimeError("Telegram document delivery failed")
        return

    sent = send_telegram(message)
    if not sent:
        raise RuntimeError("Telegram delivery failed")


def _build_analysis_news_context(market: MarketContext) -> str:
    """Build the market context passed into the final analysis model."""
    return (
        "【Perplexity 主新闻】\n"
        f"{market.brief}\n\n"
        "【Perplexity 宏观看板】\n"
        f"{market.macro}\n\n"
        "【Grok X 情绪】\n"
        f"{market.sentiment}"
    )


def _build_daily_brief(market: MarketContext, positions: dict[str, Any], analysis: str) -> str:
    """Build the final Telegram brief with clear business sections."""
    today = datetime.now().strftime("%Y-%m-%d")
    sections = [
        f"📊 每日投资简报 | {today}",
        _build_brief_header(positions),
        _build_daily_highlights(positions),
        _build_market_snapshot(market),
        _build_portfolio_snapshot(positions),
        "🤖 AI 判断\n" + _normalize_analysis(analysis),
    ]
    return "\n\n".join(section.strip() for section in sections if section.strip())


def _build_news_flash(market: MarketContext) -> str:
    """Build a Telegram-friendly market news flash."""
    today = datetime.now().strftime("%Y-%m-%d")
    sections = [
        f"📰 每日新闻快讯 | {today}",
        _build_news_summary(market),
        _build_market_snapshot(market),
    ]
    return "\n\n".join(section.strip() for section in sections if section.strip())


def _build_market_snapshot(market: MarketContext) -> str:
    """Build a compact market snapshot block for the daily brief."""
    brief_lines = _extract_key_lines(market.brief, limit=3)
    macro_lines = _extract_key_lines(market.macro, limit=3)
    sentiment_lines = _extract_key_lines(market.sentiment, limit=2)

    sections = [
        "🌍 市场情报",
        "先看这 3 组信息：",
        _format_section_block("主线新闻", brief_lines, "暂无主线新闻"),
        _format_section_block("宏观看板", macro_lines, "暂无宏观数据"),
        _format_section_block("市场情绪", sentiment_lines, "暂无情绪摘要"),
    ]
    return "\n".join(sections)


def _build_portfolio_snapshot(positions: dict[str, Any]) -> str:
    """Build a compact portfolio snapshot that is always included in the brief."""
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
        f"账户范围：{_format_account_scope(scope, account_id)}",
        f"报表日期：{report_date or '未知'}",
        (
            f"总资产 {total_value:,.2f} {base_currency} | "
            f"现金 {cash:,.2f} ({cash_pct:.1f}%) | "
            f"当日盈亏 {_format_signed_number(daily_pnl)} {base_currency} "
            f"({_format_signed_percent(daily_return_pct)})"
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
        risk_marker = _position_risk_marker(position)
        weight_pct = float(position.get("weight_pct", 0.0))
        net_weight_pct = float(position.get("net_weight_pct", 0.0))
        pnl_pct = float(position.get("pnl_pct", 0.0))
        lines.append(f"{risk_marker} {_format_position_label(position)} | {_describe_position(position)}")

        lines.append(
            "   "
            f"绝对仓位 {weight_pct:.1f}% · 净敞口 {_format_signed_percent(net_weight_pct)} · "
            f"盈亏 {_format_signed_percent(pnl_pct)} · 市值 {market_value_base:,.0f} {base_currency}"
        )

    if len(holdings) > 5:
        lines.append(f"其余 {len(holdings) - 5} 笔持仓已省略，避免消息过长。")
    return "\n".join(lines)


def _build_daily_highlights(positions: dict[str, Any]) -> str:
    """Build a short top-of-message summary for quick morning reading."""
    total_value = float(positions.get("total_value", 0.0))
    cash_pct = float(positions.get("cash_pct", 0.0))
    daily_pnl = float(positions.get("daily_pnl", 0.0))
    daily_return_pct = float(positions.get("daily_return_pct", 0.0))
    holdings = positions.get("positions", [])

    lines = ["⚡ 今日要点"]
    lines.append(
        f"- 账户今天 {_describe_daily_pnl(daily_pnl)}，总资产约 {total_value:,.0f}，"
        f"单日回报 {_format_signed_percent(daily_return_pct)}。"
    )
    lines.append(f"- 现金占比 {cash_pct:.1f}%，{_describe_cash_level(cash_pct)}。")

    risk_lines = _build_portfolio_alert_lines(holdings)
    if risk_lines:
        lines.extend(risk_lines)
    else:
        lines.append("- 目前没有看到特别刺眼的止损或仓位过重信号。")

    return "\n".join(lines)


def _position_risk_marker(position: dict[str, Any]) -> str:
    """Return a small marker for positions with obvious risk flags."""
    pnl_pct = float(position.get("pnl_pct", 0.0))
    weight_pct = float(position.get("weight_pct", 0.0))
    if pnl_pct <= -20:
        return "🚨"
    if pnl_pct <= -15 or (weight_pct >= 30 and not _is_cash_equivalent_position(position)):
        return "⚠️"
    return "•"


def _build_portfolio_alert_lines(holdings: list[dict[str, Any]]) -> list[str]:
    """Build concise portfolio alerts for stop-loss and concentration risks."""
    alerts: list[str] = []

    for position in holdings:
        symbol = position.get("symbol", "UNKNOWN")
        pnl_pct = float(position.get("pnl_pct", 0.0))
        weight_pct = float(position.get("weight_pct", 0.0))

        if pnl_pct <= -20:
            alerts.append(f"- 🚨 {symbol} 已亏损 {_format_signed_percent(pnl_pct)}，这已经是很重的回撤。")
        elif pnl_pct <= -15:
            alerts.append(f"- ⚠️ {symbol} 已亏损 {_format_signed_percent(pnl_pct)}，已经接近你的止损纪律。")
        if weight_pct >= 30 and not _is_cash_equivalent_position(position):
            alerts.append(f"- ⚠️ {symbol} 仓位 {weight_pct:.1f}%，已经接近或超过单仓上限。")

    return alerts[:4]


def _get_test_positions() -> dict[str, Any]:
    """Return test-mode portfolio data."""
    return {
        "account_id": "TEST",
        "scope": "mock",
        "base_currency": "USD",
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "positions": [
            {
                "symbol": "TSLA",
                "description": "TESLA INC",
                "currency": "USD",
                "quantity": 100,
                "side": "Long",
                "asset_category": "STK",
                "avg_cost": 220.0,
                "current_price": 185.0,
                "pnl_pct": -15.9,
                "market_value": 18500.0,
                "market_value_base": 18500.0,
            },
            {
                "symbol": "AAPL",
                "description": "APPLE INC",
                "currency": "USD",
                "quantity": 50,
                "side": "Long",
                "asset_category": "STK",
                "avg_cost": 190.0,
                "current_price": 198.0,
                "pnl_pct": 4.21,
                "market_value": 9900.0,
                "market_value_base": 9900.0,
            },
        ],
        "cash": 5000.0,
        "total_value": 33400.0,
        "daily_pnl": -340.0,
        "cash_pct": 14.97,
    }


def _handle_failure(exc: Exception, start_time: float) -> int:
    """Send a failure alert and return a failing exit code."""
    elapsed = time.perf_counter() - start_time
    error_message = (
        f"❌ 每日投资简报运行失败 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"错误信息：{str(exc)[:3500]}\n"
        f"耗时：{elapsed:.2f} 秒"
    )
    print(f"[Main] Workflow failed: {exc}")
    send_telegram(error_message)
    return 1


def _write_detailed_report(
    analysis: str,
    market: MarketContext,
    positions: dict[str, Any],
) -> Path:
    """Generate a detailed HTML report for archive and Telegram delivery."""
    print("[Main] Step 4/4: Building detailed HTML report...")
    return write_daily_report(
        analysis=_normalize_analysis(analysis),
        market={
            "brief": _clean_for_telegram(market.brief),
            "macro": _clean_for_telegram(market.macro),
            "sentiment": _clean_for_telegram(market.sentiment),
        },
        positions=positions,
        output_dir=Path(__file__).with_name("reports"),
    )


def _print_runtime(start_time: float, estimated_cost: float) -> None:
    """Print runtime summary."""
    elapsed = time.perf_counter() - start_time
    print(f"[Main] Total runtime: {elapsed:.2f}s")
    print(f"[Main] Estimated cost: {estimated_cost:.2f} USD")


def _estimate_cost() -> float:
    """Return a simple fixed cost estimate for the daily run."""
    grok_estimate = 0.02
    perplexity_estimate = 0.01
    claude_estimate = 0.04
    return grok_estimate + perplexity_estimate + claude_estimate


def _estimate_news_cost() -> float:
    """Return a simple fixed cost estimate for news-only runs."""
    grok_estimate = 0.02
    perplexity_estimate = 0.02
    return grok_estimate + perplexity_estimate


def _clean_for_telegram(text: str) -> str:
    """Remove markdown-like formatting that renders poorly in Telegram plain text."""
    cleaned = text.strip()
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\[[0-9,\s]+\]", "", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = cleaned.replace("**", "")
    cleaned = cleaned.replace("__", "")
    cleaned = cleaned.replace("```", "")
    cleaned = cleaned.replace("根据搜索结果，", "")
    cleaned = cleaned.replace("根据搜索结果", "")
    cleaned = cleaned.replace("链接：", "")
    cleaned = cleaned.replace("来源：", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _normalize_market_text(text: str, fallback: str) -> str:
    """Remove refusal-style language from market blocks and provide a graceful fallback."""
    cleaned = _clean_for_telegram(text)
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


def _extract_key_lines(text: str, limit: int) -> list[str]:
    """Extract the most readable non-empty lines for compact Telegram sections."""
    cleaned = _clean_for_telegram(text)
    raw_lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    lines: list[str] = []

    for line in raw_lines:
        normalized = re.sub(r"^\d+\.\s*", "", line)
        normalized = re.sub(r"^[-•]\s*", "", normalized)
        lowered = normalized.lower()
        if any(marker in lowered for marker in BAD_SOURCE_MARKERS):
            continue
        if any(marker in normalized for marker in BAD_TEXT_MARKERS):
            continue
        if normalized.startswith("说明："):
            continue
        if "暂无可靠最新数据" in normalized:
            continue
        lines.append(f"- {normalized}")
        if len(lines) >= limit:
            break

    return lines


def _normalize_analysis(text: str) -> str:
    """Light cleanup to keep model output readable in Telegram."""
    cleaned = _clean_for_telegram(text)
    cleaned = re.sub(r"^\|\s*.*\|\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.replace("倾向倾向继续持有", "倾向继续持有")
    cleaned = cleaned.replace("减仓至", "更适合逐步减仓至")
    cleaned = cleaned.replace("继续持有", "倾向继续持有")
    cleaned = cleaned.replace("立即警告", "需要重点警惕")
    cleaned = cleaned.replace("暂不加仓", "更适合暂不加仓")
    cleaned = re.sub(r"^\s*市场判断\s*$", "市场判断", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*组合解读\s*$", "\n组合解读", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*风险提醒\s*$", "\n风险提醒", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*今日动作\s*$", "\n今日动作", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def _build_brief_header(positions: dict[str, Any]) -> str:
    """Build a one-screen summary that reads well on Telegram."""
    holdings = positions.get("positions", [])
    top_holding_position = next(
        (position for position in holdings if not _is_cash_equivalent_position(position)),
        holdings[0] if holdings else {},
    )
    top_holding = top_holding_position.get("symbol", "暂无")
    daily_pnl = float(positions.get("daily_pnl", 0.0))
    cash_pct = float(positions.get("cash_pct", 0.0))
    report_date = str(positions.get("report_date", "")).strip()
    lines = [
        "一句话先看：",
        f"- 这份报告基于 {report_date or '最新可用'} 的 IBKR 报表，你的账户今天 {_describe_daily_pnl(daily_pnl)}。",
        f"- 当前仓位感觉：{_describe_cash_level(cash_pct)}，影响最大的持仓是 {top_holding}。",
    ]
    return "\n".join(lines)


def _build_news_summary(market: MarketContext) -> str:
    """Build a simpler summary section for news-only output."""
    news_lines = _extract_key_lines(market.brief, limit=2)
    macro_lines = _extract_key_lines(market.macro, limit=2)
    sentiment_lines = _extract_key_lines(market.sentiment, limit=1)
    combined = news_lines + macro_lines + sentiment_lines
    if not combined:
        combined = ["- 今天的新闻摘要暂时不完整。"]
    return "先看重点：\n" + "\n".join(combined)


def _format_section_block(title: str, lines: list[str], fallback: str) -> str:
    """Format a compact titled block."""
    body = "\n".join(lines) if lines else fallback
    return f"{title}\n{body}"


def _describe_daily_pnl(daily_pnl: float) -> str:
    """Translate daily PnL into plain-language status."""
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
    """Describe cash allocation in plain Chinese."""
    if cash_pct >= 40:
        return "现金很多，整体偏防守"
    if cash_pct >= 25:
        return "现金不低，手上还有腾挪空间"
    if cash_pct >= 10:
        return "现金处于正常区间"
    return "现金偏少，仓位比较满"


def _describe_position(position: dict[str, Any]) -> str:
    """Describe a single holding in plain language."""
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
    local_value_note = ""
    if currency and market_value:
        local_value_note = f"，本币市值 {market_value:,.0f} {currency}"
        if fx_rate and fx_rate != 1:
            local_value_note += f"，汇率 {fx_rate:.4f}"
    return (
        f"{mood}，{side.lower()} {asset_category.lower() or 'position'}，"
        f"成本 {float(position.get('avg_cost', 0.0)):.2f}，现价 {float(position.get('current_price', 0.0)):.2f}"
        f"{local_value_note}"
    )


def _format_signed_percent(value: float) -> str:
    """Format percentage with explicit sign."""
    return f"{value:+.1f}%"


def _format_signed_number(value: float) -> str:
    """Format numeric values with explicit sign."""
    return f"{value:+,.2f}"


def _normalize_portfolio(positions: dict[str, Any]) -> dict[str, Any]:
    """Normalize numeric portfolio fields once so downstream formatting stays simple."""
    total_value = _safe_float(positions.get("total_value", 0.0))
    cash = _safe_float(positions.get("cash", 0.0))
    daily_pnl = _safe_float(positions.get("daily_pnl", 0.0))
    normalized_positions: list[dict[str, Any]] = []

    for raw_position in positions.get("positions", []):
        market_value = _safe_float(raw_position.get("market_value", 0.0))
        market_value_base = _safe_float(raw_position.get("market_value_base", market_value))
        fx_rate_to_base = _safe_float(raw_position.get("fx_rate_to_base", 0.0)) or 1.0
        normalized_position = {
            "symbol": str(raw_position.get("symbol", "UNKNOWN")),
            "description": str(raw_position.get("description", "")),
            "currency": str(raw_position.get("currency", "UNKNOWN")),
            "quantity": _safe_float(raw_position.get("quantity", 0.0)),
            "side": str(raw_position.get("side", "Long")),
            "asset_category": str(raw_position.get("asset_category", "")),
            "account_id": str(raw_position.get("account_id", "")),
            "account_alias": str(raw_position.get("account_alias", "")),
            "avg_cost": _safe_float(raw_position.get("avg_cost", 0.0)),
            "current_price": _safe_float(raw_position.get("current_price", 0.0)),
            "pnl_pct": _safe_float(raw_position.get("pnl_pct", 0.0)),
            "market_value": market_value,
            "market_value_base": market_value_base,
            "cost_basis_money": _safe_float(raw_position.get("cost_basis_money", 0.0)),
            "cost_basis_base": _safe_float(raw_position.get("cost_basis_base", 0.0)),
            "unrealized_pnl": _safe_float(raw_position.get("unrealized_pnl", 0.0)),
            "unrealized_pnl_base": _safe_float(raw_position.get("unrealized_pnl_base", 0.0)),
            "fx_rate_to_base": fx_rate_to_base,
            "account_nav_pct": _safe_float(raw_position.get("account_nav_pct", 0.0)),
            "report_date": str(raw_position.get("report_date", "")),
            "weight_pct": (abs(market_value_base) / total_value * 100) if total_value else 0.0,
            "net_weight_pct": (market_value_base / total_value * 100) if total_value else 0.0,
        }
        normalized_positions.append(normalized_position)

    normalized_positions.sort(key=lambda item: abs(item["market_value_base"]), reverse=True)

    cash_pct = (cash / total_value * 100) if total_value else 0.0
    daily_return_pct = (daily_pnl / total_value * 100) if total_value else 0.0

    return {
        **positions,
        "account_id": str(positions.get("account_id", "")),
        "account_alias": str(positions.get("account_alias", "")),
        "scope": str(positions.get("scope", "")),
        "base_currency": str(positions.get("base_currency", "BASE")),
        "report_date": str(positions.get("report_date", "")),
        "cash": cash,
        "total_value": total_value,
        "daily_pnl": daily_pnl,
        "daily_return_pct": daily_return_pct,
        "cash_pct": cash_pct,
        "positions": normalized_positions,
    }


def _safe_float(value: Any) -> float:
    """Convert mixed numeric inputs into float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_account_scope(scope: str, account_id: str) -> str:
    """Format account scope for a user-facing portfolio snapshot."""
    if scope == "aggregate":
        account_count = len([item for item in account_id.split(",") if item.strip()])
        return f"合并账户视图（{account_count} 个账户）"
    if scope == "single":
        return "单账户视图"
    if scope == "mock":
        return "测试数据"
    return "账户视图"


def _format_position_label(position: dict[str, Any]) -> str:
    """Format a concise holding label with side when needed."""
    symbol = str(position.get("symbol", "UNKNOWN"))
    side = str(position.get("side", "Long")).strip().lower()
    asset_category = str(position.get("asset_category", "")).strip()
    if side == "short":
        return f"{symbol}（Short {asset_category or 'Position'}）"
    if asset_category and asset_category != "STK":
        return f"{symbol}（{asset_category}）"
    return symbol


def _is_cash_equivalent_position(position: dict[str, Any]) -> bool:
    """Identify treasury/cash-like ETFs so they are not treated like risky single-name bets."""
    symbol = str(position.get("symbol", "")).upper()
    description = str(position.get("description", "")).upper()
    return symbol in {"SGOV", "BIL", "SHV", "JPST"} or "TREASURY" in description


if __name__ == "__main__":
    sys.exit(main())
