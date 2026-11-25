# Filing-to-Funding portfolio case study

Filing-to-Funding is a public financial research app for six U.S. industrial companies. It answers two questions an analyst can ask about any supported metric. What had the company disclosed by a given date? Which filing lines support the displayed result? The examples below use the published snapshot `v0004`, with SEC filings and Treasury yield coverage through 19 November 2026. The public release went live on 24 November 2026. [Live dashboard](https://filing-to-funding.vercel.app/overview) · [Production release evidence](performance_and_release_readiness.md#phase-51-production-release)

The app has two ways to revisit history. **Filed by date** applies a filing-date cutoff at the end of the selected day in New York. **Platform snapshot** replays the data and methodology the project published under a specific version. The API examples below pin `v0004` so a later publication cannot silently change the results. [Historical accounting methodology](historical_correctness.md)

## 1. Dover's first-half 2024 cash flow changed reporting scope

Dover originally reported **$370.255 million** of operating cash flow for January through June 2024, including its Environmental Solutions Group (ESG). The September 2024 filing classified ESG as discontinued operations. In July 2025, Dover reported a first-half 2024 comparative of **$295.637 million** for continuing operations. Filing-to-Funding preserves both observations and labels their relationship **scope change**. The later figure is a recast following the disposal classification. [Original June 2024 10-Q](https://www.sec.gov/Archives/edgar/data/29905/000002990524000035/dov-20240630.htm) · [September 2024 10-Q](https://www.sec.gov/Archives/edgar/data/29905/000002990524000045/dov-20240930.htm) · [June 2025 10-Q with the 2024 comparative](https://www.sec.gov/Archives/edgar/data/29905/000002990525000024/dov-20250630.htm)

| H1 2024 observation | SEC filing date | Reporting scope | Operating cash flow |
| --- | --- | --- | ---: |
| Original | 25 July 2024 | Consolidated, including ESG | $370.255M |
| Later comparative | 24 July 2025 | Continuing operations | $295.637M |

The distinction affects Q3. On 24 October 2024, the nine-month continuing-operations figure was available, but the published dataset had no compatible first-half figure at that cutoff. The app left standalone Q3 cash flow unavailable. Using the original first-half figure would mix reporting scopes. By 24 July 2025, both inputs were eligible, and the app derived **$353.244 million** of Q3 operating cash flow ($648.881M − $295.637M) and **$315.490 million** of free cash flow after $37.754 million of cash capex. [Dover filing revisions in the live app](https://filing-to-funding.vercel.app/?mode=platform_snapshot&dataset_version=v0004&company=0000029905&duration=quarter&period=2024-2) · [Q3 API before the comparable figure](https://filing-to-funding.vercel.app/api/v1/companies/0000029905/analysis?fiscal_year=2024&quarter=3&duration=quarter&expected_dataset_version=v0004&mode=filed_by&filed_by=2024-10-24) · [Q3 API with both inputs](https://filing-to-funding.vercel.app/api/v1/companies/0000029905/analysis?fiscal_year=2024&quarter=3&duration=quarter&expected_dataset_version=v0004&mode=filed_by&filed_by=2025-07-24)

## 2. Illinois Tool Works' Q2 2026 free cash flow reconciles to $631 million

Illinois Tool Works' June 10-Q reports cash flows for the first six months. To isolate April through June, the app subtracts the matched January–March figures from the January–June figures. The two filings cover the same issuer, fiscal year, currency, and consolidated reporting scope. The table uses USD millions and shows cash capex as a positive amount spent. [March 2026 10-Q](https://www.sec.gov/Archives/edgar/data/49826/000004982626000028/itw-20260331.htm) · [June 2026 10-Q](https://www.sec.gov/Archives/edgar/data/49826/000004982626000049/itw-20260630.htm)

| Cash-flow measure | January–March | January–June | Standalone April–June |
| --- | ---: | ---: | ---: |
| Operating cash flow | $623M | $1,346M | $1,346M − $623M = **$723M** |
| Cash capital expenditure | $95M | $187M | $187M − $95M = **$92M** |
| Free cash flow | | | $723M − $92M = **$631M** |

The June report's management discussion gives the same three-month amounts. The historical view keeps the Q2 result unavailable on **5 August 2026** and displays it on **6 August 2026**, when the June 10-Q entered the filing record. The API returns both source accessions with the calculated metrics. [ITW Q2 in the live app](https://filing-to-funding.vercel.app/?mode=filed_by&filed_by=2026-08-06&company=0000049826&duration=quarter&period=2026-2) · [API on 5 August](https://filing-to-funding.vercel.app/api/v1/companies/0000049826/analysis?fiscal_year=2026&quarter=2&duration=quarter&expected_dataset_version=v0004&mode=filed_by&filed_by=2026-08-05) · [API on 6 August](https://filing-to-funding.vercel.app/api/v1/companies/0000049826/analysis?fiscal_year=2026&quarter=2&duration=quarter&expected_dataset_version=v0004&mode=filed_by&filed_by=2026-08-06)

## 3. A failed source check left the verified release available

During the 24 November 2026 hosted rehearsal, a controlled source-check failure preserved the last successful refresh timestamp and delivered an alert to the project's internal notification channel. The serving API continued to return all six companies on `v0004`. An isolated watchdog test independently delivered the missed-refresh alert when its simulated last-success timestamp was **36 hours and 1 second** old. [Refresh and recovery runbook](refresh_and_recovery.md#hosted-schedule-and-acceptance)

In a separate rehearsal, downloading and verifying the archived backup and restoring `v0003` and `v0004` into scratch PostgreSQL took **5.83 seconds** in total. Both restored versions matched their archived row counts and passed historical finance and Treasury checks. A private rollback drill switched the test API from six companies on `v0004` to three on `v0003` and back to six on `v0004`. A request pinned to the wrong version returned HTTP 409. The live catalog served `v0004` throughout. [Replay v0003 in the public app](https://filing-to-funding.vercel.app/overview?mode=platform_snapshot&dataset_version=v0003) · [Hosted rehearsal evidence](performance_and_release_readiness.md#hosted-sign-off)

## What the release covers

The published release covers six qualified U.S. industrial companies, supported SEC periodic filings, and U.S. Treasury reference yields. Company Explorer exposes calculation inputs and filing links, and exports retain the dataset version. Across six measured public API endpoints, the release returned zero errors in **120 warm benchmark requests** at up to two requests per second. The slowest warm p95 was **0.85 seconds** in that run. [Financial methodology](financial_methodology.md) · [Benchmark conditions and results](performance_and_release_readiness.md#phase-51-production-release)
