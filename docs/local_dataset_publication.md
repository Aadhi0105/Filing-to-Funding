# Local dataset publication

Each publication is a restorable PostgreSQL snapshot of the three-company correctness dataset. Its coverage follows the reviewed SEC filing inventory through November 19, 2026, and the reviewed 2-, 5-, and 10-year Treasury history from January 1, 2020, through November 19, 2026.

**Filed by date** applies the SEC disclosure cutoff to the facts and calculation inputs inside a dataset. **Platform snapshot** restores what Filing-to-Funding actually published, including the source captures and accounting SQL available to the platform at that publication. A later Treasury archive can contain earlier observations. Its retrieval timestamp records when the platform obtained that archive.

## Publish and restore

Run these commands from the repository root with the local Docker database running and the archived captures available under `.local/`.

```sh
python3 -B -m pipelines.publish_dataset status
python3 -B -m pipelines.publish_dataset publish --treasury-manifest .local/treasury-history-repeat.json
python3 -B -m pipelines.publish_dataset restore --version v0001 --database ftf_replay_v0001
```

The publish example reuses the inputs for the active `v0002` snapshot and reports `already_active`. For a new candidate supply the applicable `--sec-manifest`, `--statement-manifest`, and `--treasury-manifest` paths. Omitted flags use the initial archived captures documented in the [SEC backfill](sec_backfill.md), [filing qualification](historical_correctness.md), and [Treasury backfill](treasury_history.md) guides. Publishing rebuilds from those archives and the checked-out methodology. An older capture is rejected once a newer version is active.

Restore requires a new database name. Omit `--version` to choose the active snapshot. Connect to the named database to query the restored version.

```sh
docker compose --env-file .env -f infrastructure/docker/compose.yaml exec -T postgres \
  psql -U filing_to_funding -d ftf_replay_v0001
```

Restore runs inside a PostgreSQL transaction and checks the restored counts against the published record. It preserves the working database and active catalog entry. Use the snapshot's original database major version for the local replay.

## Publication checks and storage

1. The publisher takes a local refresh lock and compares the capture timestamps and hashes with the active snapshot. It rejects missing or older inputs and different payloads for the same logical source and retrieval time.
2. It creates a clean candidate database, runs migrations, replays the reviewed fixtures and archived captures, and runs the seven SQL suites covering storage, imports, historical cutoffs, financial outputs, and Treasury history.
3. It archives the candidate's schema, SQL functions, data, and provenance in a PostgreSQL dump. The snapshot also contains copies of the input manifests, hashes of the methodology files, coverage dates, validation checks, and row counts. The source payloads remain in the content-addressed local cache.
4. It atomically replaces `.local/datasets/catalog.json` once the snapshot is ready. A failed candidate, an interrupted run before this update, or a rejected concurrent run leaves the active entry intact. A retry can reuse an already validated archive if the previous run stopped before committing the catalog.

Keep `.local/datasets/` for replay and `.local/source-cache/` for access to the underlying source bytes and rebuilding from captures. Both locations are under the project checkout and excluded from Git. The published dump includes the database's SQL and data. Its manifest identifies the checked-out methodology by file hash for source-level rebuilding.

## Verified local publication

| Version | Status | Treasury archive for the October 24, 2024 observation |
| --- | --- | --- |
| `v0001` | Archived and restored | Retrieved November 20, 2026 at 11:35:33 UTC |
| `v0002` | Active and restored | Retrieved November 20, 2026 at 11:42:22 UTC |

Each version covers three issuers, 79 SEC filings, 1,044 qualified statement observations, and 5,166 Treasury yields across 1,722 dates. The two Treasury captures contained identical source payloads. Both restored versions returned the 4.21% 10-year yield for October 24, 2024 with their respective retrieval timestamps. Both also returned Illinois Tool Works' Q2 FY2026 free cash flow of $631 million on the reviewed $4.301 billion revenue denominator, for a 14.6710% FCF margin using filings available by August 6, 2026.

An invalid Treasury payload, an overlapping attempt, and an interruption during a real staged refresh each left the active catalog unchanged. The interrupted run also cleaned up its candidate database. Retrying the active candidate created no extra version. Publication regression tests cover interrupted catalog updates, stale and conflicting captures, and altered archives or manifests.

```sh
python3 -B -m unittest discover -s pipelines/tests -v
```
