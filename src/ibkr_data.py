"""IBKR Flex Query data retrieval and parsing."""

from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests

FLEX_REQUEST_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
FLEX_STATEMENT_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
IBKR_HEADERS = {"User-Agent": "ibkr-daily-brief/1.0"}


def get_ibkr_positions() -> dict[str, Any]:
    """Fetch IBKR positions from Flex Query API and return normalized portfolio data."""
    print("[IBKR] Starting Flex Query request...")

    token = os.getenv("IBKR_FLEX_TOKEN")
    query_id = os.getenv("IBKR_FLEX_QUERY_ID")

    if not token or not query_id:
        print("[IBKR] Missing Flex Query credentials, using mock data.")
        return _mock_portfolio_data()

    try:
        reference_code = _request_flex_statement(token, query_id)
        xml_text = _poll_flex_statement(token, reference_code)
        portfolio = _parse_portfolio_xml(xml_text)
        print("[IBKR] Flex Query parsing completed.")
        return portfolio
    except Exception as exc:
        print(f"[IBKR] Failed to fetch or parse data: {exc}")
        return _mock_portfolio_data()


def _request_flex_statement(token: str, query_id: str) -> str:
    """Request a Flex statement generation job and return the reference code."""
    response = requests.get(
        FLEX_REQUEST_URL,
        params={"t": token, "q": query_id, "v": "3"},
        headers=IBKR_HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    root = ET.fromstring(response.text)
    status = root.findtext("Status")
    if status != "Success":
        error_message = root.findtext("ErrorMessage", default="Unknown IBKR request error")
        raise ValueError(error_message)

    reference_code = root.findtext("ReferenceCode")
    if not reference_code:
        raise ValueError("Missing IBKR reference code")
    return reference_code


def _poll_flex_statement(token: str, reference_code: str) -> str:
    """Poll Flex statement endpoint until the statement is ready."""
    for attempt in range(5):
        print(f"[IBKR] Polling statement... attempt {attempt + 1}/5")
        response = requests.get(
            FLEX_STATEMENT_URL,
            params={"t": token, "q": reference_code, "v": "3"},
            headers=IBKR_HEADERS,
            timeout=30,
        )
        response.raise_for_status()

        if "Statement generation in progress" not in response.text:
            return response.text
        time.sleep(2)

    raise TimeoutError("IBKR statement generation timed out")


def _parse_portfolio_xml(xml_text: str) -> dict[str, Any]:
    """Parse IBKR XML into the project portfolio structure."""
    root = ET.fromstring(xml_text)

    positions: list[dict[str, Any]] = []
    cash = 0.0
    daily_pnl = 0.0
    total_value = 0.0
    base_currency = "BASE"

    for position in root.findall(".//OpenPosition"):
        symbol = position.attrib.get("symbol", "").strip() or "UNKNOWN"
        currency = position.attrib.get("currency", "").strip() or "UNKNOWN"
        quantity = _to_float(position.attrib.get("position", "0"))
        avg_cost = _to_float(position.attrib.get("costBasisPrice", "0"))
        current_price = _to_float(position.attrib.get("markPrice", "0"))
        market_value = _to_float(position.attrib.get("positionValue", "0"))

        pnl_pct = 0.0
        if avg_cost:
            pnl_pct = ((current_price - avg_cost) / avg_cost) * 100

        positions.append(
            {
                "symbol": symbol,
                "currency": currency,
                "quantity": quantity,
                "avg_cost": round(avg_cost, 2),
                "current_price": round(current_price, 2),
                "pnl_pct": round(pnl_pct, 2),
                "market_value": round(market_value, 2),
            }
        )

    latest_equity_summary = _latest_equity_summary(root)
    if latest_equity_summary is not None:
        base_currency = latest_equity_summary.attrib.get("currency", "BASE") or "BASE"
        cash = _to_float(latest_equity_summary.attrib.get("cash", "0"))
        total_value = _first_nonzero(
            latest_equity_summary.attrib.get("netLiquidation"),
            latest_equity_summary.attrib.get("total"),
        )

    base_cash_report = root.find(".//CashReportCurrency[@currency='BASE_SUMMARY']")
    if base_cash_report is not None:
        cash = _first_nonzero(
            base_cash_report.attrib.get("endingCash"),
            base_cash_report.attrib.get("totalCashValue"),
            base_cash_report.attrib.get("settledCash"),
        )

    total_line = root.find(".//MTMPerformanceSummaryUnderlying[@description='Total P/L']")
    if total_line is not None:
        daily_pnl = _first_nonzero(
            total_line.attrib.get("total"),
            total_line.attrib.get("totalWithAccruals"),
        )

    for mtm_summary in root.findall(".//MTMPerformanceSummaryUnderlying"):
        if mtm_summary.attrib.get("description") == "Total P/L":
            continue
        if daily_pnl == 0.0:
            daily_pnl += _first_nonzero(
                mtm_summary.attrib.get("mtmPnl"),
                mtm_summary.attrib.get("markToMarketPL"),
                mtm_summary.attrib.get("total"),
            )

    if cash == 0.0 or total_value == 0.0:
        for equity_summary in root.findall(".//EquitySummaryByReportDateInBase"):
            cash = max(cash, _to_float(equity_summary.attrib.get("cash", "0")))
            total_value = max(
                total_value,
                _first_nonzero(
                    equity_summary.attrib.get("netLiquidation"),
                    equity_summary.attrib.get("endingSettledCash"),
                ),
            )

    cash_pct = (cash / total_value * 100) if total_value else 0.0

    return {
        "positions": positions,
        "base_currency": base_currency,
        "cash": round(cash, 2),
        "total_value": round(total_value, 2),
        "daily_pnl": round(daily_pnl, 2),
        "cash_pct": round(cash_pct, 2),
    }


def _mock_portfolio_data() -> dict[str, Any]:
    """Return fallback portfolio data for testing and failure scenarios."""
    print("[IBKR] Returning mock portfolio data.")
    return {
        "positions": [
            {
                "symbol": "TSLA",
                "quantity": 100,
                "avg_cost": 220.0,
                "current_price": 185.0,
                "pnl_pct": -15.91,
                "market_value": 18500.0,
            },
            {
                "symbol": "NVDA",
                "quantity": 20,
                "avg_cost": 780.0,
                "current_price": 836.0,
                "pnl_pct": 7.18,
                "market_value": 16720.0,
            },
        ],
        "cash": 5000.0,
        "total_value": 40220.0,
        "daily_pnl": -340.0,
        "cash_pct": 12.43,
    }


def _to_float(value: str | None) -> float:
    """Convert string values to float safely."""
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _first_nonzero(*values: str | None) -> float:
    """Return the first non-zero numeric value from the provided strings."""
    for value in values:
        parsed = _to_float(value)
        if parsed != 0.0:
            return parsed
    return 0.0


def _latest_equity_summary(root: ET.Element) -> ET.Element | None:
    """Return the latest EquitySummaryByReportDateInBase element if present."""
    summaries = root.findall(".//EquitySummaryByReportDateInBase")
    if not summaries:
        return None
    return max(summaries, key=lambda item: item.attrib.get("reportDate", ""))
