# Module 3.3 local release validation

**Decision.** G3 passed on 21 November 2026 for the reviewed local release. The release candidate uses local dataset **v0004** and an SEC filing cutoff of **19 November 2026**. Its 160 filing records cover AOS, DOV, IEX, ITW, LECO, and ROK. It contains 1,133 qualified statement observations and 5,166 Treasury yields across 1,722 observation dates. AOS, IEX, and LECO each have 27 verified filing records and rely on 89 reviewed statement observations across 10 original filings. The application shows missing inputs for periods and metrics outside that sample. [Cohort evidence](cohort_expansion.md) · [Local run instructions](company_explorer.md)

## Findings addressed

- Annual peer comparison now defaults to the most common period end among the issuers’ latest eligible reports. In v0004 it opens on 31 December 2025 with four comparable FCF values. An excluded row retains its reporting basis and calculation window when those are available. The screen and CSV report the exclusion without a numeric comparison value.
- Funding exports include the repricing principal, Treasury maturity, reference rate, spread, curve dates, and the baseline and shocked coupon and interest for the entered shock. The scenario validates an explicitly entered curve date even when the spread field is blank.
- Wide peer, filing history, and sensitivity tables are keyboard-focusable. Mobile checks include scrolling tables within their panels.

## Verification results

| Check | Result |
| --- | --- |
| Build and API contract | Next.js production build and TypeScript checks passed. Regenerating frontend types from the live OpenAPI schema reproduced the frontend type file exactly. |
| Pipeline and financial tests | 25 pipeline tests and 24 API and calculator tests passed. The API suite traced the overview metrics for all six issuers to their qualified filing facts. |
| Browser tests | All 10 Chrome tests passed across the five views. Checks covered shared cutoffs, archived membership, matching CSV contents, unavailable-data recovery, and keyboard access at phone widths. |
| Local data access | Confirmed the reader role can read qualified facts and lacks database-create and issuer-update privileges. Requests with invalid input, mismatched snapshots, or paths outside the API returned expected errors. |

## Filing evidence and restore

The 24 July 2025 Dover filing introduces a continuing-operations presentation of the six months ended 30 June 2024. Operating cash flow is $295.637M on that basis. The original consolidated filing reported $370.255M. The 23 July 2025 cutoff excludes the later presentation. The later cutoff shows both accessions and classifies the pair as a scope change. [Revision SQL checks](../database/tests/filing_revisions.sql)

The AOS standalone quarter ended 30 September 2026 uses $162.9M of free cash flow. Its comparable half-year and nine-month operating cash flow and capex inputs support the subtraction. The 28 October cutoff withholds the value, and the 29 October cutoff makes it eligible. The same boundary check passed for IEX and LECO on their filing dates. [Cohort calculation checks](../database/tests/cohort_expansion.sql)

A checksum-verified restore of v0004 into a fresh local database matched every published row count. The restored database passed five SQL suites covering the expanded cohort, conflicting facts, Treasury history, filing revisions, and fiscal-period metrics. The temporary database was used for the drill. [Snapshot publication and restore](local_dataset_publication.md)

## Warm local responses

Responses used prepared v0004 databases and a single sequential loopback client. Each endpoint had three warm-up requests and 30 measured requests. The reported measure is HTTP round-trip latency in milliseconds on the review Mac.

| Endpoint | Median | p95 |
| --- | ---: | ---: |
| Overview | 111.1 | 132.3 |
| Company Explorer | 55.9 | 99.8 |
| Peer Comparison | 74.0 | 171.5 |
| Treasury curve | 19.8 | 33.1 |
| Filing History | 17.9 | 23.7 |

Cloud latency, cold starts, concurrency, monitoring, rollback, spending, and public release approval remain part of G4. [v1.2 release gates](filing-to-funding-audit-v1.2.md#7-stage-gates-and-evidence-required)
