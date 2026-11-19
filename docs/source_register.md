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

The curated filing observations use the `filing-line` namespace. Their locators are JSON pointers to the exact displayed line in the archived extract. Store dollar amounts at their original displayed precision and retain the statement's sign for capex. The [pilot calculations](financial_methodology.md) normalize capex and apply reporting-scope and historical-eligibility rules. Automated SEC XBRL and Treasury XML retrieval, coverage outside these samples, and validation of historical yield vintages remain open.
