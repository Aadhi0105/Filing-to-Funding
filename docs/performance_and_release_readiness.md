# Module 4.4 performance and release readiness

**Phase 5.1 was published and verified on 24 November 2026.** The local rehearsal passed on 23 November, and the private hosted rehearsal passed on 24 November. The tested release was the restored six-company dataset **v0004**, with SEC and Treasury coverage through **19 November 2026**. The rehearsal used a local Next.js production build in Docker, one FastAPI process, and an isolated PostgreSQL 17.12 instance.

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

On 24 November 2026, the protected Vercel preview loaded all six companies in **v0004**, replayed the three-company **v0003** archive, and calculated **$250,000.00** of incremental annual interest for the default sample scenario. The preview used a workspace-scoped Vercel identity to invoke the private Cloud Run service. An anonymous Vercel API request redirected to sign-in. [Private Vercel preview](https://filing-to-funding-g38fciq55-psat0501-5187.vercel.app/overview) · [Hosting and budget](hosting_and_budget.md)

| Gate | Evidence from the private hosted rehearsal |
| --- | --- |
| Performance | All **72 measured browser flows** returned the expected v0004 data or the expected calculator result. The slowest warm p95 was **1.052 s**. The earlier private Cloud Run Overview measured **0.905 s p95** over 12 requests. The earlier 24-hour Cloud Monitoring sample had two starts averaging **5.49 s**, 48 API requests, and 25.2 billable instance seconds. PostgreSQL showed two reader sessions out of 60 configured server connections in a point-in-time check. This is a low-load rehearsal. |
| Budget | Google Cloud Billing showed **₹0.00** posted for the November 1–23 charge period when checked on 24 November. Late usage can post after the report. The trial showed **₹28,569** in remaining credit. The Vercel Hobby Usage dashboard showed **41 of 1,000,000** included function invocations at the time of inspection. Supabase Free hosted **54.8 MiB** across five connectable databases, including provider schemas. The updated Google Cloud model remains below **$5/month** at the planned workload. |
| Refresh and availability | The hosted source job archived six SEC responses and one Treasury response. The clock-triggered and duplicate-skip rehearsals passed. The forced failure preserved the last success timestamp and v0004 and delivered a test notification. The hourly watchdog read the live timestamp successfully and delivered the 36-hour alert to the internal subscription using an isolated timestamp **36 hours and 1 second** old. |
| Recovery and rollback | All four backups restored locally and passed 31 API tests. The isolated Cloud Run recovery job restored v0003 and v0004 with matching hashes and counts in **5.83 seconds**. A separate hosted catalog and zero-traffic revision served **v0004 (6 companies) → v0003 (3) → v0004 (6)**. A stale version pin returned **409** and v0003 remained replayable. The live API stayed on v0004. The temporary drill route was removed and the normal service template restored. |
| Security | The unused Supabase Data API was disabled with the owner's approval. The setting persisted after reload, and the private preview still served all six companies. Supabase Security Advisor returned no findings. Anonymous and authenticated database roles had no access to either catalog. The reader had SELECT only, the source checker could update refresh status only, and the snapshot publisher could no longer sign in. Direct Cloud Run returned **403** without authorization. The serving revision uses the exact Vercel Preview identity, enforced TLS, two instances maximum, and four concurrent requests per instance. The hosted API disabled docs and OpenAPI, rejected oversized query strings and bodies, and sent `no-store` and `nosniff`. |

### Warm browser timings

Chrome exercised the signed-in Vercel Preview deployment in one session. Each flow ran three warmups followed by 12 sequential measured operations. GET timing includes browser navigation and reading the pinned v0004 JSON response. Calculator timing includes the time from submitting each test input until the expected result appeared on screen. Values use nearest-rank p95. Cold start and concurrent public traffic need separate checks.

| Flow | p95 |
| --- | ---: |
| Overview | 1,052 ms |
| Company Explorer | 832 ms |
| Peer Comparison | 901 ms |
| Filing History | 856 ms |
| Treasury curve | 635 ms |
| Funding Scenario | 620 ms |

### Production credential cutover

On 24 November, the API, source check, and watchdog moved to separate expiring runtime logins. Both private API origins served the four snapshots, and unauthorized requests to each returned HTTP 403. The protected Preview showed v0004 and produced **$250,000.00** of incremental interest for the default funding scenario after the credential switch. The source-check and watchdog jobs completed with their new credentials. The temporary logins and their Secret Manager versions were disabled. A local Next.js Production build passed and registered the server-side API route. Vercel had no ready Production deployment. The first rotation is due by **23 January 2027**, ahead of expiry at **05:14 IST on 22 February 2027**. [Credential rotation](security_and_access.md#hosted-credential-rotation)

## Phase 5.1 production release

The owner approved publication on **24 November 2026**. Vercel Production deployed the verified 22-file web source bundle to the project domain. The release uses the Production-only Vercel workload identity and private Cloud Run revision `ftf-api-production-00001-m89` in Northern Virginia. Deployment `dpl_4Yv3swsDC7nTXjmxSPZ38dTDgUhP` built from the reviewed local source with bundle SHA-256 `6b25944b511ed4dc96b1581cca7b3949a305ad8aaf07f2b0e29f06b4de5f3b61`. [Live demo](https://filing-to-funding.vercel.app/overview) · [Vercel deployment](https://vercel.com/psat0501-5187/filing-to-funding/4Yv3swsDC7nTXjmxSPZ38dTDgUhP)

| Release check | Observed result |
| --- | --- |
| Public access and workload identity | The branded HTTPS domain returned HTTP 200 without sign-in. The public API retrieved v0004 data through the Vercel identity. The direct Cloud Run origin denied anonymous access with HTTP 403. |
| Browser and history | All five public views loaded. Overview showed six companies, replayed the three-company v0003 archive, and returned to v0004. Anonymous API requests replayed all four versions and returned six companies on the 19 November filed-by cutoff. |
| Calculation and export | The default funding scenario returned **$250,000.00** in incremental interest. The company export returned a **21-row CSV attachment** pinned to v0004. |
| Request bounds | The public edge returned HTTP 409 for a stale version pin, 414 for an oversized URL, 413 for an oversized request body, 415 for an unsupported body type, and 404 for the unpublished OpenAPI route. The response security headers passed. The seven local API boundary tests also passed, including HTTP 429, Retry-After, and request body deadlines. |
| Warm performance | All **120** measured Vercel-to-Cloud Run requests passed with zero errors, using 20 requests per endpoint after three warmups, at up to two requests per second and two in flight from India. Every warm p95 was below two seconds. |
| Refresh | The source checker flagged newer Treasury coverage for review. The public app continued to serve the last verified dataset, v0004. |

| Public endpoint | Warm p95 |
| --- | ---: |
| Overview | 772.0 ms |
| Company Explorer | 847.4 ms |
| Peer Comparison | 713.9 ms |
| Filing History | 820.9 ms |
| Treasury curve | 574.7 ms |
| Funding scenario | 691.4 ms |

**Phase 5.1 is complete.** Keep the scheduled credential rotation and Google Cloud billing reconciliation in routine operations. The next portfolio milestone is 5.2.

[Hosting and budget](hosting_and_budget.md) · [Refresh and recovery](refresh_and_recovery.md) · [Security and access controls](security_and_access.md) · [v1.2 release gates](filing-to-funding-audit-v1.2.md#7-stage-gates-and-evidence-required)
