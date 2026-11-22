\set ON_ERROR_STOP on
BEGIN;

-- Keep the routines reachable by the API on the caller's privileges.
DO $check$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'analytics' AND p.prosecdef
    ) THEN
        RAISE EXCEPTION 'The API snapshot contains a privileged analytics routine';
    END IF;
END
$check$;

REVOKE ALL ON DATABASE :"snapshot_database" FROM PUBLIC, :"reader";
GRANT CONNECT ON DATABASE :"snapshot_database" TO :"reader";
REVOKE ALL ON SCHEMA public, analytics, core, raw, app_snapshot FROM PUBLIC, :"reader";
GRANT USAGE ON SCHEMA analytics, core, raw, app_snapshot TO :"reader";
REVOKE ALL ON ALL TABLES IN SCHEMA analytics, core, raw, app_snapshot FROM PUBLIC, :"reader";
REVOKE ALL ON ALL SEQUENCES IN SCHEMA analytics, core, raw, app_snapshot FROM PUBLIC, :"reader";
REVOKE ALL ON ALL ROUTINES IN SCHEMA analytics, core, raw, app_snapshot FROM PUBLIC, :"reader";

GRANT SELECT ON core.issuers, core.issuer_aliases, core.reporting_periods, core.filings,
    core.reported_facts, core.treasury_yield_observations, app_snapshot.identity TO :"reader";
GRANT SELECT (fetch_id, source_kind, source_url, retrieved_at, payload_sha256)
    ON raw.source_fetches TO :"reader";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA analytics TO :"reader";

COMMIT;
