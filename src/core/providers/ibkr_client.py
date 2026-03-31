"""IBKR Flex Query data retrieval and parsing."""

from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

from src.core.providers.networking import DEFAULT_TIMEOUT, get_requests_session

FLEX_REQUEST_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
FLEX_STATEMENT_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
IBKR_HEADERS = {"User-Agent": "ibkr-daily-brief/1.0"}
IBKR_REPORTING_TZ = ZoneInfo("America/New_York")
IBKR_SECURITIES_CUTOFF = dt_time(hour=20, minute=30)


def get_ibkr_positions() -> dict[str, Any]:
    """Fetch IBKR positions from Flex Query API and return normalized portfolio data."""
    print("[IBKR] Starting Flex Query request...")

    xml_text = get_ibkr_statement_xml()
    if not xml_text:
        return _mock_portfolio_data()

    try:
        portfolio = _parse_portfolio_xml(xml_text)
        print("[IBKR] Flex Query parsing completed.")
        return portfolio
    except Exception as exc:
        print(f"[IBKR] Failed to parse data: {exc}")
        return _mock_portfolio_data()


def get_ibkr_statement_xml() -> str:
    """Fetch the raw IBKR Flex statement XML for downstream middleware or parsing."""
    print("[IBKR] Starting Flex Query request...")

    token = os.getenv("IBKR_FLEX_TOKEN")
    query_id = os.getenv("IBKR_FLEX_QUERY_ID")

    if not token or not query_id:
        print("[IBKR] Missing Flex Query credentials, using mock data.")
        return ""

    try:
        session = get_requests_session()
        max_wait_minutes = _env_int("IBKR_MAX_WAIT_MINUTES", 0)
        poll_interval_seconds = _env_int("IBKR_POLL_INTERVAL_SECONDS", 300)
        wait_for_fresh_report = _env_bool("IBKR_WAIT_FOR_FRESH_REPORT", max_wait_minutes > 0)
        expected_report_date = _expected_activity_statement_date() if wait_for_fresh_report else None
        if expected_report_date is not None:
            print(
                "[IBKR] Waiting for fresh Activity Statement dated "
                f"{expected_report_date.isoformat()} or newer."
            )

        return _fetch_flex_statement(
            session,
            token,
            query_id,
            expected_report_date=expected_report_date,
            max_wait_minutes=max_wait_minutes,
            poll_interval_seconds=poll_interval_seconds,
        )
    except Exception as exc:
        print(f"[IBKR] Failed to fetch data: {exc}")
        return ""


def _fetch_flex_statement(
    session: requests.Session,
    token: str,
    query_id: str,
    expected_report_date: date | None,
    max_wait_minutes: int,
    poll_interval_seconds: int,
) -> str:
    """Fetch a Flex statement and optionally wait for the next daily Activity Statement."""
    deadline = time.monotonic() + max(0, max_wait_minutes) * 60
    attempt = 1
    last_xml_text = ""

    while True:
        print(f"[IBKR] Requesting Flex statement... cycle {attempt}")
        reference_code = _request_flex_statement(session, token, query_id)
        xml_text = _poll_flex_statement(session, token, reference_code)
        last_xml_text = xml_text

        report_date = _extract_statement_report_date(xml_text)
        if report_date is not None:
            print(f"[IBKR] Latest statement date from XML: {report_date.isoformat()}")
        else:
            print("[IBKR] Could not determine statement date from XML, using latest response.")

        if expected_report_date is None or report_date is None or report_date >= expected_report_date:
            return xml_text

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                "[IBKR] Fresh statement did not arrive within wait window; "
                f"using latest available statement dated {report_date.isoformat()}."
            )
            return last_xml_text

        sleep_seconds = min(max(30, poll_interval_seconds), int(remaining))
        print(
            "[IBKR] Statement is still stale; "
            f"waiting {sleep_seconds}s before retrying for date {expected_report_date.isoformat()}."
        )
        time.sleep(sleep_seconds)
        attempt += 1


def _request_flex_statement(session: requests.Session, token: str, query_id: str) -> str:
    """Request a Flex statement generation job and return the reference code."""
    response = session.get(
        FLEX_REQUEST_URL,
        params={"t": token, "q": query_id, "v": "3"},
        headers=IBKR_HEADERS,
        timeout=DEFAULT_TIMEOUT,
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


def _poll_flex_statement(session: requests.Session, token: str, reference_code: str) -> str:
    """Poll Flex statement endpoint until the statement is ready."""
    for attempt in range(10):
        print(f"[IBKR] Polling statement generation... attempt {attempt + 1}/10")
        response = session.get(
            FLEX_STATEMENT_URL,
            params={"t": token, "q": reference_code, "v": "3"},
            headers=IBKR_HEADERS,
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()

        if "Statement generation in progress" not in response.text:
            return response.text
        time.sleep(3)

    raise TimeoutError("IBKR statement generation timed out")


def _parse_portfolio_xml(xml_text: str) -> dict[str, Any]:
    """Parse IBKR XML into the project portfolio structure."""
    root = ET.fromstring(xml_text)
    statements = root.findall(".//FlexStatement")

    if not statements:
        return _empty_portfolio()

    parsed_statements = [_parse_single_statement(statement) for statement in statements]

    if len(parsed_statements) == 1:
        parsed_statements[0]["scope"] = "single"
        return parsed_statements[0]

    return _aggregate_statements(parsed_statements)


def _parse_single_statement(statement: ET.Element) -> dict[str, Any]:
    """Parse a single FlexStatement into a normalized portfolio structure."""
    positions: list[dict[str, Any]] = []
    cash = 0.0
    daily_pnl = 0.0
    total_value = 0.0
    base_currency = "BASE"
    account_id = statement.attrib.get("accountId", "UNKNOWN")
    account_alias = statement.attrib.get("acctAlias", "")
    latest_report_date: date | None = None

    for position in statement.findall(".//OpenPosition"):
        symbol = position.attrib.get("symbol", "").strip() or "UNKNOWN"
        currency = position.attrib.get("currency", "").strip() or "UNKNOWN"
        quantity = _to_float(position.attrib.get("position", "0"))
        avg_cost = _to_float(position.attrib.get("costBasisPrice", "0"))
        current_price = _to_float(position.attrib.get("markPrice", "0"))
        market_value = _to_float(position.attrib.get("positionValue", "0"))
        fx_rate_to_base = _to_float(position.attrib.get("fxRateToBase", "0")) or 1.0
        market_value_base = market_value * fx_rate_to_base
        cost_basis_money = _to_float(position.attrib.get("costBasisMoney", "0"))
        cost_basis_base = cost_basis_money * fx_rate_to_base
        unrealized_pnl = _to_float(position.attrib.get("fifoPnlUnrealized", "0"))
        unrealized_pnl_base = unrealized_pnl * fx_rate_to_base
        side = position.attrib.get("side", "Long").strip() or "Long"
        asset_category = position.attrib.get("assetCategory", "").strip()
        description = position.attrib.get("description", "").strip()
        percent_of_nav = _to_float(position.attrib.get("percentOfNAV", "0"))
        report_date = _parse_ibkr_date(position.attrib.get("reportDate"))
        latest_report_date = max(filter(None, [latest_report_date, report_date]), default=latest_report_date)

        pnl_basis = abs(cost_basis_money) or abs(market_value)
        if pnl_basis:
            pnl_pct = (unrealized_pnl / pnl_basis) * 100
        elif avg_cost:
            price_move_pct = ((current_price - avg_cost) / avg_cost) * 100
            pnl_pct = -price_move_pct if side.lower() == "short" or quantity < 0 else price_move_pct
        else:
            pnl_pct = 0.0

        positions.append(
            {
                "symbol": symbol,
                "description": description,
                "currency": currency,
                "quantity": quantity,
                "side": side,
                "asset_category": asset_category,
                "account_id": account_id,
                "account_alias": position.attrib.get("acctAlias", account_alias).strip(),
                "avg_cost": round(avg_cost, 2),
                "current_price": round(current_price, 2),
                "pnl_pct": round(pnl_pct, 2),
                "market_value": round(market_value, 2),
                "market_value_base": round(market_value_base, 2),
                "cost_basis_money": round(cost_basis_money, 2),
                "cost_basis_base": round(cost_basis_base, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "unrealized_pnl_base": round(unrealized_pnl_base, 2),
                "fx_rate_to_base": round(fx_rate_to_base, 6),
                "account_nav_pct": round(percent_of_nav, 2),
                "report_date": report_date.isoformat() if report_date else "",
            }
        )

    latest_equity_summary = _latest_equity_summary(statement)
    if latest_equity_summary is not None:
        base_currency = latest_equity_summary.attrib.get("currency", "BASE") or "BASE"
        cash = _to_float(latest_equity_summary.attrib.get("cash", "0"))
        total_value = _first_nonzero(
            latest_equity_summary.attrib.get("netLiquidation"),
            latest_equity_summary.attrib.get("total"),
        )

    base_cash_report = statement.find(".//CashReportCurrency[@currency='BASE_SUMMARY']")
    if base_cash_report is not None:
        cash = _first_nonzero(
            base_cash_report.attrib.get("endingCash"),
            base_cash_report.attrib.get("totalCashValue"),
            base_cash_report.attrib.get("settledCash"),
        )

    total_line = statement.find(".//MTMPerformanceSummaryUnderlying[@description='Total P/L']")
    if total_line is not None:
        daily_pnl = _first_nonzero(
            total_line.attrib.get("total"),
            total_line.attrib.get("totalWithAccruals"),
        )
    else:
        for mtm_summary in statement.findall(".//MTMPerformanceSummaryUnderlying"):
            if mtm_summary.attrib.get("description") == "Total P/L":
                continue
            daily_pnl += _first_nonzero(
                mtm_summary.attrib.get("mtmPnl"),
                mtm_summary.attrib.get("markToMarketPL"),
                mtm_summary.attrib.get("total"),
            )

    if cash == 0.0 or total_value == 0.0:
        for equity_summary in statement.findall(".//EquitySummaryByReportDateInBase"):
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
        "account_id": account_id,
        "account_alias": account_alias,
        "positions": positions,
        "base_currency": base_currency,
        "cash": round(cash, 2),
        "total_value": round(total_value, 2),
        "daily_pnl": round(daily_pnl, 2),
        "cash_pct": round(cash_pct, 2),
        "report_date": latest_report_date.isoformat() if latest_report_date else "",
    }


def _aggregate_statements(statements: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate multiple FlexStatement payloads into one portfolio scope."""
    base_currency = statements[0].get("base_currency", "BASE") if statements else "BASE"
    positions: list[dict[str, Any]] = []
    cash = 0.0
    total_value = 0.0
    daily_pnl = 0.0
    account_ids: list[str] = []
    account_aliases: list[str] = []
    report_dates: list[str] = []

    for statement in statements:
        positions.extend(statement.get("positions", []))
        cash += float(statement.get("cash", 0.0))
        total_value += float(statement.get("total_value", 0.0))
        daily_pnl += float(statement.get("daily_pnl", 0.0))
        account_ids.append(str(statement.get("account_id", "UNKNOWN")))
        alias = str(statement.get("account_alias", "")).strip()
        if alias:
            account_aliases.append(alias)
        report_date = str(statement.get("report_date", "")).strip()
        if report_date:
            report_dates.append(report_date)

    cash_pct = (cash / total_value * 100) if total_value else 0.0

    return {
        "account_id": ",".join(account_ids),
        "account_alias": ",".join(account_aliases),
        "scope": "aggregate",
        "positions": positions,
        "base_currency": base_currency,
        "cash": round(cash, 2),
        "total_value": round(total_value, 2),
        "daily_pnl": round(daily_pnl, 2),
        "cash_pct": round(cash_pct, 2),
        "report_date": max(report_dates) if report_dates else "",
    }


def _mock_portfolio_data() -> dict[str, Any]:
    """Return fallback portfolio data for testing and failure scenarios."""
    print("[IBKR] Returning mock portfolio data.")
    return {
        "account_id": "MOCK",
        "scope": "mock",
        "positions": [
            {
                "symbol": "TSLA",
                "description": "TESLA INC",
                "quantity": 100,
                "side": "Long",
                "asset_category": "STK",
                "avg_cost": 220.0,
                "current_price": 185.0,
                "pnl_pct": -15.91,
                "market_value": 18500.0,
                "market_value_base": 18500.0,
            },
            {
                "symbol": "NVDA",
                "description": "NVIDIA CORP",
                "quantity": 20,
                "side": "Long",
                "asset_category": "STK",
                "avg_cost": 780.0,
                "current_price": 836.0,
                "pnl_pct": 7.18,
                "market_value": 16720.0,
                "market_value_base": 16720.0,
            },
        ],
        "cash": 5000.0,
        "total_value": 40220.0,
        "daily_pnl": -340.0,
        "cash_pct": 12.43,
        "report_date": datetime.now(IBKR_REPORTING_TZ).date().isoformat(),
    }


def _empty_portfolio() -> dict[str, Any]:
    """Return an empty portfolio when the XML has no statements."""
    return {
        "account_id": "UNKNOWN",
        "scope": "empty",
        "positions": [],
        "base_currency": "BASE",
        "cash": 0.0,
        "total_value": 0.0,
        "daily_pnl": 0.0,
        "cash_pct": 0.0,
        "report_date": "",
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


def _extract_statement_report_date(xml_text: str) -> date | None:
    """Extract the latest report date visible in the IBKR Flex XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    dates: list[date] = []

    for summary in root.findall(".//EquitySummaryByReportDateInBase"):
        parsed = _parse_ibkr_date(summary.attrib.get("reportDate"))
        if parsed is not None:
            dates.append(parsed)

    for statement in root.findall(".//FlexStatement"):
        for attr_name in ("toDate", "reportDate"):
            parsed = _parse_ibkr_date(statement.attrib.get(attr_name))
            if parsed is not None:
                dates.append(parsed)

    return max(dates) if dates else None


def _parse_ibkr_date(raw_value: str | None) -> date | None:
    """Parse common IBKR date formats into a date object."""
    if not raw_value:
        return None

    value = raw_value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _expected_activity_statement_date(now: datetime | None = None) -> date:
    """Infer the freshest Activity Statement date we should expect from IBKR."""
    current_time = now or datetime.now(IBKR_REPORTING_TZ)
    current_date = current_time.date()

    if current_date.weekday() < 5 and current_time.time() >= IBKR_SECURITIES_CUTOFF:
        return current_date
    return _previous_weekday(current_date)


def _previous_weekday(current_date: date) -> date:
    """Return the most recent weekday before the provided date."""
    candidate = current_date - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean-like environment variable."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a fallback."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default
