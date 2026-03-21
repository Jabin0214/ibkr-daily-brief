from __future__ import annotations

import unittest

from main import _normalize_portfolio
from src.ibkr_data import _parse_portfolio_xml


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
        normalized = _normalize_portfolio(parsed)

        aapl = next(position for position in normalized["positions"] if position["symbol"] == "AAPL")
        self.assertAlmostEqual(aapl["market_value_base"], 390055.59, places=2)
        self.assertAlmostEqual(aapl["weight_pct"], 39.01, places=2)
        self.assertAlmostEqual(aapl["net_weight_pct"], 39.01, places=2)

    def test_short_position_uses_unrealized_pnl_direction(self) -> None:
        parsed = _parse_portfolio_xml(SAMPLE_XML)
        normalized = _normalize_portfolio(parsed)

        short_put = next(
            position for position in normalized["positions"] if position["symbol"] == "TCH MAR26 530 P"
        )
        self.assertEqual(short_put["side"], "Short")
        self.assertAlmostEqual(short_put["pnl_pct"], -406.0, places=1)
        self.assertAlmostEqual(short_put["weight_pct"], 0.21, places=2)
        self.assertAlmostEqual(short_put["net_weight_pct"], -0.21, places=2)


if __name__ == "__main__":
    unittest.main()
