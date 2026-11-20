"""Stateless funding scenario calculations for the v1.2 methodology."""

import argparse
import json
from dataclasses import asdict, dataclass
from decimal import Context, Decimal, Inexact, InvalidOperation, localcontext

DecimalInput = Decimal | int | str
METHODOLOGY_VERSION = "funding-scenario-v1"
MAX_INTEGER_DIGITS = 38
MAX_FRACTION_DIGITS = 38
MAX_INPUT_LENGTH = 128
# The formula multiplies four bounded decimals and converts between basis points and percent.
CALCULATION_PRECISION = 4 * (MAX_INTEGER_DIGITS + MAX_FRACTION_DIGITS) + 16
FORMULA = "principal_usd * repricing_share * (shock_bps / 10000) * horizon_years"
ASSUMPTIONS = (
    "Simple interest uses a constant repricing principal and annual rate shock throughout the horizon.",
    "The scenario assumes unhedged debt with no amortization, fees, tax effects, or staggered repricing.",
)


def decimal_input(field: str, value: DecimalInput) -> Decimal:
    bounds = f"{field} supports up to {MAX_INTEGER_DIGITS} integer and {MAX_FRACTION_DIGITS} fractional digits"
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ValueError(f"{field} must be a decimal string, integer, or Decimal")
    if isinstance(value, str) and len(value) > MAX_INPUT_LENGTH:
        raise ValueError(f"{field} must use at most {MAX_INPUT_LENGTH} input characters")
    if isinstance(value, int) and abs(value) >= 10 ** MAX_INTEGER_DIGITS:
        raise ValueError(bounds)

    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{field} must be a finite decimal") from None
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    if result.is_zero():
        return Decimal(0)
    if result.adjusted() >= MAX_INTEGER_DIGITS or result.as_tuple().exponent < -MAX_FRACTION_DIGITS:
        raise ValueError(bounds)
    return result


def decimal_string(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


@dataclass(frozen=True)
class IllustrativeCoupon:
    reference_yield_percent: Decimal
    spread_bps: Decimal
    baseline_coupon_percent: Decimal
    shocked_coupon_percent: Decimal
    baseline_interest_usd: Decimal
    shocked_interest_usd: Decimal


@dataclass(frozen=True)
class FundingScenarioResult:
    principal_usd: Decimal
    repricing_share: Decimal
    shock_bps: Decimal
    horizon_years: Decimal
    repricing_principal_usd: Decimal
    annual_shock_decimal: Decimal
    incremental_interest_usd: Decimal
    illustrative_coupon: IllustrativeCoupon | None

    def to_dict(self) -> dict[str, object]:
        coupon = self.illustrative_coupon
        return {
            "methodology_version": METHODOLOGY_VERSION,
            "currency": "USD",
            "inputs": {
                "principal_usd": decimal_string(self.principal_usd),
                "repricing_share": decimal_string(self.repricing_share),
                "shock_bps": decimal_string(self.shock_bps),
                "horizon_years": decimal_string(self.horizon_years),
            },
            "repricing_principal_usd": decimal_string(self.repricing_principal_usd),
            "annual_shock_decimal": decimal_string(self.annual_shock_decimal),
            "incremental_interest_usd": decimal_string(self.incremental_interest_usd),
            "illustrative_coupon": (
                {name: decimal_string(value) for name, value in asdict(coupon).items()} if coupon else None
            ),
            "formula": FORMULA,
            "assumptions": list(ASSUMPTIONS),
        }


def calculate_funding_scenario(
    *,
    principal_usd: DecimalInput,
    repricing_share: DecimalInput,
    shock_bps: DecimalInput,
    horizon_years: DecimalInput,
    reference_yield_percent: DecimalInput | None = None,
    spread_bps: DecimalInput | None = None,
) -> FundingScenarioResult:
    """Calculate the signed change in total interest over the supplied horizon."""
    principal = decimal_input("principal_usd", principal_usd)
    share = decimal_input("repricing_share", repricing_share)
    shock = decimal_input("shock_bps", shock_bps)
    horizon = decimal_input("horizon_years", horizon_years)

    if principal < 0:
        raise ValueError("principal_usd must be nonnegative")
    if not 0 <= share <= 1:
        raise ValueError("repricing_share must be between 0 and 1 inclusive")
    if horizon < 0:
        raise ValueError("horizon_years must be nonnegative")
    if (reference_yield_percent is None) != (spread_bps is None):
        raise ValueError("reference_yield_percent and spread_bps must be supplied together")

    with localcontext(Context(prec=CALCULATION_PRECISION)) as calculation:
        calculation.traps[Inexact] = True
        repricing_principal = principal * share
        shock_decimal = shock / 10000
        incremental_interest = repricing_principal * shock_decimal * horizon
        coupon = None
        if reference_yield_percent is not None:
            reference = decimal_input("reference_yield_percent", reference_yield_percent)
            spread = decimal_input("spread_bps", spread_bps)
            baseline = reference + spread / 100
            baseline_interest = repricing_principal * (baseline / 100) * horizon
            coupon = IllustrativeCoupon(
                reference_yield_percent=reference,
                spread_bps=spread,
                baseline_coupon_percent=baseline,
                shocked_coupon_percent=baseline + shock / 100,
                baseline_interest_usd=baseline_interest,
                shocked_interest_usd=baseline_interest + incremental_interest,
            )

    return FundingScenarioResult(
        principal_usd=principal,
        repricing_share=share,
        shock_bps=shock,
        horizon_years=horizon,
        repricing_principal_usd=repricing_principal,
        annual_shock_decimal=shock_decimal,
        incremental_interest_usd=incremental_interest,
        illustrative_coupon=coupon,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate a simple annual rate shock on USD funding.")
    parser.add_argument("--principal-usd", required=True, help="USD principal before applying the repricing share")
    parser.add_argument("--repricing-share", required=True, help="Share that reprices, e.g. 0.25 for 25%%")
    parser.add_argument("--shock-bps", required=True, help="Signed annual rate shock in basis points")
    parser.add_argument("--horizon-years", required=True, help="Exposure horizon in years, e.g. 0.5 for six months")
    parser.add_argument("--reference-yield-percent", help="Illustrative reference yield as a percentage, e.g. 4.21")
    parser.add_argument("--spread-bps", help="User-entered spread over the reference yield in basis points")
    try:
        result = calculate_funding_scenario(**vars(parser.parse_args()))
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
