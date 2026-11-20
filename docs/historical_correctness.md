# Historical accounting qualification

The three-company review qualified **689 observations from 79 original EDGAR filings** for the reporting window through 19 November 2026. It covers the 66 base reports, 12 opening inputs, and one amendment. Each qualified observation retains the accession, exact interval or balance-sheet date, reported precision, source archive checksum, and inline XBRL fact ID. [Per-filing coverage and tags](sec_statement_coverage.csv)

| Issuer | Base reports with cash, current assets and current liabilities | Base reports with reported debt components | Base reports with cumulative operating cash flow and cash capex |
|---|---:|---:|---:|
| Illinois Tool Works | 23 of 23 | 23 of 23 | 23 of 23 |
| Dover | 23 of 23 | 20 of 23 | 23 of 23 |
| Rockwell Automation | 20 of 20 | 17 of 20 | 20 of 20 |
| **Total** | **66 of 66** | **60 of 66** | **66 of 66** |

At the 19 November 2026 cutoff, standalone cash flow was available for all 66 base periods. Trailing cash flow was available for 56 periods, with 20 results for ITW, 19 for Dover, and 17 for Rockwell. The other 10 periods lacked four compatible quarters on the selected reporting scope.

Reported debt is available when the balance sheet supplies non-overlapping current and noncurrent components. The qualifier leaves debt incomplete when it cannot substantiate one of those components. This includes Dover's first three FY2021 quarters and Rockwell's first three FY2022 quarters. The debt statuses in the CSV describe the inputs at the filing's own report date. Finance lease-adjusted borrowing debt is available for Rockwell FY2023–FY2026 annual reports, where the notes place both current and noncurrent finance leases within the debt lines. Earlier Rockwell notes place the current lease amount in other current liabilities, so deducting the total lease balance would overstate the adjustment. [Rockwell FY2022 annual filing](https://www.sec.gov/Archives/edgar/data/1024478/000102447822000093/rok-20220930.htm), [Rockwell FY2026 annual filing](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000048/rok-20260930.htm)

## Accounting cases

- **Dover cash and ESG disposal.** The September 2024 balance sheet reports **$386.766M** of cash and cash equivalents. The separate cash-flow total includes $10M held for sale. The cash ratio uses the balance-sheet row. Continuing-operations Q3 free cash flow was unavailable on 24 October 2024. It became **$315.490M** when the compatible H1 comparative was filed on 24 July 2025, with both source accessions returned. [Dover September 2024 report](https://www.sec.gov/Archives/edgar/data/29905/000002990524000045/dov-20240930.htm), [Dover June 2025 report](https://www.sec.gov/Archives/edgar/data/29905/000002990525000024/dov-20250630.htm)
- **ITW FIFO transition.** The opening FY2021 Q1 trailing result is **$2.558B** as of 6 May 2021. The post-change FY2024 Q1 trailing result is withheld because the window crosses the inventory-method change. Four compatible quarters support **$2.844B** for FY2024. The August 2024 test also confirms that the SEC filing date governs eligibility when acceptance occurred the prior evening. [ITW FY2024 annual report](https://www.sec.gov/Archives/edgar/data/49826/000004982625000007/itw-20241231.htm), [ITW August 2024 filing index](https://www.sec.gov/Archives/edgar/data/49826/000004982624000038/0000049826-24-000038-index.htm)
- **Rockwell capex and Sensia.** The FY2024 and FY2025 cash-flow statements label the productive-assets tag **Capital expenditures**. Retain $224.7M and $186M from their respective annual filings at the reported scale. The later $225M comparative for FY2024 reflects the presentation in the FY2025 filing. The FY2026 as-reported transition-year trailing free cash flow is **$1.701B** from the 12 November cutoff. The FY2026 Q3 trailing window lacks four compatible quarters in that reporting scope. The transition-year result carries its own scope for comparisons. [Rockwell FY2024 annual report](https://www.sec.gov/Archives/edgar/data/1024478/000102447824000107/rok-20240930.htm), [Rockwell FY2025 annual report](https://www.sec.gov/Archives/edgar/data/1024478/000102447825000116/rok-20250930.htm), [Rockwell FY2026 annual report](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000048/rok-20260930.htm)

## Qualified SQL results

Run `analytics.historical_quarter_cash_flow` and `analytics.historical_ttm_cash_flow` with an issuer CIK, fiscal year, quarter, and the basis and scope shown in the coverage CSV. Pass a date to reconstruct what was filed by New York end of day. Omit the date for the latest disclosure available to the local dataset. Both methods return status and source accessions.

Quarterly cash flow uses the exact fiscal start and subtraction of adjacent cumulative amounts. The operating cash flow and cash capex for each cumulative operand come from one filing and one reporting scope. A trailing result requires four contiguous available quarters on the selected scope. A conflict or missing compatible quarter withholds the trailing amount. The balance-sheet method accepts `historical_balance_sheet` as its scope and uses a single statement for each metric. The core database keeps the original backfill candidates and the mapped statement observations.

The qualification applies to reported balance-sheet liquidity, reported debt where supported, and operating cash flow, cash capex, and free cash flow. Revenue and net-income mappings, earnings-based ratios, peer rankings, the funding scenario, and dataset publication remain open parts of v1.2.

## Reproduce locally

The original packages and primary HTML are in the Git-ignored `.local/source-cache` directory. The local `.local/sec-statement-captures.jsonl` manifest records the fetch times and checksums. ITW FY2022 Q3 uses the archived primary HTML because the first ZIP request timed out. A resumed capture later retrieved the ZIP and produced the same normalized amounts, scopes, precision, and fact locators.

Apply the [local database migrations](data_dictionary.md#reproduce-the-database-with-docker-compose), load the [verified accession backfill](sec_backfill.md#reproduce-the-backfill), then run:

```sh
python3 -m pipelines.qualify_sec --coverage
python3 -m pipelines.qualify_sec --database filing_to_funding
```

To capture missing archives, set `SEC_CONTACT_EMAIL` to an authorized project contact and run `python3 -m pipelines.qualify_sec --download --coverage`. A new source capture can have different archive bytes. Keep the original manifest to reproduce the exact checksums in the coverage report.

A clean PostgreSQL 17.12 rebuild loaded 689 mapped observations. Replaying the same evidence added zero rows. All five database checks passed, including the after-hours cutoff, disposal comparative, opening trailing window, finance lease presentation, and a simulated conflicting observation that withheld the affected trailing result.
