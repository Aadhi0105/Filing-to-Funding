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

The publish example uses the same captures as active `v0003`. The publisher reports `already_active` when the input captures and methodology match the active snapshot. Updated methodology builds a fresh candidate. For a new candidate supply the applicable `--sec-manifest`, `--statement-manifest`, and `--treasury-manifest` paths. Omitted flags use the initial archived captures documented in the [SEC backfill](sec_backfill.md), [filing qualification](historical_correctness.md), and [Treasury backfill](treasury_history.md) guides. Publishing rebuilds from those archives and the checked-out methodology. An older capture is rejected once a newer version is active.

Restore requires a new database name. Omit `--version` to choose the active snapshot. Connect to the named database to query the restored version.

```sh
docker compose --env-file .env -f infrastructure/docker/compose.yaml exec -T postgres \
  psql -U filing_to_funding -d ftf_replay_v0001
```

Restore runs inside a PostgreSQL transaction and checks the restored counts against the published record. It preserves the working database and active catalog entry. Use the snapshot's original database major version for the local replay.

## Publication checks and storage

1. The publisher takes a local refresh lock and compares the capture timestamps and hashes with the active snapshot. It rejects missing or older inputs and different payloads for the same logical source and retrieval time.
2. It creates a clean candidate database, runs migrations, replays the reviewed fixtures and archived captures, and checks qualified SEC evidence for contradictory values before running the other nine SQL checks covering storage, imports, historical cutoffs, financial outputs, Treasury history, filing revisions, and fiscal periods. A conflict rejects the candidate with its accession, concept, and period.
3. It archives the candidate's schema, SQL functions, data, and provenance in a PostgreSQL dump. The snapshot also contains copies of the input manifests, hashes of the methodology files, coverage dates, validation checks, and row counts. The source payloads remain in the content-addressed local cache.
4. It atomically replaces `.local/datasets/catalog.json` once the snapshot is ready. A failed candidate, an interrupted run before this update, or a rejected concurrent run leaves the active entry intact. A retry can reuse an already validated archive if the previous run stopped before committing the catalog.

Keep `.local/datasets/` for replay and `.local/source-cache/` for access to the underlying source bytes and rebuilding from captures. Both locations are under the project checkout and excluded from Git. The published dump includes the database's SQL and data. Its manifest identifies the checked-out methodology by file hash for source-level rebuilding.

## Verified local publication

| Version | Status | Treasury archive for the October 24, 2024 observation |
| --- | --- | --- |
| `v0001` | Archived and restored | Retrieved November 20, 2026 at 11:35:33 UTC |
| `v0002` | Archived and restored | Retrieved November 20, 2026 at 11:42:22 UTC |
| `v0003` | Active and restored | Same capture as `v0002` |

Each version covers three issuers, 79 SEC filings, 1,044 qualified statement observations, and 5,166 Treasury yields across 1,722 dates. The two Treasury captures contained identical source payloads. Each restored version returned the 4.21% 10-year yield for October 24, 2024 and retained its own retrieval timestamp. The three versions also returned Illinois Tool Works' Q2 FY2026 free cash flow of $631 million on the reviewed $4.301 billion revenue denominator, for a 14.6710% FCF margin using filings available by August 6, 2026. The G2 recheck confirmed that `v0003` uses the same input hashes as `v0002` and contains migrations 001–009. [G2 decision and evidence](correctness_review.md#module-15-final-recheck)

An invalid Treasury payload, an overlapping attempt, and an interruption during a real staged refresh each left the active catalog unchanged. The interrupted run also cleaned up its candidate database. Retrying the active candidate created no extra version. Publication regression tests cover interrupted catalog updates, stale and conflicting captures, and altered archives or manifests.

```sh
python3 -B -m unittest discover -s pipelines/tests -v
```


## Publish the reviewed expanded cohort

Use the immutable archive of the validated three-company dataset as the base. Its exact SEC and Treasury inputs and database methodology are checked before reuse. The expanded manifest adds the new SEC captures, the base snapshot ID, and hashes of the reviewed inventory and samples. Publication repeats the baseline database checks and verifies the original XBRL observations, expected quarterly and annual values, and pre-filing exclusions before updating the catalog.

```sh
base_id=$(jq -r '.versions[] | select(.version == "v0003") | .snapshot_id' .local/datasets/catalog.json)
base=".local/datasets/snapshots/$base_id"
captures=".local/cohort-qualification/2026-11-19"
python3 -B -m pipelines.expand_cohort "$captures" --base-snapshot-id "$base_id" > "$captures/cohort-derived.json"
python3 -B -m pipelines.publish_dataset publish \
  --sec-manifest "$base/sec.json" --statement-manifest "$base/statements.jsonl" \
  --treasury-manifest "$base/treasury.json" --cohort-manifest "$captures/cohort-derived.json"
```

The cohort capture directory holds the SEC submissions and company-facts manifest in `sec.json` and the original sample filing manifest in `sample-statements.jsonl`. Their source archives must be available in the repository’s ignored `.local/source-cache` directory. The expanded statement history in this release covers only the checked sample facts. Run [web app preparation](company_explorer.md) after publishing.
