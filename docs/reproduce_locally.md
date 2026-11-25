# Reproduce Filing-to-Funding locally

Choose the setup that matches what you want to verify. Each path works from the repository root. The production code reviewed here is pinned to merge commit `1556745`. [Technical evidence](technical_evidence.md) · [Phase 5.1 merge](https://github.com/Aadhi0105/Filing-to-Funding/pull/17)

| Goal | What you need | What you can verify |
| --- | --- | --- |
| Run the frontend with the public demo API | Git, Node.js 24, npm, and access to the public app | Run the five Next.js views locally using the current published dataset. |
| Reproduce the PostgreSQL pilot | Git, Python 3.11, Docker with Compose, and the tracked fixtures | Create PostgreSQL 17.12, import the three-company sample, and verify the SQL calculations. |
| Replay the complete release locally | Both toolchains, plus an approved archive of the release snapshots | Restore the versioned databases and run FastAPI and Next.js locally with the archived data. |

For a new checkout, use the following commands. In an existing checkout, run the setup commands from its root.

```sh
git clone https://github.com/Aadhi0105/Filing-to-Funding.git
cd Filing-to-Funding
git switch --detach 1556745
```

## Run the frontend with the public demo API

This path uses the public Vercel API, so the data follows the live release. The local browser calls its local Next.js server, which forwards the API requests to the public host. The public API accepts anonymous requests.

```sh
npm --prefix apps/web ci
FILING_API_ORIGIN=https://filing-to-funding.vercel.app \
  npm --prefix apps/web run dev -- --hostname 127.0.0.1 --port 3000
```

Open [local Overview](http://127.0.0.1:3000/overview). From another terminal, verify that the local Next.js server can reach the published catalog.

```sh
curl -fsS http://127.0.0.1:3000/api/v1/datasets
npm --prefix apps/web run typecheck
```

The release verified here returned active version `v0004` and displayed six companies. Stop the server with Ctrl+C. [Public Overview](https://filing-to-funding.vercel.app/overview)

## Reproduce the PostgreSQL pilot

Start Docker. The commands create `.env` with a private development password when the file is absent. Keep that file and its password when reusing the local database directory. Compose binds PostgreSQL to loopback on port 55432 by default. To use a different free port, add a `FILING_POSTGRES_PORT` entry to the local `.env`.

```sh
if [ ! -f .env ]; then
  (umask 077; printf 'POSTGRES_PASSWORD=%s\n' \
    "$(python3 -c 'import secrets; print(secrets.token_hex(24))')" > .env)
fi

ftf_compose() {
  docker compose --env-file .env -f infrastructure/docker/compose.yaml "$@"
}

ftf_compose up -d --wait
ftf_compose exec -T postgres psql -X -v ON_ERROR_STOP=1 \
  -U filing_to_funding -d filing_to_funding -f /workspace/database/migrate.sql
python3 -B -m pipelines.load_pilot
```

The loader reads the checked-in SEC and Treasury JSON extracts and archives them in the ignored `.local/source-cache` directory. It runs with Python’s standard library. The fixture import reads all source inputs from disk.

```sh
(
  set -e
  for check in pilot_storage pilot_ingestion pilot_analytics; do
    ftf_compose exec -T postgres psql -X -v ON_ERROR_STOP=1 \
      -U filing_to_funding -d filing_to_funding \
      -f "/workspace/database/tests/$check.sql"
  done
)
```

On an empty database, the tracked fixtures produce **3 issuers, 7 filings, 51 reviewed SEC facts, and 15 Treasury yield observations**. The three SQL checks validate the schema, repeated import behavior, and pilot analytics. [Pilot extracts and reconciliation](pilot_reconciliation.md) · [Database setup and schema](data_dictionary.md)

For the offline Python tests, install the pinned API dependencies in a local virtual environment.

```sh
python3 -m venv .local/phase2-python
.local/phase2-python/bin/python -m pip install -r apps/api/requirements.lock.txt
.local/phase2-python/bin/python -B -m unittest discover -s pipelines/tests
.local/phase2-python/bin/python -B -m unittest \
  apps.api.tests.test_funding_scenario apps.api.tests.test_public_boundary
```

Run `ftf_compose down` to stop PostgreSQL and retain its data under `.local/docker-postgres`.

## Replay the complete release locally

Use an approved snapshot archive containing `.local/datasets/catalog.json` and the corresponding complete `.local/datasets/snapshots/` directories. The archive, along with the original source captures used for historical rebuilds, is stored outside Git. The Git checkout supplies the pilot sample. The approved archive supplies the exact versioned release data and SQL, including `v0004`. [Snapshot publication and restore](local_dataset_publication.md)

With PostgreSQL running as above, install the pinned API dependencies and prepare the snapshots. Preparation verifies the archived manifests, checksums, and restored snapshot identities before the API serves any data.

```sh
python3 -m venv .local/phase2-python
.local/phase2-python/bin/python -m pip install -r apps/api/requirements.lock.txt
.local/phase2-python/bin/python -B -m pipelines.publish_dataset status
.local/phase2-python/bin/python -m apps.api.prepare_local
.local/phase2-python/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

Start Next.js in a separate terminal from the repository root.

```sh
npm --prefix apps/web ci
FILING_API_ORIGIN=http://127.0.0.1:8000 \
  npm --prefix apps/web run dev -- --hostname 127.0.0.1 --port 3000
```

Open [local Overview](http://127.0.0.1:3000/overview) and the [local API reference](http://127.0.0.1:8000/docs). When the reviewed full archive is present, verify the active six-company release and replay `v0003` from the Platform snapshot selector. Run the local integration checks with FastAPI and Next.js running. The browser suite uses Chrome installed on the machine.

```sh
FILING_TEST_LOCAL_API=1 .local/phase2-python/bin/python -m unittest discover -s apps/api/tests
FILING_BROWSER_CHANNEL=chrome npm --prefix apps/web run test:e2e
```

To rebuild from source captures, use the reviewed SEC and Treasury manifests and their archived bytes. Fresh downloads can contain later corrections. The original capture and methodology hashes determine snapshot identity. [Historical SEC backfill](sec_backfill.md) · [Filing qualification](historical_correctness.md) · [Treasury replay](treasury_history.md#replay-locally)
