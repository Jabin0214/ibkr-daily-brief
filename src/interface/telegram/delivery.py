"""Telegram delivery entrypoints for pipeline and interface callers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.interface.telegram.notify import send_telegram, send_telegram_document


def deliver_report(report_path: Path) -> None:
    """Send the HTML report to Telegram."""
    print(f"[Interface] Sending HTML report: {report_path}")
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
