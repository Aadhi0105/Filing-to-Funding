# Funding scenario calculator

The calculator estimates the **change in total interest in USD** over a user-specified horizon. It uses the simple-interest funding formula from v1.2. [Funding methodology](filing-to-funding-audit-v1.2.md#funding-scenarios)

```text
Repricing principal = principal × repricing share
Incremental interest = repricing principal × (annual shock in basis points ÷ 10,000) × years
```

| Input | Convention |
|---|---|
| Principal | USD debt amount in scope before applying the repricing share. Enter a nonnegative amount. |
| Repricing share | Fraction between 0 and 1 inclusive. Enter `0.25` for 25%. |
| Annual shock | Signed basis points. Enter `100` for a one-percentage-point increase or `-100` for a decrease. |
| Horizon | Nonnegative years. Enter `0.5` for six months. |

Positive incremental interest means an increase in interest expense. A negative result means a decrease. The calculation uses simple interest with the same repricing principal and shock throughout the horizon. It assumes unhedged debt with no amortization, fees, tax effects, or staggered repricing.

## Run the documented example

From the repository root, run:

```sh
python3 -m apps.api.funding_scenario \
  --principal-usd 2000000000 --repricing-share 0.25 \
  --shock-bps 100 --horizon-years 1
```

The result shows **$500 million** of repricing principal and **$5 million** of additional interest. A 100 bp cut over half a year gives a **$2.5 million reduction** on the same exposure.

### Show an illustrative coupon

Supply both `--reference-yield-percent` and `--spread-bps` to add the assumed starting coupon and the shocked coupon. For example, enter the 4.21% 10-year reference yield observed on 24 October 2024 and a hypothetical 150 bp spread. [Treasury history](treasury_history.md#date-selection-and-vintages)

```sh
python3 -m apps.api.funding_scenario \
  --principal-usd 2000000000 --repricing-share 0.25 \
  --shock-bps 100 --horizon-years 1 \
  --reference-yield-percent 4.21 --spread-bps 150
```

The baseline is **5.71%** and the shocked coupon is **6.71%**. Baseline interest is **$28.55 million** and shocked interest is **$33.55 million**, both on the $500 million repricing principal for one year. The difference stays **$5 million**. The model applies the signed shock without a coupon floor.

## Calculation and tests

The Python function `calculate_funding_scenario` uses exact decimal arithmetic and returns the inputs, repricing principal, annual shock, incremental interest, and optional coupon illustration. The JSON includes the formula, currency, assumptions, and methodology version `funding-scenario-v1`. Numeric fields are decimal strings and preserve fractional-cent precision for presentation to round later. Enter unformatted decimal values. Each input supports up to 38 integer digits and 38 fractional places.

Run the offline tests from the repository root:

```sh
python3 -m unittest discover -s apps/api/tests -v
```

The suite covers the documented example, signed rate cuts, fractional and zero inputs, malformed values, coupon math, and the command-line output.
