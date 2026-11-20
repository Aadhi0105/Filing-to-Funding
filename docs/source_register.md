# Pilot source register

The local pilot imports a bounded sample of public filing and Treasury data. The reviewed extracts are kept in Git so the same input can be replayed offline. PostgreSQL stores the source URL, a checksum of the archived extract, and the database insertion time. A reviewed extract has a null HTTP retrieval timestamp. Its checksum identifies the extract file.

| Source | Pilot input | Coverage | Evidence limitations |
|---|---|---|---|
| SEC EDGAR | [Reviewed financial statement and note extracts](../testdata/reconciled/sec_pilot.json) and the [reconciliation](pilot_reconciliation.md) | 51 observations from seven 10-K and 10-Q accessions across Illinois Tool Works, Dover, and Rockwell Automation. | Direct EDGAR archive requests returned HTTP 403 from this environment. Accession and filing URLs identify the official filings. The extract references the filing lines and displayed precision. The Rockwell FY2026 acceptance time remains unverified and null. |
| U.S. Treasury | [Reviewed daily par yield extract](../testdata/reconciled/treasury_pilot.json) | 15 observations across 21–25 October 2024, at the 2-, 5-, and 10-year maturities. This window includes Dover's 24 October filing date. | Direct downloads of the XML feed and table timed out. Values were checked against Treasury's published table. Publication times and historical vintages are unverified. |

[SEC EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [SEC developer and fair-access guidance](https://www.sec.gov/about/developer-resources) · [Treasury October 2024 table](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?field_tdr_date_value_month=202410&type=daily_treasury_yield_curve) · [Treasury XML feed documentation](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)

## Run and verify the import

Start the [Docker database and apply the migrations](data_dictionary.md#reproduce-the-database-with-docker-compose). From the repository root, run:

```sh
python3 -m pipelines.load_pilot
python3 -m pipelines.load_pilot
docker compose --env-file .env -f infrastructure/docker/compose.yaml exec -T postgres \
  psql -X -U filing_to_funding -d filing_to_funding -f /workspace/database/tests/pilot_ingestion.sql
```

Python 3.11 and the existing PostgreSQL client are sufficient. The loader uses Docker Compose by default. To use an already-migrated native PostgreSQL database, provide the client command and connection options after `--`.

The loader archives the input files under Git-ignored `.local/source-cache`, then inserts both sources in one database transaction. Existing accession metadata and issuer fiscal dates are checked before any conflicting input can commit. Replaying identical extracts preserves the existing IDs and insertion timestamps and adds no rows.

The curated filing observations use the `filing-line` namespace. Their locators are JSON pointers to the exact displayed line in the archived extract. Store dollar amounts at their original displayed precision and retain the statement's sign for capex. The [pilot calculations](financial_methodology.md) normalize capex and apply reporting-scope and historical-eligibility rules. The [original-source verification](#original-source-verification) extends this reviewed pilot with official source payloads.


## Original-source verification

On 20 November 2026, a clean PostgreSQL 17.12 test database reconciled the first official downloads with the pilot. The unmodified files are in the checkout's Git-ignored `.local/source-cache`. The verification transaction recorded each URL, UTC retrieval time, file length, and SHA-256. The working pilot database still serves the reviewed sample.

| Source | Acquisition and scope | Retrieved at (UTC) | Bytes |
|---|---|---|---:|
| [SEC EDGAR accession directory](https://www.sec.gov/Archives/edgar/data/49826/000004982626000049/) | Browser download of `0000049826-26-000049-xbrl.zip`. The importer read `itw-20260630.htm` directly from the ZIP. Seven consolidated USD observations matched the reviewed ITW filing. | 2026-11-20 09:53:58.963 | 159,244 |
| [Treasury October 2024 XML](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value_month=202410) | HTTPS request returned HTTP 200. All 15 yields matched for 21–25 October at 2, 5 and 10 years. | 2026-11-20 09:50:53 | 25,643 |

ITW's 30 June balance-sheet cash was $839M and first-half operating cash flow was $1.346B. The source reports $187M on the XBRL payments concept. The proof preserves that value and applies the opposite sign when comparing it to the reviewed statement's cash outflow. The [SEC filing index](https://www.sec.gov/Archives/edgar/data/49826/000004982626000049/0000049826-26-000049-index.htm) separately shows acceptance at 15:34:23 Eastern on 6 August 2026. That metadata already exists in the reviewed pilot. Treasury publication timestamps stay null because the XML's feed update time does not establish the observations' original publication times.

The initial load inserted 2 payloads, 2 fetch records, 7 XBRL facts, and 15 yield observations. The archived replay inserted zero rows, with identical row contents and IDs. A simulated upstream error page was rejected, and replaying the valid archive recovered successfully. All three pilot SQL checks passed with the original-source rows present.

### Replay the verified downloads

Use a disposable PostgreSQL database with [the migrations](data_dictionary.md#reproduce-the-database-with-docker-compose) and the reviewed pilot already loaded. From this checkout, set `review_db` to its name and run the following:

```sh
python3 -m pipelines.verify_live_sources --database "$review_db" \
  --sec-zip .local/source-cache/56a20366f2394c7f2a62bb99e213c6a1c510bdb874ca1134c01ce28b062d6040.zip \
  --sec-retrieved-at '2026-11-20T09:53:58.963Z' \
  --treasury-xml .local/source-cache/467d84757a00bbcfecdb20c9572f095efb9ee365922ecb497ecf187f61028455.xml \
  --treasury-retrieved-at '2026-11-20T09:50:53Z'
```

For a new download, use the official URLs above and record the actual completion time with a UTC offset. The command verifies this fixed sample. It uses the existing reviewed filing metadata and stores the original XBRL observations with source locators. The pilot's published calculations still use the reviewed mapping.

### Remaining source gate

Command-line SEC requests returned HTTP 403 during the original-source sample check. The subsequent historical backfill used a declared project contact in line with the [SEC's fair-access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) and successfully downloaded Submissions and Company Facts for all three issuers. The subsequent Treasury backfill archived seven annual XML responses and verified the 2-, 5-, and 10-year series through 19 November 2026. Historical vintages stay flagged as unverified. [SEC backfill and replay instructions](sec_backfill.md) · [Treasury history and replay instructions](treasury_history.md)
