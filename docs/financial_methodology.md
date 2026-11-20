# Pilot financial calculations and historical cutoffs

Task 5 implements the tested subset of the [v1.2 methodology](filing-to-funding-audit-v1.2.md). The expected values come from the [filing reconciliation](pilot_reconciliation.md). The SQL reads the reviewed SEC extracts already loaded in PostgreSQL.

## Select the filing evidence

`analytics.pilot_facts` selects facts for one issuer, interval or balance-sheet date, reporting basis, and scope. In the reviewed sample the inputs are consolidated-entity USD statement lines without XBRL dimensions. Amounts are exact PostgreSQL numerics at the precision transcribed from each filing.

- **Latest reported:** omit the cutoff to select the newest reviewed disclosure for each concept. If the newest day's acceptance times are incomplete, ordering within that day is uncertain. Preserve the candidates and flag conflicting values.
- **Filed by date:** provide a cutoff date. A fact is eligible only if its reporting period has ended, its SEC filing date is on or before the cutoff, and its verified acceptance instant is before the next midnight in `America/New_York`. Missing acceptance metadata excludes the filing from this mode.

The reporting basis and scope must match across inputs. A later continuing-operations comparative can fill a gap in its own scope. The original observation remains queryable under its original scope. The ordering uses SEC filing metadata. The import and database insertion times are independent of filing eligibility.

## Calculate balances and quarterly flows

| SQL function | Verified behavior |
|---|---|
| `analytics.pilot_balance_sheet` | Working capital is current assets minus current liabilities. The current and cash ratios require positive current liabilities. The cash ratio uses the balance-sheet cash line. Its numerator excludes separately disclosed cash held for sale. |
| `analytics.pilot_balance_sheet` | Reported debt uses non-overlapping current and noncurrent lines. For Rockwell, add short-term debt, the current portion of long-term debt, and noncurrent debt. The separate borrowing-debt calculation subtracts same-date finance lease liabilities when the note supplies them. Net debt subtracts balance-sheet cash. |
| `analytics.pilot_quarter_cash_flow` | Q1 uses the first-quarter amount. Later quarters subtract the previous cumulative amount from the current one using the same fiscal-year start, adjacent fiscal boundaries, and matching reporting scopes. Rockwell's Q4 uses the September 10-K and the June 10-Q. Each cumulative cash-flow and capex pair must come from the same filing. |
| `analytics.pilot_quarter_cash_flow` | Calculate standalone capex from the signed cash outflow rows and expose it as a positive spend. Free cash flow is the standalone operating cash flow minus standalone cash capex. |

Both calculation functions return a status, fact IDs, and filing accessions. Balance-sheet operands must come from a single filing. Cash-flow calculations may combine eligible filings across the adjacent cumulative periods. A missing compatible operand, conflicting value, mixed filing within an operand, unsupported fiscal period, or invalid denominator or capex sign produces an unavailable result. Reported zeros remain valid amounts outside rules that require a positive denominator.

## Reconciled examples

| Case | Result |
|---|---|
| ITW FY2026 Q2 | As of 6 August 2026, operating cash flow is **$723 million**, capex is **$92 million**, and free cash flow is **$631 million**. As of 5 August the quarter's flows are unavailable. Working capital is **$647 million** and reported net debt is **$8.855 billion**. |
| Dover FY2024 Q3 | Continuing-operations Q3 is unavailable at the 24 October 2024 cutoff in the reviewed filing set. The eligible comparative at the 24 July 2025 cutoff supports **$353.244 million** of Q3 operating cash flow and **$315.490 million** of free cash flow. Both source accessions are returned. |
| Rockwell FY2026 Q4 | Latest reported free cash flow is **$602 million**, and year-end borrowing debt excluding disclosed finance leases is **$3.276 billion**. The historical backfill verified annual acceptance at 11:35:11 Eastern on 12 November 2026. The reviewed value is eligible from that New York date in databases loaded with the backfill. The June balance has no verified finance lease adjustment in the sample. |

After [loading the pilot data](source_register.md#run-and-verify-the-import), apply the migrations and run the analytics checks:

```sh
docker compose --env-file .env -f infrastructure/docker/compose.yaml exec -T postgres \
  psql -X -U filing_to_funding -d filing_to_funding -f /workspace/database/migrate.sql
docker compose --env-file .env -f infrastructure/docker/compose.yaml exec -T postgres \
  psql -X -U filing_to_funding -d filing_to_funding -f /workspace/database/tests/pilot_analytics.sql
```

For example, use this SQL to reproduce Dover's result after the comparative became eligible:

```sql
SELECT *
FROM analytics.pilot_quarter_cash_flow(
    '0000029905', 2024, 3, DATE '2024-01-01',
    'continuing_operations', 'esg_excluded', DATE '2025-07-24'
);
```

The test covers the hand-checked values, provenance, separate reporting scopes, and the September fiscal year. It also rolls back synthetic cases for a filing accepted after midnight UTC but still on the same New York date, a conflicting disclosure, and a zero denominator.

The pilot covers only the reviewed periods and statement lines. Full historical series, trailing twelve-month calculations, and reconstruction of earlier platform snapshots require more coverage and separate verification.
