# Module 4.2 refresh and recovery

The local refresh workflow keeps the last verified version available while new data is checked. A source check captures EDGAR submissions for the six reviewed companies and Treasury par-yield feeds for the relevant year or years. It records whether the sources contain a later 10-K, 10-Q, amendment, or Treasury observation. The current release covers SEC filings and Treasury observations through 19 November 2026. Moving either cutoff requires a reviewed candidate and the applicable accounting and SQL checks. The source check detects new arrivals. Review historical corrections and qualification changes through the normal filing and dataset review workflow. [Versioned datasets](local_dataset_publication.md)

## Local operations

Run these from the project checkout using the same Python environment as FastAPI. Keep the existing Docker PostgreSQL instance running. Set `SEC_CONTACT_EMAIL` through the runtime environment before making network requests, using the project contact authorized for SEC request headers. SEC requests use the existing rate limiter and bounded retries. [SEC data APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [Treasury rate feeds](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml)

```sh
python -B -m pipelines.refresh_dataset check-sources
python -B -m pipelines.refresh_dataset status
python -B -m pipelines.refresh_dataset refresh
```

- `check-sources` archives raw responses and writes `latest-source-check.json` after both sources succeed. `review_required` signals newer coverage. Its successful exit confirms that both sources were reached and parsed.
- `refresh` without a candidate verifies the active archive and its read-only PostgreSQL database. To publish an approved candidate, run `refresh --manifests-from <directory>` with `sec.json`, `statements.jsonl`, `treasury.json`, and the reviewed `cohort.json` for the six-company dataset. The publisher checks retrieval watermarks against the newest published version, runs the finance and historical SQL checks in a candidate database, and verifies the prepared API database before atomically switching the active version. The prior version remains available for replay.
- Structured logs report the attempt result, channel, and run ID. A failure returns a nonzero exit code. A duplicate scheduled check skips a locked catalog and emits `refresh_skipped` without recording a successful heartbeat. The dashboard reads the latest recorded source and publication states on page load and displays verified coverage dates after five calendar days of age. Dates use New York time and age is tracked independently of the job result. A successful check older than 36 hours is overdue. A run still marked in progress after 15 minutes is treated as failed.
- Preserve the project contact and the database reader password through the existing runtime configuration. Refresh status, local backup files, logs, and captures belong under the Git-ignored `.local` directory.

## Backup, restore, and rollback

```sh
python -B -m pipelines.refresh_dataset backup --destination .local/recovery/backup-001
python -B -m pipelines.refresh_dataset --directory .local/recovery/backup-001 restore \
  --version v0004 --database ftf_recovery_001
python -B -m pipelines.refresh_dataset activate --version v0003
python -B -m pipelines.refresh_dataset activate --version v0004
```

Back up after publication and before a migration. The backup verifies the copied catalog, source manifests, and PostgreSQL dumps. It includes all published versions and is written to a new directory only after verification. The local copy lives on the same drive. The provider rehearsal must verify a separate private copy and the ability to recover it independently. Preserve the raw source cache separately for future rebuilds from original payloads.

Restore into a fresh database. The command checks archive integrity before touching PostgreSQL and checks the restored row counts against the selected release. Record the restored version, snapshot ID, row counts, and elapsed time. Compare representative filing-backed metrics and the Treasury estimate against the original release. A scratch restore leaves the serving pointer in place. For rollback, activate a retained version in the working catalog. Activation verifies the archive and prepares its API database before switching. Rehearse this on a disposable copy of the working catalog before changing the serving catalog. Keep the backup directory intact.

The November 2026 local rehearsal verified four archived versions and restored v0004 into an empty PostgreSQL database. The restore matched 6 issuers, 160 filings, 1,133 qualified statement observations, and 1,722 Treasury observation dates. The restored database passed the cohort and Treasury SQL checks. A separate catalog successfully switched to v0003 and then back to v0004.

## Hosted schedule and acceptance

Use one daily source check at **19:15 America/New_York** (`15 19 * * *`), after the Treasury's daily market input collection. Use the Cloud Run execution result, since Cloud Scheduler's successful call only confirms the job was triggered. Give the scheduler identity permission to invoke the one job. Use a separate job identity with narrowly scoped archive, catalog, and secret permissions. Use one task, a 10-minute timeout, and one task retry. Rerun on demand after an outage. The local file lock must become a shared lock or generation-checked publication on the hosted path before running multiple executions against a shared catalog. [Cloud Run job scheduling](https://docs.cloud.google.com/run/docs/execute/jobs-on-schedule) · [Cloud Scheduler time zones](https://docs.cloud.google.com/scheduler/docs/configuring/cron-job-schedules) · [Treasury rate methodology](https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics)

Route terminal Cloud Run job failures to the owner's approved notification channel. Route `refresh_completed` with `result=review_required` as a review notification. Run an hourly watchdog against the last successful source-check timestamp, including review-required outcomes. Alert at the first hourly check after it passes 36 hours. Verify one normal scheduled run, one duplicate trigger, one forced failure with a delivered alert, and one delayed or missed run. Confirm the public API serves the same last verified version during each source or validation failure. [Cloud Run monitoring](https://docs.cloud.google.com/run/docs/monitoring) · [Cloud Logging alerts](https://docs.cloud.google.com/logging/docs/alerting/log-based-alerts)

After a manual run verifies the hosted job and its identities, create the daily trigger with the approved project and scheduler service account.

```sh
gcloud scheduler jobs create http filing-to-funding-source-check \
  --project "${FTF_GCP_PROJECT}" --location us-east4 \
  --schedule '15 19 * * *' --time-zone America/New_York \
  --http-method POST \
  --uri "https://run.googleapis.com/v2/projects/${FTF_GCP_PROJECT}/locations/us-east4/jobs/filing-to-funding-refresh:run" \
  --oauth-service-account-email "${FTF_SCHEDULER_ACCOUNT}"
```

The hosted source job now writes its heartbeat and source-check result in the shared catalog using column-level permissions. On 24 November 2026, it archived verified responses from all six SEC submissions feeds and the Treasury feed in a write-once Cloud Storage prefix. The Treasury feed reached **23 November 2026**, so the job recorded **review required**. The serving snapshot remained **v0004**. A forced failure retained the last successful timestamp and left v0004 available through the private API.

The daily trigger is configured for **19:15 America/New_York** with its own invocation identity. A clock-triggered rehearsal returned HTTP 200, ran successfully, and was followed by restoration of the daily schedule. The parallel trigger logged a lease skip. The forced-failure notification arrived on the project-only Pub/Sub subscription. A review-required policy also uses that internal channel. The hourly read-only watchdog read the live source timestamp successfully. Its isolated drill supplied a timestamp 36 hours and 1 second old and delivered the missed-refresh alert to the private Pub/Sub subscription. The live last-success timestamp remained intact. The watchdog now uses its own read-only login for refresh status and cannot access the snapshot databases. Email routing has not been configured.

The isolated Cloud Run recovery job downloaded all four archived versions, verified the backup, and restored **v0003** and **v0004** into scratch PostgreSQL. Both versions matched the archived counts and passed their historical finance and Treasury SQL checks. Download, verification, and restore took **5.83 seconds**. The serving version remained v0004 throughout the scratch restore. The hosted rollback drill copied the catalog into `ftf_release_drill` and attached a private, zero-traffic API revision. On that route, activating v0003 returned three companies and rejected a stale v0004 pin with HTTP 409. Reactivating v0004 returned all six companies and v0003 remained replayable. The live route stayed on v0004. The test route was removed and the default service template was restored. Refresh the shadow copy before repeating the drill against a newer catalog. The initial Google Cloud billing report showed ₹0.00 posted, with usage still subject to posting delay. [Hosting and budget](hosting_and_budget.md)
