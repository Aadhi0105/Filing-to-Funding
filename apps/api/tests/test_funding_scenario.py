import json
import subprocess
import sys
import unittest
from decimal import Decimal, Inexact, localcontext
from fractions import Fraction

from apps.api.funding_scenario import calculate_funding_scenario


EXAMPLE = {
    "principal_usd": "2000000000",
    "repricing_share": "0.25",
    "shock_bps": "100",
    "horizon_years": "1",
}
CLI = [
    sys.executable, "-B", "-m", "apps.api.funding_scenario",
    "--principal-usd", "2000000000", "--repricing-share", "0.25",
    "--shock-bps", "100", "--horizon-years", "1",
]


def scenario(**overrides):
    return calculate_funding_scenario(**(EXAMPLE | overrides))


class FundingScenarioTests(unittest.TestCase):
    def test_documented_example(self):
        result = scenario()
        self.assertEqual(result.repricing_principal_usd, Decimal("500000000"))
        self.assertEqual(result.annual_shock_decimal, Decimal("0.01"))
        self.assertEqual(result.incremental_interest_usd, Decimal("5000000"))
        self.assertIsNone(result.illustrative_coupon)

    def test_rate_cut_produces_a_signed_saving(self):
        result = scenario(shock_bps=-100, horizon_years="0.5")
        self.assertEqual(result.incremental_interest_usd, Decimal("-2500000"))

    def test_each_zero_operand_gives_zero_change(self):
        for field in EXAMPLE:
            with self.subTest(field=field):
                self.assertEqual(scenario(**{field: "0"}).incremental_interest_usd, Decimal(0))

    def test_full_repricing_is_allowed(self):
        result = scenario(repricing_share=1)
        self.assertEqual(result.repricing_principal_usd, Decimal("2000000000"))
        self.assertEqual(result.incremental_interest_usd, Decimal("20000000"))

    def test_fractional_basis_points_and_horizon_preserve_subcent_precision(self):
        with localcontext() as caller:
            caller.prec = 2
            caller.traps[Inexact] = True
            result = scenario(principal_usd="1000.01", repricing_share="0.125",
                              shock_bps="12.5", horizon_years="0.5")
            self.assertEqual(result.incremental_interest_usd, Decimal("0.07812578125"))
            self.assertEqual(result.to_dict()["incremental_interest_usd"], "0.07812578125")

    def test_supported_decimal_limits_still_calculate_exactly(self):
        largest = "9" * 38 + "." + "9" * 38
        share = "0." + "9" * 38
        result = scenario(principal_usd=largest, repricing_share=share, shock_bps=largest,
                          horizon_years=largest, reference_yield_percent=largest, spread_bps=largest)
        exact = Fraction(largest) * Fraction(share) * Fraction(largest) * Fraction(largest) / 10000
        self.assertEqual(Fraction(result.incremental_interest_usd), exact)
        coupon = result.illustrative_coupon
        self.assertEqual(Fraction(coupon.shocked_interest_usd) - Fraction(coupon.baseline_interest_usd), exact)

    def test_optional_coupon_keeps_baseline_and_incremental_interest_separate(self):
        result = scenario(reference_yield_percent="4.21", spread_bps=150)
        coupon = result.illustrative_coupon
        self.assertEqual(coupon.baseline_coupon_percent, Decimal("5.71"))
        self.assertEqual(coupon.shocked_coupon_percent, Decimal("6.71"))
        self.assertEqual(coupon.baseline_interest_usd, Decimal("28550000"))
        self.assertEqual(coupon.shocked_interest_usd, Decimal("33550000"))
        self.assertEqual(coupon.shocked_interest_usd - coupon.baseline_interest_usd,
                         result.incremental_interest_usd)
        self.assertEqual(result.incremental_interest_usd, scenario().incremental_interest_usd)

    def test_negative_shocked_coupon_preserves_the_signed_shock(self):
        result = scenario(reference_yield_percent="1", spread_bps=0, shock_bps=-200)
        coupon = result.illustrative_coupon
        self.assertEqual(coupon.shocked_coupon_percent, Decimal("-1"))
        self.assertEqual(result.incremental_interest_usd, Decimal("-10000000"))

    def test_coupon_inputs_must_be_supplied_as_a_pair(self):
        for inputs in ({"reference_yield_percent": "4.21"}, {"spread_bps": 150}):
            with self.subTest(inputs=inputs):
                with self.assertRaisesRegex(ValueError, "must be supplied together"):
                    scenario(**inputs)

    def test_invalid_inputs_are_rejected(self):
        for field, value in (
            ("principal_usd", -1), ("repricing_share", "-0.01"), ("repricing_share", "1.01"),
            ("horizon_years", "-0.5"), ("shock_bps", float("inf")), ("shock_bps", 0.1),
            ("shock_bps", "Infinity"), ("shock_bps", "NaN"), ("shock_bps", "50bps"),
            ("repricing_share", True), ("principal_usd", "1e999999999"),
            ("principal_usd", 10 ** 38), ("shock_bps", "1e-39"), ("shock_bps", " " * 129),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ValueError, field):
                    scenario(**{field: value})

    def test_cli_returns_exact_strings_and_assumptions(self):
        process = subprocess.run(
            [*CLI, "--reference-yield-percent", "4.21", "--spread-bps", "150"],
            check=True, capture_output=True, text=True,
        )
        payload = json.loads(process.stdout)
        self.assertEqual(payload["currency"], "USD")
        self.assertEqual(payload["methodology_version"], "funding-scenario-v1")
        self.assertEqual(payload["inputs"]["repricing_share"], "0.25")
        self.assertEqual(payload["incremental_interest_usd"], "5000000")
        self.assertEqual(payload["illustrative_coupon"]["shocked_coupon_percent"], "6.71")
        self.assertTrue(payload["assumptions"])

    def test_cli_reports_input_errors(self):
        process = subprocess.run(
            [*CLI, "--reference-yield-percent", "4.21"], capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, "")
        self.assertIn("must be supplied together", process.stderr)


if __name__ == "__main__":
    unittest.main()
