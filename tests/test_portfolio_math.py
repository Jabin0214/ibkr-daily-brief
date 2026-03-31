from __future__ import annotations

import unittest

from src.core.analysis.position_analysis import build_research_plan, normalize_portfolio
from src.core.providers.ibkr_client import _parse_portfolio_xml
from src.core.providers.news_client import _join_lines


SAMPLE_XML = """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U1" acctAlias="Growth">
      <EquitySummaryByReportDateInBase currency="HKD" reportDate="2026-03-19" cash="100000" netLiquidation="1000000" />
      <MTMPerformanceSummaryUnderlying description="Total P/L" total="-8564" />
      <OpenPosition
        acctAlias="Growth"
        accountId="U1"
        assetCategory="STK"
        symbol="AAPL"
        description="APPLE INC"
        currency="USD"
        position="200"
        costBasisPrice="255.17441804"
        costBasisMoney="51034.883608"
        markPrice="248.96"
        positionValue="49792"
        fifoPnlUnrealized="-1242.883608"
        fxRateToBase="7.8337"
        percentOfNAV="88.38"
        reportDate="20260319"
        side="Long"
      />
      <OpenPosition
        acctAlias="Growth"
        accountId="U1"
        assetCategory="OPT"
        symbol="TCH MAR26 530 P"
        description="700 30MAR26 530 P"
        currency="HKD"
        position="-1"
        costBasisPrice="4.19"
        costBasisMoney="-419"
        markPrice="21.2"
        positionValue="-2120"
        fifoPnlUnrealized="-1701"
        fxRateToBase="1"
        percentOfNAV="100.00"
        reportDate="20260319"
        side="Short"
      />
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


class PortfolioMathTests(unittest.TestCase):
    def test_cross_currency_weight_uses_base_value(self) -> None:
        parsed = _parse_portfolio_xml(SAMPLE_XML)
        normalized = normalize_portfolio(parsed)

        aapl = next(position for position in normalized["positions"] if position["symbol"] == "AAPL")
        self.assertAlmostEqual(aapl["market_value_base"], 390055.59, places=2)
        self.assertAlmostEqual(aapl["weight_pct"], 39.01, places=2)
        self.assertAlmostEqual(aapl["net_weight_pct"], 39.01, places=2)

    def test_short_position_uses_unrealized_pnl_direction(self) -> None:
        parsed = _parse_portfolio_xml(SAMPLE_XML)
        normalized = normalize_portfolio(parsed)

        short_put = next(
            position for position in normalized["positions"] if position["symbol"] == "TCH MAR26 530 P"
        )
        self.assertEqual(short_put["side"], "Short")
        self.assertAlmostEqual(short_put["pnl_pct"], -406.0, places=1)
        self.assertAlmostEqual(short_put["weight_pct"], 0.21, places=2)
        self.assertAlmostEqual(short_put["net_weight_pct"], -0.21, places=2)

    def test_programmatic_research_plan_prioritizes_risk_assets(self) -> None:
        positions = normalize_portfolio(
            {
                "account_id": "TEST",
                "scope": "mock",
                "base_currency": "HKD",
                "cash": 120000,
                "total_value": 1166442.75,
                "daily_pnl": -5093.64,
                "positions": [
                    {
                        "symbol": "SGOV",
                        "description": "ISHARES TREASURY BOND ETF",
                        "currency": "USD",
                        "side": "Long",
                        "asset_category": "STK",
                        "market_value": 50290,
                        "market_value_base": 393932,
                        "pnl_pct": 0.1,
                    },
                    {
                        "symbol": "AAPL",
                        "description": "APPLE INC",
                        "currency": "USD",
                        "side": "Long",
                        "asset_category": "STK",
                        "market_value": 49598,
                        "market_value_base": 388511,
                        "pnl_pct": -2.8,
                    },
                    {
                        "symbol": "700",
                        "description": "TENCENT HOLDINGS LTD",
                        "currency": "HKD",
                        "side": "Long",
                        "asset_category": "STK",
                        "market_value": 50800,
                        "market_value_base": 50800,
                        "pnl_pct": -15.5,
                    },
                    {
                        "symbol": "TCH MAR26 530 P",
                        "description": "700 30MAR26 530 P",
                        "currency": "HKD",
                        "side": "Short",
                        "asset_category": "OPT",
                        "market_value": -2450,
                        "market_value_base": -2450,
                        "pnl_pct": -472.8,
                    },
                ],
            }
        )

        plan = build_research_plan(positions)
        self.assertIn("AAPL", plan["focus_symbols"])
        self.assertIn("700", plan["focus_symbols"])
        self.assertIn("TCH MAR26 530 P", plan["focus_symbols"])
        self.assertIn("期权到期与波动率风险", plan["focus_themes"])
        self.assertTrue(any("short" in flag.lower() for flag in plan["risk_flags"]))

    def test_market_bundle_filters_empty_news_items(self) -> None:
        text = _join_lines(
            [
                "700 | 无72小时内直接新闻。空。",
                "AAPL | 3月19日股价跌0.392%至248.96美元 | 重仓波动继续放大组合回撤",
                "JEPQ | 暂无相关新闻",
            ],
            "fallback",
        )
        self.assertEqual(
            text,
            "AAPL | 3月19日股价跌0.392%至248.96美元 | 重仓波动继续放大组合回撤",
        )


if __name__ == "__main__":
    unittest.main()
