"""Stage 01: fetch raw IBKR statement data."""

from __future__ import annotations

from typing import Any

from src.core.providers.ibkr_client import get_ibkr_positions, get_ibkr_statement_xml


def run_ibkr_fetch_stage() -> str:
    """Return the raw IBKR Flex statement XML."""
    return get_ibkr_statement_xml()


def run_ibkr_positions_stage() -> dict[str, Any]:
    """Return parsed IBKR portfolio positions for legacy consumers."""
    return get_ibkr_positions()
