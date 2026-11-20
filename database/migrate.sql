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

SELECT NOT EXISTS (
    SELECT 1 FROM raw.schema_migrations WHERE version = '002_reviewed_sources'
) AS apply_reviewed_sources \gset

\if :apply_reviewed_sources
    \ir migrations/002_reviewed_sources.sql
    INSERT INTO raw.schema_migrations (version) VALUES ('002_reviewed_sources');
\endif

SELECT NOT EXISTS (
    SELECT 1 FROM raw.schema_migrations WHERE version = '003_pilot_analytics'
) AS apply_pilot_analytics \gset

\if :apply_pilot_analytics
    \ir migrations/003_pilot_analytics.sql
    INSERT INTO raw.schema_migrations (version) VALUES ('003_pilot_analytics');
\endif

SELECT NOT EXISTS (
    SELECT 1 FROM raw.schema_migrations WHERE version = '004_historical_cash_flow'
) AS apply_historical_cash_flow \gset

\if :apply_historical_cash_flow
    \ir migrations/004_historical_cash_flow.sql
    INSERT INTO raw.schema_migrations (version) VALUES ('004_historical_cash_flow');
\endif

SELECT NOT EXISTS (
    SELECT 1 FROM raw.schema_migrations WHERE version = '005_financial_ratios'
) AS apply_financial_ratios \gset

\if :apply_financial_ratios
    \ir migrations/005_financial_ratios.sql
    INSERT INTO raw.schema_migrations (version) VALUES ('005_financial_ratios');
\endif

SELECT NOT EXISTS (
    SELECT 1 FROM raw.schema_migrations WHERE version = '006_treasury_history'
) AS apply_treasury_history \gset

\if :apply_treasury_history
    \ir migrations/006_treasury_history.sql
    INSERT INTO raw.schema_migrations (version) VALUES ('006_treasury_history');
\endif

COMMIT;
