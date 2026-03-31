from __future__ import annotations

import unittest

from src.ibkr_middleware import build_ibkr_analysis_payload


SAMPLE_XML = """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement accountId="U1" acctAlias="Growth" fromDate="20260327" toDate="20260327">
      <EquitySummaryInBase />
      <EquitySummaryByReportDateInBase currency="HKD" reportDate="20260327" cash="100000" netLiquidation="1000000" />
      <MTMPerformanceSummaryInBase>
        <MTMPerformanceSummaryUnderlying description="Total P/L" total="-8564" />
      </MTMPerformanceSummaryInBase>
      <CashReport>
        <CashReportCurrency currency="BASE_SUMMARY" reportDate="20260327" endingCash="100000" dividends="320.5" withholdingTax="-48.08" interest="11.2" />
        <CashReportCurrency currency="USD" reportDate="20260327" endingCash="12000" />
      </CashReport>
      <OpenPositions>
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
          percentOfNAV="39.01"
          reportDate="20260327"
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
          percentOfNAV="0.21"
          reportDate="20260327"
          side="Short"
        />
      </OpenPositions>
      <Trades>
        <Trade
          symbol="AAPL"
          description="APPLE INC"
          assetCategory="STK"
          currency="USD"
          buySell="BUY"
          quantity="20"
          tradePrice="249.5"
          netCash="-4990"
          ibCommission="-1.2"
          tradeDate="20260327"
          tradeTime="093500"
          ibOrderID="12345"
        />
      </Trades>
      <CashTransactions>
        <CashTransaction
          currency="USD"
          description="Dividend AAPL"
          symbol="AAPL"
          amount="40.0"
          settleDate="20260327"
          reportDate="20260327"
        />
        <CashTransaction
          currency="USD"
          description="Withholding Tax"
          amount="-6.0"
          settleDate="20260327"
          reportDate="20260327"
        />
      </CashTransactions>
      <OptionEAE>
        <OptionEvent
          symbol="TCH MAR26 530 P"
          description="Expired option"
          currency="HKD"
          transactionType="Expiration"
          quantity="-1"
          strike="530"
          expiry="20260330"
          reportDate="20260327"
          proceeds="0"
        />
      </OptionEAE>
      <ConversionRates>
        <ConversionRate fromCurrency="USD" toCurrency="HKD" rate="7.83" reportDate="20260327" />
      </ConversionRates>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>
"""


class IbkrMiddlewareTests(unittest.TestCase):
    def test_build_payload_extracts_analysis_ready_sections(self) -> None:
        payload = build_ibkr_analysis_payload(SAMPLE_XML)

        self.assertEqual(payload["meta"]["report_date"], "2026-03-27")
        self.assertEqual(payload["meta"]["sections"]["Trades"]["non_empty_accounts"], 1)
        self.assertEqual(payload["portfolio"]["base_currency"] if "base_currency" in payload["portfolio"] else "HKD", "HKD")
        self.assertEqual(payload["insights"]["counts"]["trades"], 1)
        self.assertEqual(payload["insights"]["counts"]["cash_transactions"], 2)
        self.assertEqual(payload["insights"]["counts"]["option_events"], 1)

        trade = payload["trades"][0]
        self.assertEqual(trade["symbol"], "AAPL")
        self.assertEqual(trade["action"], "BUY")
        self.assertAlmostEqual(trade["trade_price"], 249.5)

        dividend = payload["cash_transactions"][0]
        self.assertEqual(dividend["category"], "dividend")
        self.assertAlmostEqual(dividend["amount_base"], 313.2, places=2)

        option_event = payload["option_events"][0]
        self.assertEqual(option_event["event_type"], "Expiration")
        self.assertEqual(option_event["expiry"], "2026-03-30")

    def test_build_payload_derives_risk_flags_and_concentration(self) -> None:
        payload = build_ibkr_analysis_payload(SAMPLE_XML)

        top_holding = payload["insights"]["concentration"]["top_holdings"][0]
        self.assertEqual(top_holding["symbol"], "AAPL")
        self.assertGreater(top_holding["weight_pct"], 30)

        flag_types = {flag["type"] for flag in payload["insights"]["risk_flags"]}
        self.assertIn("concentration", flag_types)
        self.assertIn("short_option_loss", flag_types)


if __name__ == "__main__":
    unittest.main()
