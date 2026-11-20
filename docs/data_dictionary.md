# Pilot PostgreSQL model

Pilot Task 3 establishes storage for the filing reconciliation and the next ingestion task. The [v1.2 architecture](filing-to-funding-audit-v1.2.md) and the [hand-checked examples](pilot_reconciliation.md) specify the results the later stages need to reproduce.

| Table | One row represents | Key and provenance |
|---|---|---|
| `raw.source_payloads` | An archived response body or reviewed extract | SHA-256 of the archived bytes, a storage key, and byte count. Repeated fetches can reference the same body. |
| `raw.source_fetches` | A fetch or reviewed extract associated with a source URL | Source type, URL, payload hash, and insertion time. Retrieval time is null for reviewed extracts. |
| `core.issuers` | A reporting entity | The ten-character SEC CIK, including leading zeros. |
| `core.issuer_aliases` | A ticker or legal name in use over an interval | CIK, alias kind, alias, inclusive start date, and optional exclusive end date. |
| `core.reporting_periods` | An issuer's fiscal year or standalone fiscal quarter | CIK, fiscal year, optional quarter, and actual start and end dates. An annual period and its Q4 can share an end date. |
| `core.filings` | An SEC periodic filing or amendment | Accession, issuer, reporting period, form, filing date, optional acceptance instant and source timezone, filing URL, and metadata fetch. |
| `core.reported_facts` | A distinct numerical observation from a filing | Accession, taxonomy and concept, interval or instant, unit, dimensions, reporting basis, issuer-specific scope, source precision, value, and source fetch and locator. |
| `core.treasury_yield_observations` | A published 2-, 5-, or 10-year nominal Treasury par yield as seen in a source fetch | Observation date, maturity in months, percent value, fetch, and publication timestamp when supported by source evidence. |

`raw.schema_migrations` records the applied SQL versions. The `analytics` schema contains the [pilot calculation and historical-selection functions](financial_methodology.md), the [qualified historical quarter and trailing calculations](historical_correctness.md#qualified-sql-results), and the [financial ratios](financial_ratios.md#metric-rules).

## Dates, amounts, and repeated observations

- A filing's reporting period is separate from each fact's period. A June 2025 10-Q can contain a comparative from January to June 2024. Both the filing accession and the comparative interval survive storage. An instant such as quarter-end cash has a null start date.
- Filing date, acceptance instant, retrieval time, and database insertion time are separate. For the strict date-based historical view, use the filing date and require a verified acceptance instant before the next midnight in America/New_York. Missing acceptance time stays null and is excluded from this strict view. A fetch timestamp can show when the platform observed a disclosure. It cannot stand in for SEC acceptance.
- Store XBRL numerical values as exact PostgreSQL `numeric` in source units. An amount displayed as 370,255 USD thousands is stored as 370255000 USD. Preserve decimals metadata where available. A genuinely reported zero is a value. Unavailable data has no qualifying numeric observation.
- Preserve exact context dimensions as a JSON object and assign a scope key that differentiates changes in the businesses covered by a number. Scope and reporting basis must be checked when joining operands. Two distinct values for the same concept, period, unit, and context can coexist for investigation. An exact duplicate observation violates the unique constraint, including when its start date or precision is null. A source locator can be an inline XBRL fact ID or a JSON pointer. The pilot stores reviewed statement lines and their assigned reporting scopes.
- Treasury values are percentages. A value of 4.125 represents 4.125%, and the observation date identifies the market date. Preserve different fetches for vintage review. Use a null publication timestamp when no exact time is available.

The [source register](source_register.md) describes the imported sample, its provenance, and how to reproduce the load. The pilot analytics checks eligibility by period, filing date, and reporting scope while retaining the original evidence.

## Run locally

### Existing macOS pilot checkout

The repository-local installation uses the PostgreSQL 17 binaries from [Postgres.app](https://github.com/PostgresApp/PostgresApp/releases/tag/v2.9.7). Its database and log files live under the Git-ignored `.local/postgres` directory. The native server uses a private Unix socket with peer authentication. Run from the repository root as the OS user who initialized the database:

```sh
pg_bin="$PWD/.local/postgres/runtime/Postgres.app/Contents/Versions/17/bin"
"$pg_bin/pg_ctl" -D .local/postgres/data status
"$pg_bin/psql" -X -h "$PWD/.local/postgres/socket" -p 55432 \
  -d filing_to_funding -f database/migrate.sql
"$pg_bin/psql" -X -h "$PWD/.local/postgres/socket" -p 55432 \
  -d filing_to_funding -f database/tests/pilot_storage.sql
```

If the status command reports the server stopped, start it with `"$pg_bin/pg_ctl" -D .local/postgres/data -l .local/postgres/server.log -w start`. To stop it, use `"$pg_bin/pg_ctl" -D .local/postgres/data -w stop`.

### Reproduce the database with Docker Compose

On a machine with Docker Compose, create a local `.env` containing `POSTGRES_PASSWORD` with a private development password. Keep the same password when reusing the data directory. Run from the repository root:

```sh
docker compose --env-file .env -f infrastructure/docker/compose.yaml up -d --wait
docker compose --env-file .env -f infrastructure/docker/compose.yaml exec -T postgres \
  psql -X -U filing_to_funding -d filing_to_funding -f /workspace/database/migrate.sql
docker compose --env-file .env -f infrastructure/docker/compose.yaml exec -T postgres \
  psql -X -U filing_to_funding -d filing_to_funding -f /workspace/database/tests/pilot_storage.sql
```

Compose uses the [official PostgreSQL image](https://hub.docker.com/_/postgres), a loopback port of 55432 by default, and a separate data directory under `.local/docker-postgres`. The migration records its version in one transaction and can be run again without recreating the schema. The storage test rolls back its sample rows.
