\set ON_ERROR_STOP on

BEGIN;
SELECT pg_catalog.pg_advisory_xact_lock(2004228903);

CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

SELECT NOT EXISTS (
    SELECT 1 FROM raw.schema_migrations WHERE version = '001_pilot_storage'
) AS apply_pilot_storage \gset

\if :apply_pilot_storage
    \ir migrations/001_pilot_storage.sql
    INSERT INTO raw.schema_migrations (version) VALUES ('001_pilot_storage');
\endif

COMMIT;
