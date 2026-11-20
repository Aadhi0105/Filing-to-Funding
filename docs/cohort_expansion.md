# Three additional issuers for the six-company cohort

**Module 3.1 decision, 20 November 2026.** Qualify **A. O. Smith (AOS), IDEX (IEX), and Lincoln Electric (LECO)** for the first-release cohort. All three use consolidated U.S. GAAP financial statements in USD and a December 31 fiscal year-end. Selection is based on their industrial operations, filing coverage, and the sample accounting checks below. The review uses the existing SEC cutoff of **19 November 2026**. [v1.2 release scope](filing-to-funding-audit-v1.2.md#5-product-scope-and-ux-acceptance)

## Verified filings and coverage

| Issuer | SEC CIK | Principal industrial products | Complete fiscal years | Later quarters | Opening input |
| --- | --- | --- | --- | --- | --- |
| A. O. Smith (AOS) | `0000091142` | Water heaters, boilers, and water treatment | FY2021–FY2025 | FY2026 Q1–Q3 | FY2020 Q1–Q3 and annual |
| IDEX (IEX) | `0000832101` | Pumps, fluidics, metering, and engineered components | FY2021–FY2025 | FY2026 Q1–Q3 | FY2020 Q1–Q3 and annual |
| Lincoln Electric (LECO) | `0000059527` | Welding, cutting, and automation equipment | FY2021–FY2025 | FY2026 Q1–Q3 | FY2020 Q1–Q3 and annual |

EDGAR verified **27 filings per issuer**, comprising 23 filings in the main window and four opening filings. All 81 accessions have acceptance timestamps. Each completed fiscal year has one annual report and three quarterly reports. Q4 is derived from the annual and nine-month statements where the inputs are compatible. The FY2020 opening filings supply the predecessor evidence needed for the first trailing periods. [Accession inventory](cohort_expansion_filing_inventory.csv) · [A. O. Smith FY2025 annual report](https://www.sec.gov/Archives/edgar/data/91142/000009114226000008/aos-20251231.htm) · [IDEX FY2025 annual report](https://www.sec.gov/Archives/edgar/data/832101/000083210126000003/iex-20251231.htm) · [Lincoln Electric FY2025 annual report](https://www.sec.gov/Archives/edgar/data/59527/000005952726000006/leco-20251231x10k.htm)

The Company Facts screen matched the original accession and the exact USD reporting interval. It checked balance-sheet cash, current assets and liabilities, debt tags, operating cash flow, cash capex, revenue, and net income. The SEC primary statements determine whether the values and reporting scopes qualify. [SEC XBRL API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces#xbrl-data-apis)

| Issuer | Cash, working capital inputs, cash flows, revenue and earnings | Current-debt candidate tags | Primary-statement follow-up |
| --- | --- | --- | --- |
| AOS | 26 of 27 filings | 26 of 27 | Company Facts lacked the checked inputs on the FY2024 accession. The original 10-K supplied those values, including $473.8M of FY2024 free cash flow. [FY2024 10-K](https://www.sec.gov/Archives/edgar/data/91142/000009114225000036/aos-20241231.htm) |
| IEX | 27 of 27 filings | 24 of 27 | Review FY2022 Q1–Q3 current borrowings in the statements and notes before mapping their debt totals. The reviewed FY2025 and FY2026 reports use the primary income statement's `Revenues` tag for net sales. [FY2025 10-K](https://www.sec.gov/Archives/edgar/data/832101/000083210126000003/iex-20251231.htm) |
| LECO | 27 of 27 filings | 11 of 27 | Review current borrowings in the source statements. For June 2026, the balance sheet displays a dash for short-term debt, with no qualifying inline fact in the reviewed sample. September 2026 supplies a tagged zero. Keep the June exception explicit and resolve other missing tags from filing evidence. [June 2026 10-Q](https://www.sec.gov/Archives/edgar/data/59527/000005952726000022/leco-20260630x10q.htm) · [September 2026 10-Q](https://www.sec.gov/Archives/edgar/data/59527/000005952726000027/leco-20260930x10q.htm) |

## Reconciled accounting samples

The review traced **89 values across 10 primary statements** to their SEC accessions, exact periods, original XBRL fact IDs, source hashes, and reported precision. Each FY2026 Q3 flow uses the September nine-month amount minus the June six-month amount from the same issuer and consolidated scope. Capex is the gross cash outflow with a positive presentation in the table. USD amounts are in millions. [Tagged statement evidence](../testdata/cohort_expansion/statement_samples.csv)

| Issuer | FY2025 free cash flow | FY2026 Q3 operating cash flow | FY2026 Q3 cash capex | FY2026 Q3 free cash flow | Working capital at 30 September 2026 | Reported carrying debt at 30 September 2026 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AOS | 546.0 | 175.6 | 12.7 | 162.9 | 549.0 | 673.1 |
| IEX | 616.8 | 239.5 | 25.2 | 214.3 | 1,130.6 | 1,751.5 |
| LECO | 534.199 | 215.757 | 41.219 | 174.538 | 870.474 | 1,149.969 |

PostgreSQL reproduced the annual and quarterly FCF, working capital, and the quarterly FCF margin and cash-conversion operands in a disposable copy of the local database. Each latest quarter was unavailable on the day before its SEC filing date. Replaying the 81 filing entries and the 89 reviewed statement values added zero rows. The debt sums were reconciled from disclosed carrying amounts. The three-company `v0003` snapshot remains active in the Explorer. [Local publication record](local_dataset_publication.md#verified-local-publication)

## Comparability and exclusions

- **A. O. Smith.** Flag the January 2026 Leonard Valve acquisition when explaining FY2026 changes. The September report includes the China business and discloses an expected fourth-quarter move to discontinued operations. When a later filing recasts prior periods, keep its continuing-operations figures on their own reporting scope and apply its filing date before making them eligible. [September 2026 10-Q](https://www.sec.gov/Archives/edgar/data/91142/000009114226000104/aos-20260930.htm)
- **IDEX.** Flag the September 2024 Mott acquisition in comparisons across the change. Use consolidated net income for the cash-conversion denominator. At 30 September 2026 the balance sheet reported $602.1M cash and cash equivalents. The cash-flow total of $607.1M included $5.0M of restricted cash. Use $602.1M for the cash ratio. Retain the September 2026 disclosure of revised customer-rebate estimates as context for reported earnings. [FY2025 10-K](https://www.sec.gov/Archives/edgar/data/832101/000083210126000003/iex-20251231.htm) · [September 2026 10-Q](https://www.sec.gov/Archives/edgar/data/832101/000083210126000029/iex-20260930.htm)
- **Lincoln Electric.** Flag acquisitions including RedViking, Vanair, and Inrotech in 2024 and Alloy Steel in 2025 when explaining changes. Use the total current-debt line when it already includes current maturities. Where the current-debt tag is missing, use reviewed filing evidence or withhold the debt measure. [FY2025 10-K](https://www.sec.gov/Archives/edgar/data/59527/000005952726000006/leco-20251231x10k.htm)
- **Peer eligibility.** Align actual dates, duration, and consolidation scope before comparing a metric. Use only periods with supported same-date lease treatment for borrowing-debt ratios. Keep issuer-specific exposures and cash availability outside the reported liquidity comparison. [Metric definitions](filing-to-funding-audit-v1.2.md#v12-metric-definitions)

The inventory and sample evidence are available for the six-company data build. Periods beyond the samples require the same statement-level mapping and validation before display. The official response and statement manifests are stored under `.local/cohort-qualification/2026-11-19/`. Original source bytes remain in `.local/source-cache/`.
