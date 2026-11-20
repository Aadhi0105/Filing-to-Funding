# Historical financial ratios

Task 4 added **355 observations** from the archived SEC filings to the three-company PostgreSQL database. The new observations include 135 revenue values, 135 net-income values, 79 total-assets balances, and six Dover lease disclosures. There are now 1,044 qualified statement observations. [Filing-by-filing qualification](sec_statement_coverage.csv)

## Coverage at the 19 November 2026 cutoff

| Issuer | Quarterly FCF margin and cash conversion | Trailing 12-month FCF margin and cash conversion | Base periods with verified borrowing-debt ratios |
|---|---:|---:|---:|
| Illinois Tool Works | 23 of 23 | 20 of 23 | 0 of 23 |
| Dover | 23 of 23 | 19 of 23 | 5 of 23 |
| Rockwell Automation | 20 of 20 | 17 of 20 | 4 of 20 |
| **Total** | **66 of 66** | **56 of 66** | **9 of 66** |

The 10 unavailable trailing periods lack four compatible quarters on the selected reporting scope. Earlier historical cutoffs can have lower coverage. The borrowing-ratio count is narrower than the reported-debt count because it requires filing evidence for the treatment of lease liabilities.

## Metric rules

| Metric | Formula and eligibility |
|---|---|
| FCF margin | Qualified free cash flow divided by positive revenue. Each cumulative revenue input comes from the same filing, period and reporting scope as the corresponding cash-flow input. |
| Cash conversion | Qualified operating cash flow divided by positive net income. Use consolidated net income for consolidated operating cash flow and the explicitly reported continuing-operations earnings line for that scope. Capex is independent of this ratio. |
| Debt-to-assets | Verified borrowing debt divided by positive total assets from the same balance sheet. |
| Cash-to-debt | Balance-sheet cash and equivalents divided by positive verified borrowing debt from the same balance sheet. |
| Net borrowing debt | Verified borrowing debt less balance-sheet cash and equivalents. Retain negative values. |

Quarterly flow ratios use differences between adjacent year-to-date disclosures where needed. Trailing ratios divide the sum of four compatible quarterly numerators by the sum of the corresponding denominators. They apply the positive-denominator rule to the entire trailing window. The PostgreSQL results return the numerator, denominator, status, fact IDs, and source accessions for each ratio. A missing or conflicting input withholds the value.

For Rockwell, the consolidated net-income line is the appropriate denominator for consolidated operating cash flow. The parent-attributable line is a separate measure. For Dover after the ESG disposal, the scope for revenue, operating cash flow, and earnings is qualified against the continuing-operations presentation. [Rockwell FY2026 annual report](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000048/rok-20260930.htm) · [Dover 2025 half-year report](https://www.sec.gov/Archives/edgar/data/29905/000002990525000024/dov-20250630.htm)

Dover's FY2021–FY2025 annual notes place finance leases in accrued expenses and other liabilities. The borrowing basis therefore uses the qualified debt lines directly. Rockwell's FY2023–FY2026 annual notes place finance leases in both current and noncurrent debt, so the disclosed total is deducted once. The older Rockwell presentation included current finance leases in other current liabilities. ITW's borrowing ratios and the remaining periods stay unavailable until the applicable lease treatment and amounts can be verified. [Dover FY2025 annual report](https://www.sec.gov/Archives/edgar/data/29905/000002990526000009/dov-20251231.htm) · [Rockwell FY2022 annual report](https://www.sec.gov/Archives/edgar/data/1024478/000102447822000093/rok-20220930.htm)

## Reconciled results

| Case | Verified result |
|---|---|
| ITW FY2026 Q2 | **14.67% FCF margin** from $631M free cash flow and $4.301B revenue. **0.887× cash conversion** from $723M CFO and $815M consolidated net income. |
| Dover FY2024 Q3 continuing operations | The 24 October 2024 cutoff lacks a compatible first-half disclosure. The 24 July 2025 cutoff supports **15.91% FCF margin** and **1.129× cash conversion**. The results trace to the nine-month report and the later first-half comparative. |
| Rockwell FY2026 annual | **18.92% trailing FCF margin** and **1.392× cash conversion**. The same filing provides **$3.276B borrowing debt**, **29.07% debt-to-assets**, and **0.132× cash-to-debt**. |

[ITW FY2026 Q2 report](https://www.sec.gov/Archives/edgar/data/49826/000004982626000049/itw-20260630.htm) · [Dover Q3 2024 report](https://www.sec.gov/Archives/edgar/data/29905/000002990524000045/dov-20240930.htm) · [Rockwell FY2026 annual report](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000048/rok-20260930.htm)

## Run locally

Apply migration 005 with the [standard migration command](data_dictionary.md#reproduce-the-database-with-docker-compose), then replay the [qualified statement import](historical_correctness.md#reproduce-locally) from the project archive.

```sql
SELECT metric, value, numerator, denominator, status, source_accessions
FROM analytics.historical_cash_flow_ratios(
    '0000049826', 2026, 2, 'consolidated', 'itw_from_fifo_change', 'quarter', DATE '2026-08-06'
);

SELECT metric, value, unit, status, debt_basis, source_accessions
FROM analytics.historical_borrowing_metrics('0001024478', DATE '2026-09-30', DATE '2026-11-12');
```

Use `ttm` for a trailing flow ratio. Flow ratios are numeric fractions. A null filing cutoff selects the latest compatible disclosures held locally. A date applies the New York end-of-day cutoff.

The six PostgreSQL test scripts passed on a clean rebuild and on the existing project database. Replaying the archived import inserted zero rows. Regression cases cover missing capex, missing same-filing revenue, conflicting revenue, a loss quarter inside a profitable trailing window, zero assets, and negative net borrowing debt.
