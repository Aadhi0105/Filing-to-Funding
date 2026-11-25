# Three-minute Filing-to-Funding demo

This walkthrough is for a recruiter or interviewer. Open the five linked views in advance for a live presentation, or follow them in order for a self-guided demo. [Portfolio case study](portfolio_case_study.md) · [Technical evidence](technical_evidence.md)

## 0:00–0:25 · Show the six-company overview

Open Overview on platform snapshot `v0004`. Point to the six company cards and the dataset version. [Open Overview](https://filing-to-funding.vercel.app/overview?mode=platform_snapshot&dataset_version=v0004)

> Filing-to-Funding brings liquidity and cash-flow analysis for six U.S. industrial companies into one dashboard. You can select a filing cutoff to see what had been disclosed by that date, or replay a published snapshot.

## 0:25–1:00 · Explain Dover’s scope change

Open Dover’s FY2024 Q2 in Company Explorer and scroll to **Filing revisions**. Point to the operating cash flow row and its two linked SEC accessions. The screen rounds the figures to **$370.26M** and **$295.64M**. [Open Dover’s Q2 filing revisions](https://filing-to-funding.vercel.app/?mode=platform_snapshot&dataset_version=v0004&company=0000029905&duration=quarter&period=2024-2)

> Dover’s original first-half figure included its Environmental Solutions Group. The later comparative covered continuing operations after the disposal classification. The app keeps both disclosures and labels the difference as a scope change.

## 1:00–1:40 · Trace a derived quarter to two filings

Open Illinois Tool Works’ FY2026 Q2 with **Filed by date** set to **6 August 2026**. Select the **Free cash flow $631M** tile. In **Filing evidence**, show the March and June 10-Q accessions. [Open the ITW cash-flow example](https://filing-to-funding.vercel.app/?mode=filed_by&filed_by=2026-08-06&company=0000049826&duration=quarter&period=2026-2)

> Illinois Tool Works reports cumulative cash flows. Subtracting the first quarter from the first half gives $723 million in standalone Q2 operating cash flow and $92 million in cash capital expenditure. The difference is $631 million in free cash flow. The two filings are visible behind the result.

## 1:40–2:15 · Model a funding shock

Open Funding Scenarios. Use **100000000** principal, **0.25** share repricing, a **100** basis-point shock, and a **1**-year horizon. Keep the optional spread blank. Select **Calculate scenario** and highlight **$250,000.00** under **Incremental interest**. [Open Funding Scenarios](https://filing-to-funding.vercel.app/funding?mode=platform_snapshot&dataset_version=v0004)

> In this example, a quarter of the $100 million balance reprices. A one percentage-point increase on that $25 million exposure adds $250,000 in interest over one year. The result depends on the assumptions entered here.

## 2:15–3:00 · Replay an archive and close

Open Overview on `v0003` and show its three companies. Use the **Published dataset** selector to return to `v0004` and its six companies. Close on Overview. [Open the archived v0003 Overview](https://filing-to-funding.vercel.app/overview?mode=platform_snapshot&dataset_version=v0003) · [Recovery rehearsal evidence](performance_and_release_readiness.md#hosted-sign-off)

> The older snapshot still reproduces the three-company release. In a separate recovery rehearsal, the serving API stayed on the last verified snapshot while the restored datasets and rollback were tested. The case study links to the filings, and the repository documents the setup and test results.
