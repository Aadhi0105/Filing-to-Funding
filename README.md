# Filing-to-Funding

**A corporate liquidity and financial resilience monitoring platform**

Filing-to-Funding uses regulatory filings to show how companies' cash, debt, working capital, and operating cash flow change over time. It is designed for analysts who need to compare companies, check how a metric was calculated, and reconstruct what had been disclosed by a specific date.

**Project status:** Local PostgreSQL holds 1,044 qualified statement observations from 79 SEC filings across Illinois Tool Works, Dover, and Rockwell Automation. The historical results include liquidity, quarterly and trailing cash flow, FCF margin, cash conversion, and borrowing-debt ratios where the lease basis is verified.

[v1.2 architecture and audit](docs/filing-to-funding-audit-v1.2.md) · [Pilot company coverage matrix](docs/coverage_matrix.md) · [Pilot filing reconciliation](docs/pilot_reconciliation.md) · [Pilot database model and setup](docs/data_dictionary.md) · [Source register and import](docs/source_register.md) · [Financial methodology and checks](docs/financial_methodology.md) · [Pilot readiness review](docs/pilot_readiness.md) · [Historical SEC backfill](docs/sec_backfill.md) · [Historical accounting qualification](docs/historical_correctness.md) · [Financial ratios](docs/financial_ratios.md) · [Treasury history](docs/treasury_history.md)

## What the application will do

| View | What an analyst can do |
|---|---|
| Overview | See recent filings, data freshness, and explainable changes in liquidity and cash flow. |
| Company explorer | Follow annual, quarterly, and trailing twelve-month trends. Inspect original filing lines, calculation inputs, and later revisions. |
| Peer comparison | Compare companies where reporting periods, consolidation scopes, and metric definitions are compatible. See why a value is excluded. |
| Funding scenarios | View 2-, 5-, and 10-year U.S. Treasury par yields and model the effect of a hypothetical rate change on a specified amount of debt. |
| Filing history and data quality | Review filing dates, conflicts, missing disclosures, and dataset publication status. |

The first release targets **six qualified U.S. industrial companies reporting under U.S. GAAP**, with five complete fiscal years and later published quarters where coverage supports them. Expansion to other regions would require local filing sources and mappings for accounting standards, currencies, and rate benchmarks.

## How historical views work

| Mode | Meaning |
|---|---|
| Latest reported | Use the latest eligible disclosure for each period and identify later revisions. |
| Filed by date | Use supported filings available by the selected date. Each input to a derived metric must satisfy the same cutoff. |
| Platform snapshot | Reproduce a dataset that Filing-to-Funding actually published. Coverage begins with the application's own snapshot archive. |

For example, suppose annual operating cash flow was first reported as $100 million in February and revised to $80 million in May. A March **Filed by date** view shows $100 million. **Latest reported** can show $80 million with the later filing attached. This reconstruction covers supported 10-Ks, 10-Qs, and amendments. Earlier earnings releases and intraday dissemination are outside the first release.

## Financial methodology

- **Liquidity and leverage.** Calculate working capital, cash and current ratios, and borrowing-based debt measures from compatible balance-sheet inputs. Count current debt maturities once. Identify restricted cash and bundled lease liabilities where the filing supports it.
- **Cash flow.** Derive standalone quarters from compatible year-to-date disclosures. For example, Q2 operating cash flow is first-half cash flow minus Q1 cash flow. Trailing twelve-month flows require four consecutive, comparable quarters. The application's free cash flow is operating cash flow minus qualifying cash purchases of property, plant, and equipment.
- **Data quality.** Distinguish reported zeros from missing, conflicting, stale, and non-comparable values. Carry the filing accession, observation period, units, calculation version, and source links with each published metric.
- **Funding.** A simple scenario multiplies principal by the share that reprices, the assumed rate change, and the number of years. For example, 25% of $2 billion repricing by 100 basis points for one year produces $5 million of illustrative incremental interest. Treasury yields are reference rates. The scenario depends on the analyst's inputs.

The first release measures reported balance-sheet liquidity and cash generation. Borrowing capacity, debt maturities, covenants, guarantees, and hedges require additional disclosures and are outside the first release's assessment.

## Architecture

The planned system takes SEC filing metadata and financial facts alongside Treasury yields. Python jobs preserve source evidence and validate incoming data. PostgreSQL normalizes and versions filing facts, then SQL selects the appropriate historical records and computes comparable metrics. FastAPI serves the results, and Next.js presents the dashboard.

| Layer | v1.2 design |
|---|---|
| Web | Next.js, React, TypeScript, Tailwind CSS, shadcn/ui, and Apache ECharts. |
| API | Python and FastAPI with a versioned REST interface and types generated from OpenAPI. |
| Data | PostgreSQL with `raw`, `core`, and `analytics` schemas. Stage and validate each refresh before publishing a new dataset version. |
| Local development | Docker and local PostgreSQL. |
| Planned hosting | Vercel for the web app, Google Cloud Run for the API and ingestion jobs, Cloud Scheduler for refreshes, private Cloud Storage for source payloads, and Supabase for managed PostgreSQL. |
| Delivery | GitHub Actions for automated checks and controlled releases. |

Primary sources are [SEC EDGAR](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) and the [U.S. Treasury daily interest-rate feed](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed). Company Facts supplies standard entity-wide XBRL facts. The source filing and notes provide evidence for custom tags, conflicting contexts, and disclosures that need review.

## Planned repository layout

```text
apps/
  web/                 Next.js dashboard and browser tests
  api/                 FastAPI routes, scenario calculator, and API tests
pipelines/             SEC and Treasury ingestion, validation, and refresh tests
database/              PostgreSQL migrations, normalized facts, analytics, and SQL tests
packages/
  shared-types/        Frontend types generated from the API contract
testdata/              Synthetic edge cases and small filing-backed fixtures
infrastructure/        Local Docker setup and planned cloud configuration
docs/                  Architecture, coverage, methodology, and operating notes
.github/workflows/     Automated checks and release workflows
```

The layout above includes planned components. Run and test the database with the [local setup instructions](docs/data_dictionary.md#run-locally).

## Pilot and release roadmap

1. **Select the pilot companies — complete.** The coverage matrix records the evidence and known comparison issues for Illinois Tool Works, Dover, and Rockwell Automation. The historical backfill verifies the filing and amendment inventory.
2. **Record expected values from the filings — complete.** The reconciliation records balance-sheet and cash-flow examples, including a later disclosure that changed the reporting scope.
3. **Set up the local PostgreSQL model — complete.** Store fiscal periods, filing metadata, versioned financial observations, Treasury rates, and source references.
4. **Load the pilot data — complete.** Import the reviewed SEC and Treasury extracts, preserve their source evidence, and verify that replay adds no duplicates.
5. **Verify calculations and historical cutoffs — complete.** Reconcile quarterly cash flow, working capital, and debt. Check that the chosen date excludes later or unverified disclosures.
6. **Review the pilot — complete.** The local pilot passed for its reviewed sample. The readiness review records the remaining requirements for expansion.
7. **Verify live sources and backfill — complete for the three-company filing window.** The original downloads, accession inventory, and repeatable import are documented.
8. **Qualify historical liquidity and cash flow — complete for the reviewed scope.** Filing-level evidence supports historical balances, standalone quarters, and compatible trailing results.
9. **Complete the financial ratios — complete for the reviewed scope.** Qualify revenue and net income, calculate FCF margin and cash conversion, and publish borrowing-debt ratios where the filing supports the basis.
10. **Backfill Treasury history — complete for the pilot window.** Archive the 2-, 5-, and 10-year par curves, and show the observation date, age, and vintage status.
11. **Close correctness for funding scenarios and dataset publication.** Verify those features against the v1.2 stage gates.
12. **Expand to six companies and build the web app.** Add the five views, consistent exports, source drilldowns, and accessible charts and tables.
13. **Prepare the public release.** Verify security, restore and replay, performance, and hosting costs before deployment. Any AI filing assistant is a later extension.

Financial verification will use independently checked SEC filing examples for real reporting cases and synthetic fixtures for edge cases. The test plan covers amendments, missing quarters, different fiscal calendars, incompatible reporting bases, and interrupted refreshes.
