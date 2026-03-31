"""Entry point for the IBKR daily investment brief workflow."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from src.interface.telegram.delivery import deliver_failure_alert, deliver_message, deliver_report
from src.interface.telegram.presenter import render_daily_report, render_news_flash, render_portfolio_snapshot
from src.pipeline.daily_report import (
    run_daily_report_pipeline,
    run_ibkr_payload_pipeline,
    run_ibkr_snapshot_pipeline,
    run_news_only_pipeline,
)


def main() -> int:
    """Run the daily investment brief workflow."""
    load_dotenv(Path(__file__).with_name(".env"))
    args = _parse_args()
    start_time = time.perf_counter()

    print("=== 开始每日投资简报 ===")
    print(f"[Main] Test mode: {args.test}")
    print(f"[Main] News-only mode: {args.news_only}")
    print(f"[Main] IBKR-only mode: {args.ibkr_only}")
    print(f"[Main] IBKR-payload mode: {args.ibkr_payload}")
    print(f"[Main] Send mode: {args.send}")

    try:
        if args.ibkr_payload:
            payload = run_ibkr_payload_pipeline(test_mode=args.test)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            _print_runtime(start_time, 0.0)
            return 0

        if args.ibkr_only:
            positions = run_ibkr_snapshot_pipeline(test_mode=args.test)
            snapshot = render_portfolio_snapshot(positions)
            print(snapshot)
            if args.send:
                deliver_message(snapshot)
            _print_runtime(start_time, 0.0)
            return 0

        if args.news_only:
            market = run_news_only_pipeline()
            news_flash = render_news_flash(market)
            print(news_flash)
            if args.send:
                deliver_message(news_flash)
            _print_runtime(start_time, _estimate_news_cost())
            return 0

        output_dir = Path(__file__).with_name("reports")
        artifacts = run_daily_report_pipeline(
            test_mode=args.test,
            output_dir=output_dir,
        )
        message, report_path = render_daily_report(
            market=artifacts.market,
            positions=artifacts.positions,
            analysis=artifacts.analysis,
            research_plan=artifacts.research_plan,
            output_dir=output_dir,
        )
        print(f"[Main] Detailed report saved to: {report_path}")
        if args.send:
            deliver_report(report_path)
        else:
            print(message)
        _print_runtime(start_time, _estimate_full_cost())
        return 0

    except Exception as exc:
        elapsed = time.perf_counter() - start_time
        print(f"[Main] Workflow failed: {exc}")
        deliver_failure_alert(exc, elapsed)
        return 1


def _parse_args() -> argparse.Namespace:
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
        "--ibkr-only",
        action="store_true",
        help="Only fetch and print the IBKR portfolio snapshot without market news or AI analysis.",
    )
    parser.add_argument(
        "--ibkr-payload",
        action="store_true",
        help="Only fetch IBKR data and print an analysis-ready JSON payload.",
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Send the generated output to Telegram.",
    )
    return parser.parse_args()


def _print_runtime(start_time: float, estimated_cost: float) -> None:
    elapsed = time.perf_counter() - start_time
    print(f"[Main] Total runtime: {elapsed:.2f}s")
    print(f"[Main] Estimated cost: {estimated_cost:.2f} USD")


def _estimate_full_cost() -> float:
    return 0.02 + 0.012 + 0.04  # grok + perplexity news + perplexity claude


def _estimate_news_cost() -> float:
    return 0.02 + 0.02  # grok + perplexity


if __name__ == "__main__":
    sys.exit(main())
