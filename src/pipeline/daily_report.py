"""Daily report pipeline — orchestrates all five stages of the automated brief."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.analysis.market_context import build_market_context
from src.core.analysis.portfolio_context import (
    build_ibkr_analysis_payload,
    build_mock_ibkr_analysis_payload,
)
from src.core.analysis.portfolio_market_analysis import build_analysis
from src.core.analysis.position_analysis import build_research_plan, normalize_portfolio
from src.core.providers.ibkr_client import get_ibkr_positions, get_ibkr_statement_xml
from src.interface.telegram.brief_builder import (
    MarketSnapshot,
    PORTFOLIO_NEWS_FALLBACK,
    NEWS_MARKET_FALLBACK,
    build_analysis_news_context,
    build_daily_brief,
    build_news_flash,
    build_portfolio_snapshot,
    clean_for_telegram,
    normalize_analysis,
    normalize_market_text,
)
from src.interface.telegram.html_report import write_daily_report
from src.interface.telegram.notify import send_telegram, send_telegram_document


# ---------------------------------------------------------------------------
# Full pipeline (daily report)
# ---------------------------------------------------------------------------


def run_daily_report_pipeline(
    test_mode: bool = False,
    output_dir: Path | None = None,
) -> tuple[str, Path]:
    """Run all five stages and return (telegram_message, html_report_path).

    Stages:
    1. Fetch IBKR portfolio
    2. Build portfolio research plan
    3. Fetch targeted market intelligence
    4. Generate AI analysis
    5. Build HTML report and Telegram message
    """
    positions = _stage_fetch_portfolio(test_mode)
    research_plan = _stage_build_research_plan(positions)
    market = _stage_fetch_market_context(research_plan, positions)
    analysis = _stage_generate_analysis(positions, research_plan, market)
    message = build_daily_brief(market, positions, analysis)
    report_path = _stage_write_html_report(analysis, market, positions, research_plan, output_dir)
    return message, report_path


# ---------------------------------------------------------------------------
# News-only pipeline
# ---------------------------------------------------------------------------


def run_news_only_pipeline() -> str:
    """Fetch market context and return a formatted Telegram news flash."""
    market = _stage_fetch_market_context()
    return build_news_flash(market)


# ---------------------------------------------------------------------------
# IBKR-only pipeline
# ---------------------------------------------------------------------------


def run_ibkr_snapshot_pipeline(test_mode: bool = False) -> str:
    """Fetch portfolio data and return a formatted Telegram snapshot."""
    positions = _stage_fetch_portfolio(test_mode)
    return build_portfolio_snapshot(positions)


def run_ibkr_payload_pipeline(test_mode: bool = False) -> dict[str, Any]:
    """Fetch IBKR data and return an analysis-ready JSON payload."""
    print("[Pipeline] Step 1/1: Fetching IBKR analysis payload...")
    if test_mode:
        print("[Pipeline] Using mock portfolio payload for test mode.")
        return build_mock_ibkr_analysis_payload()

    xml_text = get_ibkr_statement_xml()
    if not xml_text:
        return build_mock_ibkr_analysis_payload()
    return build_ibkr_analysis_payload(xml_text)


# ---------------------------------------------------------------------------
# Delivery helpers
# ---------------------------------------------------------------------------


def deliver_report(message: str, report_path: Path) -> None:
    """Send the HTML report and (if needed) the Telegram message."""
    print(f"[Pipeline] Sending HTML report: {report_path}")
    document_sent = send_telegram_document(
        report_path,
        caption="今晚的详尽版报告已附上，建议直接用手机打开 HTML 查看。",
    )
    if not document_sent:
        raise RuntimeError("Telegram document delivery failed")


def deliver_message(message: str) -> None:
    """Send a plain-text Telegram message."""
    sent = send_telegram(message)
    if not sent:
        raise RuntimeError("Telegram delivery failed")


def deliver_failure_alert(exc: Exception, elapsed: float) -> None:
    """Send a failure notification to Telegram."""
    error_message = (
        f"❌ 每日投资简报运行失败 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"错误信息：{str(exc)[:3500]}\n"
        f"耗时：{elapsed:.2f} 秒"
    )
    send_telegram(error_message)


# ---------------------------------------------------------------------------
# Mock data for test mode
# ---------------------------------------------------------------------------


def get_mock_positions() -> dict[str, Any]:
    """Return test-mode portfolio data (no IBKR call required)."""
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


# ---------------------------------------------------------------------------
# Stage implementations (private)
# ---------------------------------------------------------------------------


def _stage_fetch_portfolio(test_mode: bool) -> dict[str, Any]:
    print("[Pipeline] Step 1/5: Fetching portfolio snapshot...")
    if test_mode:
        print("[Pipeline] Using mock positions for test mode.")
        return normalize_portfolio(get_mock_positions())
    return normalize_portfolio(get_ibkr_positions())


def _stage_build_research_plan(positions: dict[str, Any]) -> dict[str, Any]:
    print("[Pipeline] Step 2/5: Building portfolio research plan...")
    return build_research_plan(positions)


def _stage_fetch_market_context(
    research_plan: dict[str, Any] | None = None,
    positions: dict[str, Any] | None = None,
) -> MarketSnapshot:
    print("[Pipeline] Step 3/5: Fetching targeted market intelligence...")
    raw = build_market_context(research_plan=research_plan, positions=positions)
    return MarketSnapshot(
        brief=normalize_market_text(raw.brief, NEWS_MARKET_FALLBACK),
        macro=raw.macro,
        portfolio_news=normalize_market_text(raw.portfolio_news, PORTFOLIO_NEWS_FALLBACK),
        sentiment=raw.sentiment,
    )


def _stage_generate_analysis(
    positions: dict[str, Any],
    research_plan: dict[str, Any],
    market: MarketSnapshot,
) -> str:
    print("[Pipeline] Step 4/5: Generating final investment analysis...")
    news_context = build_analysis_news_context(market)
    return build_analysis(positions, research_plan, news_context)


def _stage_write_html_report(
    analysis: str,
    market: MarketSnapshot,
    positions: dict[str, Any],
    research_plan: dict[str, Any],
    output_dir: Path | None,
) -> Path:
    print("[Pipeline] Step 5/5: Building detailed HTML report...")
    out = output_dir or Path(__file__).parent.parent.parent / "reports"
    return write_daily_report(
        analysis=normalize_analysis(analysis),
        market={
            "brief": clean_for_telegram(market.brief),
            "macro": clean_for_telegram(market.macro),
            "portfolio_news": clean_for_telegram(market.portfolio_news),
            "sentiment": clean_for_telegram(market.sentiment),
        },
        positions=positions,
        research=research_plan,
        output_dir=out,
    )
