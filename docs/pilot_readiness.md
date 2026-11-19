# Three-company pilot readiness review

**Decision, 19 November 2026:** The local pilot passes for its reviewed sample. Continue the v1.2 correctness work with Illinois Tool Works, Dover, and Rockwell Automation. The evidence supports using the prototype and its fixtures for further development. Expanding to six qualified issuers depends on a repeatable backfill, verified filing metadata, and documented per-issuer comparability.

This review covers repository commit `292c81c`, the three-company [coverage matrix](coverage_matrix.md), and the [v1.2 stage gates](filing-to-funding-audit-v1.2.md#7-stage-gates-and-evidence-required).

## What passed

| Check | Evidence from the clean rebuild |
|---|---|
| Reproducibility | Applied migrations 001–003 to an empty database in the existing Docker PostgreSQL 17.12 container. Loaded 3 issuers, 7 SEC filings, 51 financial facts, and 15 Treasury yields across 5 observation dates. |
| Replay | A second load inserted zero rows. All row contents and IDs matched across the eight imported tables. |
| Failed import | Injected an invalid Treasury maturity into the test import. PostgreSQL rejected it and rolled back the entire database transaction, including the preceding SEC inserts. The valid batch then loaded successfully. |
| Verification | Storage, ingestion, and analytics checks passed. The checks that insert synthetic rows rolled them back. The temporary review database was removed, and the working pilot still contained 51 financial facts. |

| Calculation or behavior | Verified result | Boundary |
|---|---|---|
| Quarterly cash flow | ITW FY2026 Q2 moved from unavailable on 5 August to **$723M operating cash flow** and **$631M free cash flow** by 6 August, New York dates. | The sample covers the reviewed first-half filings. |
| Recast and historical scope | Dover FY2024 Q3 continuing-operations cash flow was unavailable on 24 October 2024 in the reviewed set. With the 24 July 2025 comparative, operating cash flow was **$353.244M** and free cash flow **$315.490M**. Both input filings are identified. | The full filing inventory could contain an earlier compatible comparative. The original first-half figure remains available on its original scope. |
| Liquidity metrics | ITW Q2 working capital was **$647M** and the current ratio was **1.108685×**. Dover Q3 working capital was **$1.358698B** and the cash ratio was **0.162016×**, using the balance-sheet cash line. | Ratios use a positive denominator. Cash held for sale remains separate. |
| Borrowing debt and fiscal calendar | Rockwell's September year-end produced **$602M** of latest-reported fiscal Q4 free cash flow and **$3.276B** of borrowing debt after excluding **$4M** of disclosed finance leases. | Its annual report is excluded from strict historical results because its acceptance time remains unverified. Its June debt remains on its reported basis. |
| Cases to withhold | Tests rejected conflicting observations, balance-sheet operands from mixed filings, a zero denominator, and an incorrect fiscal-year start. A synthetic late filing verified the New York end-of-day boundary across midnight UTC. | These tests demonstrate the specified cases in the reviewed dataset. |

Sources and expected values are in the [filing reconciliation](pilot_reconciliation.md) and [financial methodology](financial_methodology.md). The three test scripts are under [database/tests](../database/tests/).

## What still limits expansion

| Priority | Gap | Evidence needed to close it |
|---|---|---|
| 1 | **Live source retrieval and provenance.** The pilot's direct SEC download returned HTTP 403 and the Treasury requests timed out. It loads reviewed extracts and records their checksums. | Establish an approved SEC and Treasury retrieval path. Fetch and preserve original bytes, source URL, retrieval time, and checksum. Demonstrate a fresh load, an unchanged replay, and recovery after a temporary source failure. See the [source register](source_register.md). |
| 2 | **Filing history and acceptance.** The seven loaded reports are a sample against an expected inventory of 66 base reports across the current pilot companies for five complete fiscal years plus available subsequent quarters. Amendments and opening-quarter inputs are additional. | Build an accession-level inventory for the three companies. Confirm actual available forms and dates against EDGAR, preserve amendments, and verify timestamps used for historical selection. Resolve Rockwell's missing annual timestamp or retain its explicit exclusion. |
| 3 | **Mappings and comparability.** The reviewed statement lines and the three-company debt rules are applied explicitly. XBRL tags, dimensions, lease treatment, and reporting changes are unverified across the intended history. | Version the issuer and concept mappings. Reconcile source-backed examples for changes in accounting scope and disclosures. Add coverage for real amendments, missing quarters, trailing twelve-month inputs, and nonstandard fiscal calendars before offering those results. |
| 4 | **Dataset publication and market context.** The local import is atomic. The sample contains five market days and has no verified historical Treasury vintage. Published dataset versions, scheduling, and last-good refresh behavior are outside this proof. | Implement validated dataset publication and archived snapshots, test interrupted and overlapping refreshes, and label vintage limitations. Verify the scenario calculator against the documented assumptions. |

## Readiness decision by v1.2 stage

- **G1, local feasibility:** Demonstrated on the bounded three-company sample. The architecture, coverage matrix, source register, and reconciled cases support continuing the work.
- **G2, correctness:** Partially demonstrated. Close the source, coverage, and mapping gaps on the three existing issuers before expanding validated coverage. Add test evidence for applicable v1.2 requirements, including the scenario engine and versioned dataset publication.
- **G3, usable full stack:** Pending. A six-company release requires three additional issuers that pass the same coverage and reconciliation checks. The API and dashboard will also need to surface source links, filing cutoffs, and unavailable results.
- **G4 and G5, operational and release readiness:** Pending. Cloud costs, access controls, recovery drills, performance, and release verification remain covered by the v1.2 plan.

The next milestone is a reproducible backfill for the current three companies with an explicit record of accepted, missing, and incompatible periods. Use that evidence to qualify the next three companies and decide which measures the first dashboard can support.
