# Local Company Explorer

The Phase 2 Explorer reads the three-company correctness dataset through a versioned FastAPI API and Next.js. It supports **Latest reported**, **Filed by date**, and **Platform snapshot** for the published local versions. Select an annual, quarterly, or trailing period, inspect the reported metrics and underlying SEC evidence, and export the selected period and free cash flow series.

## Start locally

From the repository root, start the [Docker PostgreSQL database](data_dictionary.md#reproduce-the-database-with-docker-compose) and prepare the published snapshots.

```sh
python3 -m venv .local/phase2-python
.local/phase2-python/bin/python -m pip install -r apps/api/requirements.lock.txt
.local/phase2-python/bin/python -m apps.api.prepare_local
.local/phase2-python/bin/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

The preparation command restores each published archive into a separate app database and verifies its identity. The application uses a read-only PostgreSQL login. Its generated password is stored in the Git-ignored `.local/phase2-api/password` with owner-only permissions. Run the preparation command again after publishing a new dataset.

In a second terminal with Node.js available, run the following from the repository root.

```sh
npm --prefix apps/web ci
NEXT_TELEMETRY_DISABLED=1 npm --prefix apps/web run dev -- --hostname 127.0.0.1 --port 3000
```

Use this command to select the repository-local Node installation on the review Mac.

```sh
export PATH="$PWD/.local/phase2-node/node-v24.22.3-darwin-arm64/bin:$PATH"
```

Open [Company Explorer](http://127.0.0.1:3000/) or the [FastAPI reference](http://127.0.0.1:8000/docs) while the services are running. The Next.js server proxies `/api/v1/` to the local API. Set `FILING_API_ORIGIN` on the web server if the API uses a different loopback port.

## Historical modes and evidence

| Reporting mode | Dataset and selection |
| --- | --- |
| Latest reported | Uses the active published dataset and the latest eligible disclosure in its reporting scope. |
| Filed by date | Uses the active dataset and the selected New York end-of-day cutoff within its verified filing window. |
| Platform snapshot | Uses the selected archived database and its original methodology. Snapshots before migration 008 lack annual flows and linked filing revisions. |

The Explorer preserves the company, fiscal period, duration, and reporting mode in its URL. Unavailable values retain their quality status and stay blank in the CSV. Chart lines break at missing values and changes in reporting scope. The accessible chart table shows each point and the exact period. Selected metrics link to their source facts, with the original SEC accession, filing date, and document location. The export carries the same dataset, methodology, cutoff, scopes, statuses, and source accessions. If the active version changes between the chart and export requests, the API asks for a refresh before serving the export.

## Verify

With the two services running, run the API and browser checks from the repository root.

```sh
FILING_TEST_LOCAL_API=1 .local/phase2-python/bin/python -m unittest discover -s apps/api/tests
python3 -m unittest discover -s pipelines/tests
npm --prefix apps/web run typecheck
FILING_BROWSER_CHANNEL=chrome npm --prefix apps/web run test:e2e
NEXT_TELEMETRY_DISABLED=1 npm --prefix apps/web run build
```

The browser tests use a fresh test session and the installed Chrome when the channel is specified. They check the filing cutoff, archived methodology, chart and CSV agreement, keyboard navigation, and phone layout.

The web types are generated from the FastAPI OpenAPI schema. Regenerate them from the repository root after API contract changes.

```sh
.local/phase2-python/bin/python -B -c 'import json; from apps.api.main import app; print(json.dumps(app.openapi()))' > .local/phase2-api/openapi.json
apps/web/node_modules/.bin/openapi-typescript .local/phase2-api/openapi.json -o apps/web/app/api-types.ts
```
