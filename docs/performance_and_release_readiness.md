# Module 4.4 performance and release readiness

**Local rehearsal passed on 23 November 2026. Hosted G4 sign-off remains pending.** The tested release was the restored six-company dataset **v0004**, with SEC and Treasury coverage through **19 November 2026**. The rehearsal used a local Next.js production build in Docker, one FastAPI process, and an isolated PostgreSQL 17.12 instance.

## Correctness and recovery

- Checksum-verified and restored all four retained snapshots. PostgreSQL reader-grant checks passed for each version. Five SQL suites passed for v0004, covering cohort evidence, source conflicts, Treasury history, filing revisions, and fiscal-period metrics.
- The restored v0004 contained **6 issuers**, **160 filings**, **1,133 qualified statement observations**, and **1,722 Treasury observation dates**. The four prepared databases occupied **44.0 MiB** locally.
- **31 API tests**, **30 pipeline tests**, and **11 Chrome tests** passed. The API run included all 12 previously skipped live-dataset tests. It caught and verified a fix for an unsupported POST returning HTTP 415. The API now returns HTTP 405 there and applies the JSON body policy to the funding submission.
- A simulated SEC outage returned failed source status through the API. Chrome showed the failure banner and all six company cards on the real v0004 data. The working catalog switched to v0003 and back to v0004. A client pinned to v0004 received a version mismatch during rollback.
- A separate v0004 restore into a fresh local database completed in **402 ms**, including archive verification and row-count comparison. The PostgreSQL test data directory was in memory. Hosted recovery time and recovery point still require a private Cloud Storage restore drill.

## Warm local performance

The benchmark sent three warm-up requests and 30 measured requests per endpoint through the production frontend rewrite. It scheduled five requests per second, with up to two requests in flight and one endpoint measured at a time. Times are local HTTP round trips. The p95 uses the nearest rank among successful responses. All **180 measured requests** succeeded and returned the requested dataset. A run pinned to the wrong version failed at warm-up.

| Endpoint | Median ms | p95 ms | Max ms |
| --- | ---: | ---: | ---: |
| Overview | 120.2 | 148.4 | 148.7 |
| Company Explorer | 86.0 | 103.5 | 209.4 |
| Peer Comparison | 91.2 | 194.9 | 236.9 |
| Filing History | 41.3 | 54.6 | 65.6 |
| Treasury curve | 46.9 | 56.9 | 60.3 |
| Funding scenario | 48.2 | 55.8 | 163.9 |

A separate five-run check restarted the local API for every first Overview response. From process launch through the first completed response, the median was **1.02 s** and the maximum was **1.19 s**. PostgreSQL was already running. Record Cloud Run cold starts separately using the deployed revision and instance startup telemetry. [Cloud Run monitoring](https://docs.cloud.google.com/run/docs/monitoring)

Run the benchmark from the project checkout against the reviewed release and a prepared app origin.

```sh
python -m apps.api.benchmark --origin http://127.0.0.1:3008 --dataset-version v0004
```

For the hosted rehearsal, use the approved HTTPS origin and record the source region, revision, dataset, instance and pool settings, request rate, errors, and observed cost. Set `--rate 1` if the Vercel edge rule requires a lower request rate, and record it with the result. Each endpoint must have zero errors and warm **p95 below 2 seconds**. The command exits nonzero on a version mismatch, response failure, or missed threshold.

## Hosted sign-off

The Vercel project had zero deployments at inspection. The default Supabase database had zero application schemas. The rehearsal needs a Cloud Run target, the TLS-enabled hosted database and catalog, and the private artifact store specified in the hosting plan.

| Gate | Evidence to collect |
| --- | --- |
| Performance and budget | Benchmark through Vercel and the Cloud Run origin. Record cold-start timings, runtime and database connection usage, storage and egress, and observed costs against the approved plan. |
| Refresh and availability | Verify a scheduled SEC and Treasury check, simulate a failed check, confirm alert delivery, and confirm v0004 remains available until a reviewed release is published. |
| Recovery and rollback | Recover the active release and a retained version from private Cloud Storage. Verify checksums, row counts, and historical query results. Record the recovery point and recovery time, and verify rollback through the hosted API. |
| Security and release | Verify the hosted reader and ingestion identities, the Supabase Data API boundary, preview credential separation, and effective request limits. Review the combined evidence before approving public publication. |

[Hosting and budget](hosting_and_budget.md) · [Refresh and recovery](refresh_and_recovery.md) · [Security and access controls](security_and_access.md) · [v1.2 release gates](filing-to-funding-audit-v1.2.md#7-stage-gates-and-evidence-required)
