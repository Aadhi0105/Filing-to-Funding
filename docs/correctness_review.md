# Three-company correctness review

**G2 decision, 20 November 2026. Passed for the reviewed three-company dataset.** The verified snapshot `v0003` is active locally. It uses the same SEC and Treasury captures as `v0002` and includes the validated methodology from Modules 1.1–1.4. The SEC filing cutoff remains 19 November 2026. The earlier snapshots remain available for replay. [Local publication record](local_dataset_publication.md#verified-local-publication) · [v1.2 stage gates](filing-to-funding-audit-v1.2.md#7-stage-gates-and-evidence-required)

## Module 1.5 final recheck

| Gate criterion | Verified evidence |
| --- | --- |
| Filing lineage and coverage | Verified the SHA-256 checksum and byte count for each of 94 archived payloads, all 79 acceptance timestamps, and all 1,044 qualified fact locators against their original filing documents. Company Facts remains a discovery source. |
| Historical cutoffs and conflict handling | `v0002` and `v0003` matched on the checked historical results. ITW FY2026 Q2 FCF stayed unavailable on 5 August and was $631M by 6 August. Dover's continuing-operations quarter stayed unavailable at its original cutoff and reached $315.490M after the later comparative. The conflict checks preserve a prior observation when a line is omitted and withhold the affected metric when newer evidence conflicts. |
| Revisions, calendars, and metrics | Verified ITW's unchanged certification amendment and Dover's separate reporting scopes. Rockwell FY2026 reconciled to $1.701B annual FCF and $3.276B of borrowing debt on the reviewed lease basis. ITW's comparable Q2 FCF change was $182M. Leap-day, 52/53-week, short-period, missing-input, and nonpositive growth-base cases passed. |
| Treasury and funding assumptions | The 24 October 2024 10-year yield verified at 4.21%, with the historical vintage qualification retained. The funding scenario produced $5M of incremental interest using the documented $2B principal, 25% repricing share, 100-basis-point shock, and one-year horizon. |
| Publication and recovery | A clean rebuild passed 10 PostgreSQL checks and 37 Python tests. Restoring the candidate and replaying all four loaders preserved every row and ID across eight tables. An invalid Treasury manifest and a competing refresh both left the last good version intact. The archive tested by restore is the one activated. Repeating publication returned `already_active`. |

The next stage is the local FastAPI and Company Explorer slice. Cohort expansion, peer eligibility, and user-facing freshness and quality labels belong to G3. The active snapshot provides the reviewed three-company evidence for that work.

## Task 8 baseline and remediation

**Initial Task 8 decision, 20 November 2026.** The local three-company dataset is reproducible for the reviewed methods, filing dates, and reporting scopes. **Hold the v1.2 G2 correctness gate.** The statement importer can drop a conflicting disclosure before the publication checks see it, and the calendar, revision, and comparison contracts still need evidence. The initial decision retained `v0002` as the local reference while the findings were addressed. [v1.2 stage gates](filing-to-funding-audit-v1.2.md#7-stage-gates-and-evidence-required)

**Module 1.1 update.** The importer and publisher now distinguish a newer conflict from an omitted line. Regression tests cover both outcomes. [Filing conflict handling](historical_correctness.md#filing-conflict-handling)

**Module 1.2 update.** Migration 007 links the original and later evidence. The checks cover the ITW certification amendment, Dover’s reporting-scope change, a controlled changed amount, and historical cutoffs. [Filing revisions and amendments](historical_correctness.md#filing-revisions-and-amendments)

**Module 1.3 update.** Migration 008 adds annual cash-flow metrics and comparable year-over-year changes. Tests cover the leap day, different weekly year lengths, a short fiscal year, incompatible reporting scopes, and nonpositive growth bases. [Annual results and year-over-year changes](financial_ratios.md#annual-results-and-year-over-year-changes)

**Module 1.4 update.** The SEC backfill reads overlapping history files, preserves filing provenance through deduplication, and shares a request budget with statement downloads. Live endpoint checks, offline source-failure tests, and a split-history snapshot replay passed. [Historical submissions and request handling](sec_backfill.md#historical-submissions-and-request-handling)

## Evidence from the original snapshots

Restored `v0001` and then-active `v0002` into separate PostgreSQL 17 databases. Both use the 19 November 2026 filing cutoff. Both passed all seven database suites and returned the same checked financial and Treasury values. Verified 94 archived source files against their stored SHA-256 digests and byte counts in each version. Replaying the pilot, SEC, statement, and Treasury loaders against restored `v0002` left every row and ID in the eight imported tables identical. The seven publication and twelve funding-calculator regression tests also passed.

| Issuer | Base filings in the review window | Opening-year filings | Amendments | Qualified statement observations |
| --- | ---: | ---: | ---: | ---: |
| Illinois Tool Works | 23 | 4 | 1 | 368 |
| Dover | 23 | 4 | 0 | 339 |
| Rockwell Automation | 20 | 4 | 0 | 337 |
| **Total** | **66** | **12** | **1** | **1,044** |

All 79 accessions had verified acceptance timestamps in the restored database. The 2,273 Company Facts observations remain discovery inputs. Qualified statements carry the accession, reported precision, source document locator, and original capture reference. The 5,166 Treasury observations cover three maturities across 1,722 dates. [Filing inventory](sec_filing_inventory.csv) · [SEC backfill evidence](sec_backfill.md) · [Local snapshot verification](local_dataset_publication.md)

| Check | Verified result |
| --- | --- |
| Filing cutoff and operating cash flow | ITW FY2026 Q2 free cash flow is **$631M** by 6 August. Using the compatible revenue inputs gives **14.6710%** FCF margin. Earlier cutoff checks withhold the quarter. |
| Later comparative and scope | Dover FY2024 Q3 continuing-operations FCF is unavailable at the 24 October 2024 cutoff. It becomes **$315.490M** at the 24 July 2025 cutoff, using the later compatible H1 comparative. The original H1 series remains available on its original scope. |
| Fiscal year and borrowing basis | Rockwell FY2026 Q4 FCF is unavailable on 11 November and **$602M** by 12 November. The annual lease note supports **$3.276B** of borrowing debt after deducting **$4M** in finance leases. Nine of the 66 in-window periods support the borrowing ratios. |
| Treasury and funding scenario | Both snapshots returned **4.21%** for the 10-year Treasury yield on 24 October 2024, with different capture timestamps. Weekend, holiday, and synthetic rate-revision checks passed. The documented calculator example yields **$5M** of incremental interest for the stated scenario. |

The figures above use reported balance-sheet liquidity indicators and compatible filing periods. Separately, a filing recheck found 20 Dover balance-sheet cash rows with a broader XBRL cash tag. All 20 were labelled cash and cash equivalents on the primary balance sheet. The September 2024 fixture independently confirms that the **$386.766M** selected line excludes the **$10M** held for sale. Preserve that issuer-specific evidence in the mapping and keep cash accessibility outside the metric claim. [Filing reconciliation](pilot_reconciliation.md) · [Financial ratios](financial_ratios.md) · [Treasury history](treasury_history.md) · [Funding scenario](funding_scenario.md)

## Original Task 8 findings and required remedies

| Priority | Finding | Evidence required to close |
| --- | --- | --- |
| P0 · R03, R07, R12 | **The qualifier can hide ambiguity before validation.** The frozen archive showed no conflicting amounts in the mapped row groups checked. In a synthetic newer ITW disclosure, two conflicting cash values produced the same empty result as an omitted cash line. With the ambiguous candidates absent from storage, the selector still returned the older **$839M** as `available`. Passing both candidates to storage produced `conflicting_observations` and withheld the value. [Qualification](../pipelines/qualify_sec.py#L174) · [Historical selection](../database/analytics/historical/pilot_facts.sql#L19) | Carry ambiguous evidence and its filing/period through ingestion as a conflict. Test that a genuine omission preserves the prior fact, a newer conflict withholds the affected result, and a refresh cannot publish that result as verified. Preserve the last good snapshot when the quality gate rejects a candidate. |
| P0 · R03 | **Historical selection works, but revision relationships are implicit.** The real ITW amendment changed a certification rather than the financial values. A synthetic same-scope change returned **$839M** before the new filing and **$1.4B** after it. The selector returns the chosen accession. The database lacks a record connecting original and superseding evidence and distinguishing a same-value amendment, a changed comparable fact, and a change of reporting scope. | Return both accessions and a reviewed reason for the change. Verify the real certification amendment, the Dover scope change, and a controlled changed-value case. Reserve formal restatement labels for explicit filing evidence. |
| P0 · R04 | **Calendar evidence is limited to the three month-end issuers.** Exact interval checks, the September year-end, contiguous quarters, and the reviewed accounting-scope transitions passed. The importer derives calendars from month ends. The required leap-day and 53-week/short-transition fiscal-period cases have no dedicated tests. [Calendar generation](../pipelines/backfill_sec.py#L66) | Add explicit boundary fixtures and record the exact fiscal boundaries and eligibility of irregular periods. Verify that unsupported periods and incomplete trailing windows stay unavailable. |
| v1.2 formulas · R04, R07 | **Annual and change results need a shared calculation contract.** A fiscal-year ratio request returned `unsupported_fiscal_period` for both ratios. The ratio function supports quarter and trailing durations. Comparable absolute changes and percentage growth with a positive base have no implementation in the shared analytics layer. [Ratio duration filter](../database/analytics/metrics/historical_cash_flow_ratios.sql#L19) · [v1.2 metric definitions](filing-to-funding-audit-v1.2.md#v12-metric-definitions) | Verify annual and change calculations using the actual fiscal dates, the selected historical cutoff, and compatible reporting scopes. Cover zero/negative prior values and accounting breaks before exposing growth or peer comparisons. |
| P1 · R11 | **The frozen backfill has complete filing evidence for this window.** The SEC loader rejects an overlapping historical submissions shard. It uses delay and retry limits per run, and has no shared request budget across the capture commands. [SEC backfill and request handling](sec_backfill.md#historical-submissions-and-request-handling) | Traverse overlapping shards and test duplicate accessions, source faults, and recovery. Verify one shared request budget before recurring refresh or qualifying a larger filing universe. |

R01, R02, R05, and R06 have passing local evidence for the frozen scope. R10 passes for archived Treasury retrieval history and carries `historical_vintage_unverified` for earlier public availability. R12 and R18 have passing local replay and fixture evidence. Their hosted recovery, monitoring, and UI/API checks belong to the later gates. User-facing status labels, peer exclusions, and coverage tests for three additional issuers belong to G3.
