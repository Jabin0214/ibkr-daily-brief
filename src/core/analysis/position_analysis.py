"""Portfolio-only analysis engine for positions, exposures, and account risk."""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_portfolio(positions: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw IBKR portfolio dict: compute weights, sort by exposure, cast floats."""
    total_value = _safe_float(positions.get("total_value", 0.0))
    cash = _safe_float(positions.get("cash", 0.0))
    daily_pnl = _safe_float(positions.get("daily_pnl", 0.0))
    normalized_positions: list[dict[str, Any]] = []

    for raw in positions.get("positions", []):
        market_value = _safe_float(raw.get("market_value", 0.0))
        market_value_base = _safe_float(raw.get("market_value_base", market_value))
        fx_rate_to_base = _safe_float(raw.get("fx_rate_to_base", 0.0)) or 1.0
        normalized = {
            "symbol": str(raw.get("symbol", "UNKNOWN")),
            "description": str(raw.get("description", "")),
            "currency": str(raw.get("currency", "UNKNOWN")),
            "quantity": _safe_float(raw.get("quantity", 0.0)),
            "side": str(raw.get("side", "Long")),
            "asset_category": str(raw.get("asset_category", "")),
            "account_id": str(raw.get("account_id", "")),
            "account_alias": str(raw.get("account_alias", "")),
            "avg_cost": _safe_float(raw.get("avg_cost", 0.0)),
            "current_price": _safe_float(raw.get("current_price", 0.0)),
            "pnl_pct": _safe_float(raw.get("pnl_pct", 0.0)),
            "market_value": market_value,
            "market_value_base": market_value_base,
            "cost_basis_money": _safe_float(raw.get("cost_basis_money", 0.0)),
            "cost_basis_base": _safe_float(raw.get("cost_basis_base", 0.0)),
            "unrealized_pnl": _safe_float(raw.get("unrealized_pnl", 0.0)),
            "unrealized_pnl_base": _safe_float(raw.get("unrealized_pnl_base", 0.0)),
            "fx_rate_to_base": fx_rate_to_base,
            "account_nav_pct": _safe_float(raw.get("account_nav_pct", 0.0)),
            "report_date": str(raw.get("report_date", "")),
            "weight_pct": (abs(market_value_base) / total_value * 100) if total_value else 0.0,
            "net_weight_pct": (market_value_base / total_value * 100) if total_value else 0.0,
        }
        normalized_positions.append(normalized)

    normalized_positions.sort(key=lambda p: abs(p["market_value_base"]), reverse=True)

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


def build_research_plan(positions: dict[str, Any]) -> dict[str, Any]:
    """Create a deterministic portfolio-first research plan without an extra AI call.

    Identifies focus symbols, themes, risk flags, and targeted news questions
    based purely on holdings data. Output is passed to market context and final
    analysis stages.
    """
    print("[PositionAnalysis] Building portfolio research plan...")
    holdings = positions.get("positions", [])
    core_holdings = [p for p in holdings if not _is_cash_equivalent(p)]
    ranked = sorted(
        core_holdings,
        key=lambda p: (
            _is_risk_focus(p),
            float(p.get("weight_pct", 0.0)),
            abs(float(p.get("pnl_pct", 0.0))),
        ),
        reverse=True,
    )
    focus_positions = ranked[:5] or holdings[:5]

    focus_symbols = [str(p.get("symbol", "UNKNOWN")) for p in focus_positions]
    focus_themes = _build_focus_themes(focus_positions)
    risk_flags = build_portfolio_flags(holdings)
    news_questions = _build_news_questions(focus_positions, risk_flags)

    return {
        "portfolio_view": _build_portfolio_view(positions, focus_positions, risk_flags),
        "focus_symbols": focus_symbols[:5],
        "focus_themes": focus_themes[:6],
        "risk_flags": risk_flags[:6],
        "news_questions": news_questions[:6],
    }


def build_portfolio_flags(holdings: list[dict[str, Any]]) -> list[str]:
    """Create deterministic portfolio risk flags from holdings data.

    Outputs:
    - Deep-drawdown flags (pnl <= -20%)
    - Near-stop-loss flags (pnl <= -15%)
    - Concentration flags (weight >= 30%)
    - Short position direction flags
    """
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

        if weight_pct >= 30 and not _is_cash_equivalent(position):
            flags.append(f"{symbol}: 绝对仓位 {weight_pct:.1f}%，接近或超过单仓上限")

        if side.lower() == "short":
            flags.append(f"{symbol}: 这是 short/卖方仓位，方向风险不能按普通多头理解")

    return flags[:6]


def is_cash_equivalent(position: dict[str, Any]) -> bool:
    """Identify treasury/cash-like ETFs so they are not treated as risky single names."""
    return _is_cash_equivalent(position)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_cash_equivalent(position: dict[str, Any]) -> bool:
    symbol = str(position.get("symbol", "")).upper()
    description = str(position.get("description", "")).upper()
    return symbol in {"SGOV", "BIL", "SHV", "JPST"} or "TREASURY" in description


def _is_risk_focus(position: dict[str, Any]) -> bool:
    weight_pct = float(position.get("weight_pct", 0.0))
    pnl_pct = float(position.get("pnl_pct", 0.0))
    side = str(position.get("side", "Long")).strip().lower()
    return pnl_pct <= -10 or weight_pct >= 20 or side == "short"


def _build_focus_themes(focus_positions: list[dict[str, Any]]) -> list[str]:
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

    return _dedupe(themes)[:6]


def _build_news_questions(
    focus_positions: list[dict[str, Any]],
    risk_flags: list[str],
) -> list[str]:
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
    if any(
        "港" in p.get("currency", "") or p.get("symbol", "") in {"700", "3416"}
        for p in focus_positions
    ):
        questions.append("港股互联网与高股息相关资产最近的情绪和催化剂是什么？")

    return _dedupe(questions)[:6]


def _build_portfolio_view(
    positions: dict[str, Any],
    focus_positions: list[dict[str, Any]],
    risk_flags: list[str],
) -> str:
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


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result
