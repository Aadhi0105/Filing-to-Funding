# Three-company SEC historical backfill

**Reporting cutoff: 19 November 2026.** The frozen EDGAR capture contains all 66 expected base reports, one amendment, and 12 earlier filings that supply the opening quarters. The accession inventory includes the SEC filing date, acceptance time in UTC, report date, and primary document link for each filing. All 79 accessions have an acceptance time. [Accession inventory](sec_filing_inventory.csv)

| Issuer | Main coverage | Base reports | Opening inputs | Amendments | USD observations |
|---|---|---:|---:|---:|---:|
| Illinois Tool Works | FY2021–FY2025 and FY2026 Q1–Q3 | 23 | 4 from FY2020 | 1 | 757 |
| Dover | FY2021–FY2025 and FY2026 Q1–Q3 | 23 | 4 from FY2020 | 0 | 801 |
| Rockwell Automation | FY2022–FY2026 | 20 | 4 from FY2021 | 0 | 715 |
| **Total** | | **66** | **12** | **1** | **2,273** |

The opening year includes Q1 so the first eligible Q2 can be derived from Q2 and Q1 year-to-date flows. The opening Q4 requires the annual report and the preceding Q3. Rockwell's December quarter belongs to the following fiscal year. The accession inventory includes these inputs for future trailing calculations. [Cohort and fiscal calendars](coverage_matrix.md)

## Filing history and evidence

- **ITW FY2021 Q2 amendment.** EDGAR lists the 5 August original and the 6 August amendment as separate accessions for the same fiscal period. The filing's explanatory note identifies the amendment as an exhibit certification signature correction, with the financial disclosures unchanged. The database retains the original and amended observations. [Original 10-Q](https://www.sec.gov/Archives/edgar/data/49826/000004982621000059/itw-20210630.htm), [10-Q/A](https://www.sec.gov/Archives/edgar/data/49826/000004982621000064/itw-20210630.htm)
- **Rockwell FY2026 10-K.** The Submissions API supplies acceptance at **16:35:11 UTC on 12 November 2026**, corroborated by **11:35:11 Eastern** on the filing index. The existing reviewed fiscal Q4 free cash flow is now available at the 12 November New York cutoff. It remains unavailable at the 11 November cutoff. [SEC filing index](https://www.sec.gov/Archives/edgar/data/1024478/000102447826000048/0001024478-26-000048-index.htm)
- **ITW FY2024 Q2 after-hours filing.** SEC accepted the report at 18:26:02 Eastern on 1 August and lists 2 August as the filing date. The historical rule requires the SEC filing date in addition to the acceptance instant. [SEC filing index](https://www.sec.gov/Archives/edgar/data/49826/000004982624000038/0000049826-24-000038-index.htm)
- **Dover reporting scope.** The 2025 half-year report contains a 2024 comparative on continuing operations. The backfill keeps the comparative interval and 2025 filing accession, separate from the original 2024 disclosure. [Original 2024 10-Q](https://www.sec.gov/Archives/edgar/data/29905/000002990524000035/dov-20240630.htm), [2025 comparative](https://www.sec.gov/Archives/edgar/data/29905/000002990525000024/dov-20250630.htm)

## Accounting coverage

The loader retains USD observations for selected standard taxonomy tags, including prior-period observations re-reported on in-window accessions. The source locator is a JSON pointer into the original Company Facts file. The API provides the numeric value and date interval. Filing-level presentation, context IDs, and reported decimals require original filing evidence. The stored observations carry an unclassified reporting basis and are excluded from the reviewed pilot calculations. [SEC API coverage](https://www.sec.gov/search-filings/edgar-application-programming-interfaces#xbrl-data-apis)

| Review priority | Finding |
|---|---|
| Dover balance-sheet cash | The standard cash carrying-value tag appears at the report date in 3 of 23 base reports. The combined cash and restricted cash tag appears in the other 20. Verify the balance-sheet line and disclosures before using this combined tag for a cash ratio or net debt. |
| Dover cash-flow comparability | The cohort includes reported and continuing-operations cash flows. Reconcile capex scope and distinguish the original and later comparative before deriving standalone quarters across the ESG disposition. |
| Rockwell capex | The PP&E payment tag appears in 18 of 20 reports. The FY2024 and FY2025 annual reports use a broader productive-assets payment tag. Check that tag against the reported cash capex line for both years. |
| Debt and finance leases | Reconcile current and long-term tags to the statement and note on each relevant date. Rockwell's Company Facts has no separate current or noncurrent finance lease liability tags at the base report dates in this capture. The reviewed FY2026 lease adjustment comes from the annual filing note. |
| ITW accounting change and cross-issuer measures | The candidate tags cover all eight input groups in every ITW base report. Carry forward the FY2024 LIFO-to-FIFO comparability flag and qualify the revenue and income tags before publishing earnings-based measures. |

## Reproduce the backfill

Run from the project folder with the [local Docker PostgreSQL database set up](data_dictionary.md#reproduce-the-database-with-docker-compose). The six original SEC JSON responses are stored by SHA-256 under `.local/source-cache`. The Git-ignored manifest `.local/sec-history-2026-11-19.json` records their URLs, retrieval times, file sizes, and checksums. The CSV is a derived record of the frozen capture.

```sh
python3 -m pipelines.backfill_sec --inventory
python3 -m pipelines.backfill_sec --database filing_to_funding
```

To repeat the official download, set `SEC_CONTACT_EMAIL` in your shell to an authorized project contact, then run:

```sh
python3 -m pipelines.backfill_sec --download \
  --manifest .local/sec-history-new-capture.json --inventory
```

The downloader sends the contact only to the SEC in the request header. It records the retrieval timestamp after each successful response. A fresh download can include later source corrections, so keep the original manifest to reproduce this run. The fixed cutoff applies to the SEC filing date. Retrieval dates represent when the application obtained the snapshot. [SEC fair-access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)

## Historical submissions and request handling

The recent Submissions response lists older files and their filing-date ranges. The capture follows the files that overlap the review window, including its opening inputs. It archives each response with its own URL, retrieval timestamp, and SHA-256 checksum. Replay checks that every required file is present and that overlapping rows agree before loading PostgreSQL. An exact duplicate keeps the recent source when both sources supply identical evidence. A history file can supply a missing acceptance timestamp, and each stored accession retains the source used for its metadata. [SEC EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

The submissions and statement capture commands share a limit of two requests per second within this local checkout. Each request and retry uses the same budget. A transient server or network failure gets one retry, with a delay that honors `Retry-After`. A longer server-directed delay pauses both commands until the recorded time. An SEC access denial or rate limit stops the run and pauses both commands for at least ten minutes. The request header uses the declared project contact. [SEC fair-access guidance](https://www.sec.gov/about/developer-resources)

A failed backfill preserves the prior manifest and published snapshot. Resume by running the capture after the SEC pause expires, or replay the existing archived manifest. The statement capture command also keeps completed filing captures so it can resume from the remaining accessions. The local request budget coordinates processes in this checkout. Deployments that run on several machines need a shared deployment-wide limit.

## Verification

An independent download reproduced the 79-row inventory. Loading the frozen archive in a disposable PostgreSQL 17.12 database produced 79 filings and 2,273 candidate observations. A second import inserted zero rows and preserved the contents and IDs of the loaded tables. The reviewed pilot also replayed successfully after the backfill. An intentionally conflicting acceptance time caused the transaction to roll back. The original pilot checks and the historical import tests passed.

The [historical accounting qualification](historical_correctness.md) verifies the selected tags against the original statements and records when standalone quarters and trailing results are available.

Module 1.4 verified live responses from the recent and historical SEC endpoints. An isolated rebuild with a filing moved to an older file reproduced all 79 accessions and preserved the source of each. An identical replay kept the same rows and IDs. Conflicting metadata rejected the candidate and preserved the last good version. Offline tests covered transient failures, shared cooldowns, missing files, and duplicate accessions.
