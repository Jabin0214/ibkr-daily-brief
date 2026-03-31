"""IBKR Flex Query raw statement retrieval and freshness checks."""

from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

import requests

from src.core.providers.networking import DEFAULT_TIMEOUT, get_requests_session

FLEX_REQUEST_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
FLEX_STATEMENT_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
IBKR_HEADERS = {"User-Agent": "ibkr-daily-brief/1.0"}
IBKR_REPORTING_TZ = ZoneInfo("America/New_York")
IBKR_SECURITIES_CUTOFF = dt_time(hour=20, minute=30)
STATEMENT_POLL_ATTEMPTS = 10
STATEMENT_POLL_SLEEP_SECONDS = 3


@dataclass(frozen=True)
class FlexFetchConfig:
    """Runtime configuration for IBKR Flex statement retrieval."""

    token: str
    query_id: str
    expected_report_date: date | None
    max_wait_minutes: int
    poll_interval_seconds: int


def get_ibkr_statement_xml() -> str:
    """Fetch the latest raw IBKR Flex statement XML."""
    print("[IBKR] Starting Flex Query request...")

    config = _load_fetch_config()
    if config is None:
        print("[IBKR] Missing Flex Query credentials, using mock data.")
        return ""

    try:
        session = get_requests_session()
        if config.expected_report_date is not None:
            print(
                "[IBKR] Waiting for fresh Activity Statement dated "
                f"{config.expected_report_date.isoformat()} or newer."
            )
        return _fetch_flex_statement(session, config)
    except Exception as exc:
        print(f"[IBKR] Failed to fetch data: {exc}")
        return ""


def _load_fetch_config() -> FlexFetchConfig | None:
    """Load environment-driven Flex Query configuration."""
    token = os.getenv("IBKR_FLEX_TOKEN")
    query_id = os.getenv("IBKR_FLEX_QUERY_ID")
    if not token or not query_id:
        return None

    max_wait_minutes = _env_int("IBKR_MAX_WAIT_MINUTES", 0)
    poll_interval_seconds = _env_int("IBKR_POLL_INTERVAL_SECONDS", 300)
    wait_for_fresh_report = _env_bool("IBKR_WAIT_FOR_FRESH_REPORT", max_wait_minutes > 0)
    expected_report_date = _expected_activity_statement_date() if wait_for_fresh_report else None
    return FlexFetchConfig(
        token=token,
        query_id=query_id,
        expected_report_date=expected_report_date,
        max_wait_minutes=max_wait_minutes,
        poll_interval_seconds=poll_interval_seconds,
    )


def _fetch_flex_statement(session: requests.Session, config: FlexFetchConfig) -> str:
    """Fetch a Flex statement and optionally wait for the next daily Activity Statement."""
    deadline = time.monotonic() + max(0, config.max_wait_minutes) * 60
    attempt = 1
    last_xml_text = ""

    while True:
        print(f"[IBKR] Requesting Flex statement... cycle {attempt}")
        reference_code = _request_flex_statement(session, config.token, config.query_id)
        xml_text = _poll_flex_statement(session, config.token, reference_code)
        last_xml_text = xml_text

        report_date = _extract_statement_report_date(xml_text)
        if report_date is not None:
            print(f"[IBKR] Latest statement date from XML: {report_date.isoformat()}")
        else:
            print("[IBKR] Could not determine statement date from XML, using latest response.")

        if config.expected_report_date is None or report_date is None or report_date >= config.expected_report_date:
            return xml_text

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                "[IBKR] Fresh statement did not arrive within wait window; "
                f"using latest available statement dated {report_date.isoformat()}."
            )
            return last_xml_text

        sleep_seconds = min(max(30, config.poll_interval_seconds), int(remaining))
        print(
            "[IBKR] Statement is still stale; "
            f"waiting {sleep_seconds}s before retrying for date {config.expected_report_date.isoformat()}."
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
    for attempt in range(STATEMENT_POLL_ATTEMPTS):
        print(f"[IBKR] Polling statement generation... attempt {attempt + 1}/{STATEMENT_POLL_ATTEMPTS}")
        response = session.get(
            FLEX_STATEMENT_URL,
            params={"t": token, "q": reference_code, "v": "3"},
            headers=IBKR_HEADERS,
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()

        if "Statement generation in progress" not in response.text:
            return response.text
        time.sleep(STATEMENT_POLL_SLEEP_SECONDS)

    raise TimeoutError("IBKR statement generation timed out")


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

    for statement in _find_flex_statements(root):
        for attr_name in ("toDate", "reportDate"):
            parsed = _parse_ibkr_date(statement.attrib.get(attr_name))
            if parsed is not None:
                dates.append(parsed)

    return max(dates) if dates else None


def _find_flex_statements(root: ET.Element) -> list[ET.Element]:
    """Handle both wrapped and direct FlexStatement XML payloads."""
    if root.tag == "FlexStatement":
        return [root]
    return root.findall(".//FlexStatement")


def _parse_ibkr_date(raw_value: str | None) -> date | None:
    """Parse IBKR date strings for fetch-time freshness checks."""
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
