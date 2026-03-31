"""Middleware for extracting analysis-ready signals from IBKR Flex statements."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Any

from src.core.providers.ibkr_client import _mock_portfolio_data, _parse_ibkr_date, _parse_portfolio_xml, _to_float


def build_ibkr_analysis_payload(xml_text: str) -> dict[str, Any]:
    """Build an analysis-ready payload from an IBKR Flex statement XML string."""
    root = ET.fromstring(xml_text)
    statements = root.findall(".//FlexStatement")
    portfolio = _normalize_portfolio(_parse_portfolio_xml(xml_text))
    fx_rates = _extract_conversion_rates(root)

    account_summaries = [_build_account_summary(statement) for statement in statements]
    cash_balances = _extract_cash_balances(statements)
    trades = _extract_trades(statements)
    cash_transactions = _extract_cash_transactions(statements, portfolio.get("base_currency", "BASE"), fx_rates)
    option_events = _extract_option_events(statements)

    return {
        "meta": {
            "report_date": portfolio.get("report_date", ""),
            "base_currency": portfolio.get("base_currency", "BASE"),
            "scope": portfolio.get("scope", "single"),
            "account_count": len(statements),
            "accounts": account_summaries,
            "sections": _detect_sections(statements),
        },
        "portfolio": {
            "account_id": portfolio.get("account_id", ""),
            "account_alias": portfolio.get("account_alias", ""),
            "base_currency": portfolio.get("base_currency", "BASE"),
            "total_value": portfolio.get("total_value", 0.0),
            "cash": portfolio.get("cash", 0.0),
            "cash_pct": portfolio.get("cash_pct", 0.0),
            "daily_pnl": portfolio.get("daily_pnl", 0.0),
            "daily_return_pct": portfolio.get("daily_return_pct", 0.0),
        },
        "holdings": portfolio.get("positions", []),
        "cash_balances": cash_balances,
        "trades": trades,
        "cash_transactions": cash_transactions,
        "option_events": option_events,
        "fx_rates": fx_rates,
        "insights": {
            "counts": {
                "holdings": len(portfolio.get("positions", [])),
                "cash_balances": len(cash_balances),
                "trades": len(trades),
                "cash_transactions": len(cash_transactions),
                "option_events": len(option_events),
                "fx_rates": len(fx_rates),
            },
            "concentration": _build_concentration_snapshot(portfolio.get("positions", [])),
            "risk_flags": _build_risk_flags(portfolio.get("positions", []), option_events),
            "cash_flow_summary": _summarize_cash_transactions(cash_transactions, portfolio.get("base_currency", "BASE")),
            "recent_activity": _summarize_recent_activity(trades, option_events),
        },
    }


def build_mock_ibkr_analysis_payload() -> dict[str, Any]:
    """Return a payload with only portfolio data when live XML is unavailable."""
    portfolio = _normalize_portfolio(_mock_portfolio_data())
    return {
        "meta": {
            "report_date": portfolio.get("report_date", ""),
            "base_currency": portfolio.get("base_currency", "BASE"),
            "scope": portfolio.get("scope", "mock"),
            "account_count": 1,
            "accounts": [
                {
                    "account_id": portfolio.get("account_id", "MOCK"),
                    "account_alias": portfolio.get("account_alias", ""),
                    "report_date": portfolio.get("report_date", ""),
                }
            ],
            "sections": {},
        },
        "portfolio": {
            "account_id": portfolio.get("account_id", ""),
            "account_alias": portfolio.get("account_alias", ""),
            "base_currency": portfolio.get("base_currency", "BASE"),
            "total_value": portfolio.get("total_value", 0.0),
            "cash": portfolio.get("cash", 0.0),
            "cash_pct": portfolio.get("cash_pct", 0.0),
            "daily_pnl": portfolio.get("daily_pnl", 0.0),
            "daily_return_pct": portfolio.get("daily_return_pct", 0.0),
        },
        "holdings": portfolio.get("positions", []),
        "cash_balances": [],
        "trades": [],
        "cash_transactions": [],
        "option_events": [],
        "fx_rates": [],
        "insights": {
            "counts": {
                "holdings": len(portfolio.get("positions", [])),
                "cash_balances": 0,
                "trades": 0,
                "cash_transactions": 0,
                "option_events": 0,
                "fx_rates": 0,
            },
            "concentration": _build_concentration_snapshot(portfolio.get("positions", [])),
            "risk_flags": _build_risk_flags(portfolio.get("positions", []), []),
            "cash_flow_summary": _summarize_cash_transactions([], portfolio.get("base_currency", "BASE")),
            "recent_activity": _summarize_recent_activity([], []),
        },
    }


def _build_account_summary(statement: ET.Element) -> dict[str, Any]:
    report_dates: list[str] = []
    for node in statement.findall(".//*[@reportDate]"):
        parsed = _parse_ibkr_date(node.attrib.get("reportDate"))
        if parsed is not None:
            report_dates.append(parsed.isoformat())
    return {
        "account_id": statement.attrib.get("accountId", "UNKNOWN"),
        "account_alias": statement.attrib.get("acctAlias", ""),
        "from_date": _normalize_date_text(statement.attrib.get("fromDate")),
        "to_date": _normalize_date_text(statement.attrib.get("toDate")),
        "report_date": max(report_dates) if report_dates else "",
    }


def _extract_cash_balances(statements: list[ET.Element]) -> list[dict[str, Any]]:
    balances: list[dict[str, Any]] = []
    for statement in statements:
        account_id = statement.attrib.get("accountId", "UNKNOWN")
        account_alias = statement.attrib.get("acctAlias", "")
        for row in statement.findall(".//CashReportCurrency"):
            currency = row.attrib.get("currency", "").strip()
            if not currency:
                continue
            balances.append(
                {
                    "account_id": account_id,
                    "account_alias": account_alias,
                    "currency": currency,
                    "starting_cash": _to_float(row.attrib.get("startingCash")),
                    "ending_cash": _first_present_float(
                        row.attrib.get("endingCash"),
                        row.attrib.get("totalCashValue"),
                        row.attrib.get("settledCash"),
                    ),
                    "commissions": _to_float(row.attrib.get("commissions")),
                    "dividends": _to_float(row.attrib.get("dividends")),
                    "taxes": _to_float(row.attrib.get("withholdingTax")),
                    "interest": _to_float(row.attrib.get("interest")),
                    "report_date": _normalize_date_text(row.attrib.get("reportDate")),
                }
            )
    return balances


def _extract_trades(statements: list[ET.Element]) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    for statement in statements:
        account_id = statement.attrib.get("accountId", "UNKNOWN")
        account_alias = statement.attrib.get("acctAlias", "")
        for row in statement.findall(".//Trades/*"):
            record = {
                "account_id": account_id,
                "account_alias": account_alias,
                "symbol": _first_present_text(row.attrib, "symbol", "underlyingSymbol"),
                "description": row.attrib.get("description", ""),
                "asset_category": row.attrib.get("assetCategory", ""),
                "currency": row.attrib.get("currency", ""),
                "action": _first_present_text(row.attrib, "buySell", "side"),
                "quantity": _first_present_float(
                    row.attrib.get("quantity"),
                    row.attrib.get("tradeQuantity"),
                    row.attrib.get("ibCommissionQuantity"),
                ),
                "trade_price": _first_present_float(
                    row.attrib.get("tradePrice"),
                    row.attrib.get("price"),
                    row.attrib.get("tradePriceMultiplier"),
                ),
                "proceeds": _first_present_float(
                    row.attrib.get("netCash"),
                    row.attrib.get("proceeds"),
                ),
                "commission": _to_float(row.attrib.get("ibCommission")),
                "trade_date": _normalize_date_text(_first_present_text(row.attrib, "tradeDate", "dateTime")),
                "trade_time": _normalize_time_text(_first_present_text(row.attrib, "tradeTime", "dateTime")),
                "order_id": _first_present_text(row.attrib, "ibOrderID", "orderID"),
            }
            if record["symbol"] or record["quantity"] or record["proceeds"]:
                trades.append(record)
    return trades


def _extract_cash_transactions(
    statements: list[ET.Element],
    base_currency: str,
    fx_rates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rate_lookup = _build_fx_lookup(fx_rates)
    transactions: list[dict[str, Any]] = []
    for statement in statements:
        account_id = statement.attrib.get("accountId", "UNKNOWN")
        account_alias = statement.attrib.get("acctAlias", "")
        for row in statement.findall(".//CashTransactions/*"):
            currency = row.attrib.get("currency", "")
            report_date = _normalize_date_text(_first_present_text(row.attrib, "reportDate", "dateTime"))
            amount = _first_present_float(
                row.attrib.get("amount"),
                row.attrib.get("amountInBase"),
                row.attrib.get("netCash"),
            )
            amount_base = _amount_in_base(amount, currency, base_currency, report_date, rate_lookup)
            description = _first_present_text(row.attrib, "description", "type", "transactionType")
            category = _classify_cash_transaction(description, row.attrib)
            record = {
                "account_id": account_id,
                "account_alias": account_alias,
                "currency": currency,
                "base_currency": base_currency,
                "category": category,
                "description": description,
                "symbol": _first_present_text(row.attrib, "symbol", "underlyingSymbol"),
                "amount": amount,
                "amount_base": amount_base,
                "settle_date": _normalize_date_text(_first_present_text(row.attrib, "settleDate", "dateTime")),
                "report_date": report_date,
            }
            if description or amount:
                transactions.append(record)
    return transactions


def _extract_option_events(statements: list[ET.Element]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for statement in statements:
        account_id = statement.attrib.get("accountId", "UNKNOWN")
        account_alias = statement.attrib.get("acctAlias", "")
        for row in statement.findall(".//OptionEAE/*"):
            record = {
                "account_id": account_id,
                "account_alias": account_alias,
                "symbol": _first_present_text(row.attrib, "symbol", "underlyingSymbol"),
                "description": row.attrib.get("description", ""),
                "currency": row.attrib.get("currency", ""),
                "event_type": _first_present_text(row.attrib, "transactionType", "action", "type"),
                "quantity": _first_present_float(row.attrib.get("quantity"), row.attrib.get("position")),
                "strike": _to_float(row.attrib.get("strike")),
                "expiry": _normalize_date_text(_first_present_text(row.attrib, "expiry", "expirationDate")),
                "event_date": _normalize_date_text(_first_present_text(row.attrib, "reportDate", "dateTime")),
                "proceeds": _first_present_float(row.attrib.get("proceeds"), row.attrib.get("netCash")),
            }
            if record["symbol"] or record["event_type"] or record["quantity"]:
                events.append(record)
    return events


def _extract_conversion_rates(root: ET.Element) -> list[dict[str, Any]]:
    rates: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in root.findall(".//ConversionRate"):
        record = {
            "from_currency": row.attrib.get("fromCurrency", ""),
            "to_currency": row.attrib.get("toCurrency", ""),
            "rate": _to_float(row.attrib.get("rate")),
            "report_date": _normalize_date_text(row.attrib.get("reportDate")),
        }
        key = (record["from_currency"], record["to_currency"], record["report_date"])
        if key in seen:
            continue
        seen.add(key)
        rates.append(record)
    return rates


def _detect_sections(statements: list[ET.Element]) -> dict[str, dict[str, Any]]:
    sections: dict[str, dict[str, Any]] = {}
    for name in (
        "EquitySummaryInBase",
        "MTMPerformanceSummaryInBase",
        "CashReport",
        "OpenPositions",
        "Trades",
        "OptionEAE",
        "CashTransactions",
        "ConversionRates",
    ):
        nodes = [statement.find(f".//{name}") for statement in statements]
        sections[name] = {
            "present": any(node is not None for node in nodes),
            "non_empty_accounts": sum(1 for node in nodes if node is not None and len(list(node)) > 0),
        }
    return sections


def _build_concentration_snapshot(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    top_holdings = [
        {
            "symbol": holding.get("symbol", "UNKNOWN"),
            "weight_pct": round(float(holding.get("weight_pct", 0.0)), 2),
            "net_weight_pct": round(float(holding.get("net_weight_pct", 0.0)), 2),
            "pnl_pct": round(float(holding.get("pnl_pct", 0.0)), 2),
        }
        for holding in holdings[:5]
    ]
    return {
        "top_holdings": top_holdings,
        "top_1_weight_pct": round(sum(item["weight_pct"] for item in top_holdings[:1]), 2),
        "top_3_weight_pct": round(sum(item["weight_pct"] for item in top_holdings[:3]), 2),
    }


def _build_risk_flags(holdings: list[dict[str, Any]], option_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for holding in holdings:
        symbol = str(holding.get("symbol", "UNKNOWN"))
        weight_pct = float(holding.get("weight_pct", 0.0))
        pnl_pct = float(holding.get("pnl_pct", 0.0))
        side = str(holding.get("side", "Long")).lower()
        if weight_pct >= 30 and side != "short" and not _is_cash_equivalent_position(holding):
            flags.append({"type": "concentration", "symbol": symbol, "value": round(weight_pct, 2)})
        if pnl_pct <= -15:
            flags.append({"type": "drawdown", "symbol": symbol, "value": round(pnl_pct, 2)})
        if side == "short" and pnl_pct <= -100:
            flags.append({"type": "short_option_loss", "symbol": symbol, "value": round(pnl_pct, 2)})
    for event in option_events:
        if event.get("event_type"):
            flags.append(
                {
                    "type": "option_event",
                    "symbol": event.get("symbol", "UNKNOWN"),
                    "value": event.get("event_type", ""),
                }
            )
    return flags[:12]


def _summarize_cash_transactions(
    transactions: list[dict[str, Any]],
    base_currency: str,
) -> dict[str, Any]:
    totals = defaultdict(float)
    for transaction in transactions:
        totals[transaction.get("category", "other")] += float(transaction.get("amount_base", 0.0))
    return {
        "base_currency": base_currency,
        "dividends": round(totals["dividend"], 2),
        "withholding_tax": round(totals["withholding_tax"], 2),
        "interest": round(totals["interest"], 2),
        "fees": round(totals["fee"], 2),
        "transfers": round(totals["transfer"], 2),
        "other": round(totals["other"], 2),
    }


def _summarize_recent_activity(trades: list[dict[str, Any]], option_events: list[dict[str, Any]]) -> dict[str, Any]:
    trade_symbols = [trade["symbol"] for trade in trades if trade.get("symbol")]
    option_symbols = [event["symbol"] for event in option_events if event.get("symbol")]
    return {
        "trade_count": len(trades),
        "traded_symbols": sorted(set(trade_symbols)),
        "option_event_count": len(option_events),
        "option_event_symbols": sorted(set(option_symbols)),
    }


def _normalize_portfolio(positions: dict[str, Any]) -> dict[str, Any]:
    total_value = _to_float(positions.get("total_value", 0.0))
    cash = _to_float(positions.get("cash", 0.0))
    daily_pnl = _to_float(positions.get("daily_pnl", 0.0))
    normalized_positions: list[dict[str, Any]] = []

    for raw_position in positions.get("positions", []):
        market_value = _to_float(raw_position.get("market_value", 0.0))
        market_value_base = _to_float(raw_position.get("market_value_base", market_value))
        normalized_positions.append(
            {
                "symbol": str(raw_position.get("symbol", "UNKNOWN")),
                "description": str(raw_position.get("description", "")),
                "currency": str(raw_position.get("currency", "")),
                "quantity": _to_float(raw_position.get("quantity", 0.0)),
                "side": str(raw_position.get("side", "Long")),
                "asset_category": str(raw_position.get("asset_category", "")),
                "account_id": str(raw_position.get("account_id", "")),
                "account_alias": str(raw_position.get("account_alias", "")),
                "avg_cost": _to_float(raw_position.get("avg_cost", 0.0)),
                "current_price": _to_float(raw_position.get("current_price", 0.0)),
                "pnl_pct": _to_float(raw_position.get("pnl_pct", 0.0)),
                "market_value": market_value,
                "market_value_base": market_value_base,
                "cost_basis_money": _to_float(raw_position.get("cost_basis_money", 0.0)),
                "cost_basis_base": _to_float(raw_position.get("cost_basis_base", 0.0)),
                "unrealized_pnl": _to_float(raw_position.get("unrealized_pnl", 0.0)),
                "unrealized_pnl_base": _to_float(raw_position.get("unrealized_pnl_base", 0.0)),
                "fx_rate_to_base": _to_float(raw_position.get("fx_rate_to_base", 0.0)) or 1.0,
                "account_nav_pct": _to_float(raw_position.get("account_nav_pct", 0.0)),
                "report_date": str(raw_position.get("report_date", "")),
                "weight_pct": (abs(market_value_base) / total_value * 100) if total_value else 0.0,
                "net_weight_pct": (market_value_base / total_value * 100) if total_value else 0.0,
            }
        )

    normalized_positions.sort(key=lambda item: abs(item["market_value_base"]), reverse=True)
    cash_pct = (cash / total_value * 100) if total_value else 0.0
    daily_return_pct = (daily_pnl / total_value * 100) if total_value else 0.0

    return {
        **positions,
        "cash": cash,
        "total_value": total_value,
        "daily_pnl": daily_pnl,
        "daily_return_pct": daily_return_pct,
        "cash_pct": cash_pct,
        "positions": normalized_positions,
    }


def _build_fx_lookup(fx_rates: list[dict[str, Any]]) -> dict[tuple[str, str, str], float]:
    lookup: dict[tuple[str, str, str], float] = {}
    for row in fx_rates:
        key = (
            str(row.get("from_currency", "")),
            str(row.get("to_currency", "")),
            str(row.get("report_date", "")),
        )
        lookup[key] = float(row.get("rate", 0.0))
    return lookup


def _amount_in_base(
    amount: float,
    currency: str,
    base_currency: str,
    report_date: str,
    rate_lookup: dict[tuple[str, str, str], float],
) -> float:
    if not currency or currency == base_currency:
        return round(amount, 2)
    rate = rate_lookup.get((currency, base_currency, report_date)) or rate_lookup.get(
        (currency, base_currency, "")
    )
    return round(amount * rate, 2) if rate else round(amount, 2)


def _classify_cash_transaction(description: str, attrs: dict[str, str]) -> str:
    haystack = " ".join(
        part.lower()
        for part in (
            description,
            attrs.get("type", ""),
            attrs.get("transactionType", ""),
        )
        if part
    )
    if "dividend" in haystack:
        return "dividend"
    if "withholding" in haystack or "tax" in haystack:
        return "withholding_tax"
    if "interest" in haystack:
        return "interest"
    if "fee" in haystack or "commission" in haystack:
        return "fee"
    if "deposit" in haystack or "withdraw" in haystack or "transfer" in haystack:
        return "transfer"
    return "other"


def _is_cash_equivalent_position(position: dict[str, Any]) -> bool:
    symbol = str(position.get("symbol", "")).upper()
    description = str(position.get("description", "")).upper()
    return symbol in {"SGOV", "BIL", "SHV", "JPST"} or "TREASURY" in description


def _normalize_date_text(value: str | None) -> str:
    parsed = _parse_ibkr_date(value)
    return parsed.isoformat() if parsed is not None else (value or "").strip()


def _normalize_time_text(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.strip()
    if len(cleaned) == 6 and cleaned.isdigit():
        return f"{cleaned[:2]}:{cleaned[2:4]}:{cleaned[4:6]}"
    return cleaned


def _first_present_text(attrs: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = attrs.get(key, "").strip()
        if value:
            return value
    return ""


def _first_present_float(*values: str | None) -> float:
    for value in values:
        parsed = _to_float(value)
        if parsed != 0.0:
            return parsed
    return 0.0
