# Module 4.3 security and access controls

The public demo serves anonymous research views, CSV downloads, and a stateless funding scenario calculator. It serves qualified financial values and filing provenance through FastAPI. Operational ingestion, publication, backup, and rollback run separately. Filing evidence links to the original SEC document. The application renders financial data as text and avoids embedding filing HTML.

## Local controls

| Surface | Control |
| --- | --- |
| API requests | The API checks URL and body size before parsing. Limits are 512 path characters, 2 KiB of query bytes, and 4 KiB of JSON with a five-second body deadline. The calculator accepts uncompressed JSON with known fields. Input errors omit submitted values. |
| Request volume | Each API process admits four concurrent requests and uses a 20 request-per-second token bucket with a burst of 40. A saturated process returns HTTP 429 and a retry hint. The process limit also applies to callers reaching the API directly. This is a shared limit for the process. |
| API exposure | The public profile turns off the interactive API tools and their schema endpoint. The named research endpoints and calculator remain anonymous. Responses disable storage and content-type sniffing. The API uses parameterized SQL, bounded filing pages, and bounded financial history and export output. |
| PostgreSQL | The snapshot API role has read-only access to the required financial tables, analytics functions, and snapshot identity. Its provenance grant covers five fetch metadata columns, including the source URL and payload hash. Private object keys, migration records, unneeded metadata, and schema creation are outside its grant. The local credential file requires owner-only permissions. |
| Web and downloads | The site sets browser content, framing, referrer, and permissions policies. Its static Next.js pages retain inline bootstrap scripts and chart styles. The deployed browser policies allow same-origin requests. CSV exports protect formula-leading text and preserve signed financial numbers. |

Use the public API profile with the following entry point. The local profile keeps the developer API documentation available.

```sh
FILING_API_PUBLIC=1 uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 \
  --no-access-log --no-proxy-headers
```

The snapshot-preparation command reapplies the ACLs to retained local application databases on a reachable PostgreSQL instance.

```sh
python -B -m apps.api.prepare_local
```

Run `apps/api/tests/reader_privileges.sql` with `psql -v reader=ftf_phase2_reader` against a prepared snapshot. The SQL checks permissions without changing dataset rows. Local verification in November 2026 exercised an isolated PostgreSQL 17.12 instance with the reviewed three-company pilot. The reader could query approved finance and provenance data. The SQL checks denied writes, schema creation, private raw payload metadata, and public database access. The anonymous API served company data, the calculator, and a CSV download with the public profile enabled.

The production web build and Chrome checks verified the security headers, browser loading of all three pilot companies through FastAPI, and the $5 million funding scenario. The Python and frontend runtime dependency audits reported no known advisories for the pinned versions.

## Hosted release gates

1. **Keep access explicit.** Run the API with a dedicated read-only PostgreSQL role and verified TLS. Give the ingestion and publication job its own identity. Keep migration and rollback credentials separate. Disable the unused Supabase Data API and confirm that anonymous direct requests cannot access raw, core, or analytics objects after loading the hosted dataset. Verify the API reader's effective grants on the loaded schema. The initial advisory check reported no findings on the project before its application schemas were loaded. [Supabase Data API controls](https://supabase.com/docs/guides/api/securing-your-api#disable-the-data-api) · [Supabase TLS enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement)
2. **Protect the public edge and direct origin.** Set the Vercel production rewrite to the HTTPS Cloud Run origin. Start Cloud Run with a single API worker, four concurrent requests per instance, and the two-instance ceiling from the hosting plan. Keep the limits at the origin because callers can reach it directly. Review the Hobby allowance before enabling a Vercel rate-limit rule keyed to its verified client identity. Validate normal anonymous use and HTTP 429 behavior on the Vercel URL and the direct origin. [Vercel rate limits](https://vercel.com/docs/vercel-firewall/vercel-waf/rate-limiting) · [Cloud Run concurrency](https://docs.cloud.google.com/run/docs/about-concurrency)
3. **Separate credentials and environments.** Store the database credential and SEC contact in Secret Manager with access scoped to the relevant service or job. Scope the production API origin to the Vercel production environment. Use a separate origin for previews. Give pull-request jobs read-only repository permissions and use short-lived GitHub OIDC credentials for approved publishing jobs. During rotation, install and verify the replacement credential before retiring the previous version. [Cloud Run secrets](https://docs.cloud.google.com/run/docs/configuring/services/secrets) · [GitHub Actions OIDC](https://docs.github.com/en/actions/concepts/security/openid-connect)
4. **Keep logs and archives private.** Retain operational logs in the Cloud Logging project for 30 days. Use status, route templates, run IDs, and dataset versions in application logs. Omit bodies, submitted values, credentials, and raw filing payloads. Review automatic Cloud Run request logs and sink filters before public traffic because platform logging is separate from the application. Record access to private source archives and retained datasets through the operator identities. [Cloud Run logging](https://docs.cloud.google.com/run/docs/logging) · [Cloud Logging retention](https://docs.cloud.google.com/logging/docs/store-log-entries)
5. **Capture release evidence.** Verify the browser security headers and CSV behavior, the reader grants, direct Supabase denial, externally reachable API limits, preview credential separation, and the audit results for the production lockfiles. Record the scope, timing, and result of each check in the release evidence. After a security incident, restrict public traffic through the provider, rotate affected credentials, review access logs, and use the verified release rollback path. [Refresh and recovery](refresh_and_recovery.md)

The hosted checks depend on the hosted API, the loaded Supabase dataset and reader role, and the Google Cloud release configuration. [Hosting and budget](hosting_and_budget.md)
