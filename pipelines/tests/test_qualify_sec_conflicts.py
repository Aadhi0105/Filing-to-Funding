"""Regression tests for conflicts found while qualifying SEC filing statements."""

import contextlib
import csv
import io
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from xml.etree.ElementTree import Element

from pipelines import qualify_sec


class FilingConflictTest(unittest.TestCase):
    period_end = date(2021, 6, 30)
    instant = (None, period_end)
    cumulative = (date(2021, 1, 1), period_end)
    filing = {
        "accession": "0000049826-21-000064", "cik": "0000049826", "ticker": "ITW",
        "fiscal_year": "2021", "fiscal_period": "Q2", "report_end": period_end.isoformat(),
        "window": "coverage", "filing_url": "https://www.sec.gov/Archives/edgar/data/example.htm",
    }
    source = {"member": "filing.htm", "sha256": "a" * 64}

    @staticmethod
    def row(label, tag, period, amount, node_id, decimals="-6"):
        node = Element("fact", {"id": node_id, "name": f"us-gaap:{tag}", "decimals": decimals, "scale": "6"})
        node.text = str(amount)
        return (label, tag, period, node)

    def balance_table(self, *cash):
        return [
            self.row("", "Assets", self.instant, 16000, "assets"),
            self.row("total current assets", "AssetsCurrent", self.instant, 6000, "current-assets"),
            self.row("total current liabilities", "LiabilitiesCurrent", self.instant, 4000, "current-liabilities"),
            *(self.row("cash and cash equivalents", "CashAndCashEquivalentsAtCarryingValue",
                       self.instant, amount, f"cash-{index}", decimals)
              for index, (amount, decimals) in enumerate(cash)),
        ]

    def qualify(self, *tables):
        with patch.object(qualify_sec, "load_document", return_value=Element("filing")):
            with patch.object(qualify_sec, "statement_rows", return_value=tables):
                return qualify_sec.qualify(self.filing, self.source, {self.period_end})

    def coverage(self, facts):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            qualify_sec.report([(self.filing, self.source, facts)])
        return next(csv.DictReader(io.StringIO(output.getvalue())))

    def test_omitted_cash_has_no_observation(self):
        facts = self.qualify(self.balance_table())
        self.assertFalse(any(fact["concept"] == "cash_and_equivalents" for fact in facts))
        self.assertEqual(self.coverage(facts)["liquidity_inputs"], "missing_statement_inputs")

    def test_conflicting_cash_keeps_both_values_and_locators(self):
        facts = self.qualify(self.balance_table((1400, "-6"), (1500, "-6")))
        cash = [fact for fact in facts if fact["concept"] == "cash_and_equivalents"]
        self.assertEqual(
            [(Decimal(fact["value"]), fact["source_locator"]) for fact in cash],
            [(Decimal(1400000000), "filing.htm#cash-0"), (Decimal(1500000000), "filing.htm#cash-1")],
        )
        coverage = self.coverage(facts)
        self.assertEqual(coverage["liquidity_inputs"], "conflicting_observations")
        self.assertEqual(coverage["cash_source_tag"], "")

    def test_ambiguous_primary_tables_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Ambiguous primary balance sheets in 0000049826-21-000064"):
            self.qualify(self.balance_table((1400, "-6")), self.balance_table((1500, "-6")))

    def test_equal_amounts_with_different_precision_are_not_conflicts(self):
        facts = self.qualify(self.balance_table((1400, "-6"), (1400, "-6"), (1400, "-3")))
        cash = [fact for fact in facts if fact["concept"] == "cash_and_equivalents"]
        self.assertEqual([fact["reported_decimals"] for fact in cash], ["-6", "-3"])
        self.assertEqual(self.coverage(facts)["liquidity_inputs"], "qualified")

    def test_cash_flow_and_earnings_conflicts_retained_in_their_scope(self):
        flow = [
            self.row("operating activities", qualify_sec.TOTAL_CFO, self.cumulative, 100, "cfo-1"),
            self.row("operating activities", qualify_sec.TOTAL_CFO, self.cumulative, 120, "cfo-2"),
            self.row("capital expenditures", "PaymentsToAcquirePropertyPlantAndEquipment",
                     self.cumulative, 30, "capex"),
        ]
        earnings = [
            self.row("operating revenue", "RevenueFromContractWithCustomerExcludingAssessedTax",
                     self.cumulative, amount, f"revenue-{amount}") for amount in (500, 510)
        ] + [
            self.row("net income", "ProfitLoss", self.cumulative, 70, "earnings"),
            self.row("operating income", "OperatingIncomeLoss", self.cumulative, 85, "operating-income"),
        ]
        facts = self.qualify(flow, earnings)
        self.assertEqual(
            [fact["concept"] for fact in facts],
            ["operating_cash_flow", "operating_cash_flow", "cash_capex_outflow", "revenue", "revenue", "net_income"],
        )
        self.assertEqual({fact["scope_key"] for fact in facts}, {"itw_before_fifo_change"})
        coverage = self.coverage(facts)
        self.assertEqual(coverage["cash_flow_inputs"], "conflicting_observations")
        self.assertEqual(coverage["revenue_inputs"], "conflicting_observations")
        self.assertEqual(coverage["net_income_inputs"], "qualified")


if __name__ == "__main__":
    unittest.main()
