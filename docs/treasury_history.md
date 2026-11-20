# U.S. Treasury par yield history

Task 5 loaded **5,166 Treasury yields across 1,722 observation dates**. The window runs from the start of the pilot's opening fiscal year, 1 January 2020, through the SEC backfill cutoff of 19 November 2026. The first available observation is 2 January 2020. The archive covers the 2-, 5-, and 10-year nominal par yields. [Treasury XML feed documentation](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)

| Year | First observation | Last observation | Dates |
|---|---|---|---:|
| 2020 | 2 January | 31 December | 251 |
| 2021 | 4 January | 31 December | 251 |
| 2022 | 3 January | 30 December | 249 |
| 2023 | 3 January | 29 December | 250 |
| 2024 | 2 January | 31 December | 250 |
| 2025 | 2 January | 31 December | 249 |
| 2026 | 2 January | 19 November | 222 |

The seven annual XML responses are archived by SHA-256 under the project's Git-ignored `.local/source-cache`. The capture manifest records the official URL, UTC retrieval time, file length, and checksum. All 15 values from the original five-day October 2024 sample matched the annual source. [Treasury October 2024 daily rates](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?field_tdr_date_value_month=202410&type=daily_treasury_yield_curve)

## Date selection and vintages

`analytics.treasury_curve` returns the latest observation dated on or before the requested cutoff, the age in calendar days, and the 10-year minus 2-year spread in basis points. The three rates are percentages from one source capture. On days with no observation, the result is marked `carried_forward` and retains the actual observation date. This applies to weekends, holidays, and gaps in the archive. Missing, incomplete, or conflicting curves withhold the yield values and spread.

| Requested cutoff | Observation used | Age | 2Y | 5Y | 10Y | 10Y–2Y |
|---|---|---:|---:|---:|---:|---:|
| 8 March 2023 | 8 March 2023 | 0 days | 5.05% | 4.34% | 3.98% | −107 bps |
| 24 October 2024 | 24 October 2024 | 0 days | 4.07% | 4.03% | 4.21% | +14 bps |
| 26 October 2024 | 25 October 2024 | 1 day | 4.11% | 4.07% | 4.25% | +14 bps |
| 11 November 2024 | 8 November 2024 | 3 days | 4.26% | 4.20% | 4.30% | +4 bps |

By default the lookup uses the most recent archived capture for the selected observation date. An optional retrieval cutoff selects the capture available in the local archive at that time. The original daily publication timestamp remains null for these annual XML responses. A feed update timestamp does not establish when a historical day's rate was originally published or revised. Historical lookups return `historical_vintage_unverified` for that reason. [Treasury interest-rate methodology and data](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics)

## Replay locally

Apply migration 006 with the [standard migration command](data_dictionary.md#reproduce-the-database-with-docker-compose). Then run:

```sh
python3 -m pipelines.treasury_history --coverage
python3 -m pipelines.treasury_history --database filing_to_funding
```

These commands use the frozen `.local/treasury-history-2026-11-19.json` capture. To check a fresh download, use a separate manifest so the original capture stays available for exact replay:

```sh
python3 -m pipelines.treasury_history --download \
  --manifest .local/treasury-history-new-capture.json --coverage
```

```sql
SELECT cutoff_date, observation_date, observation_age_days, status,
       two_year_percent, five_year_percent, ten_year_percent, ten_minus_two_bps,
       vintage_status, source_retrieved_at
FROM analytics.treasury_curve(DATE '2024-11-11');
```

A clean PostgreSQL rebuild passed all seven SQL checks and the original-source smoke test. Replaying the frozen capture added zero rows. Tests also checked weekend and holiday selection, inversion, the absence of evidence before the first capture, and selection of a later archived revision. A simulated stored-rate conflict rolled back without changing the database.
