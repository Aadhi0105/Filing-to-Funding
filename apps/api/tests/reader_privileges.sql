\set ON_ERROR_STOP on
BEGIN;
SELECT pg_catalog.set_config('ftf_test.reader', :'reader', true);

DO $checks$
DECLARE
    api_reader text := pg_catalog.current_setting('ftf_test.reader');
BEGIN
    IF NOT pg_catalog.has_database_privilege(api_reader, current_database(), 'CONNECT')
        OR pg_catalog.has_database_privilege(api_reader, current_database(), 'CREATE, TEMP')
        OR pg_catalog.has_schema_privilege(api_reader, 'public', 'USAGE, CREATE')
        OR pg_catalog.has_schema_privilege(api_reader, 'raw', 'CREATE')
        OR pg_catalog.has_schema_privilege(api_reader, 'core', 'CREATE')
    THEN
        RAISE EXCEPTION 'Unexpected API reader database or schema privileges';
    END IF;

    IF NOT pg_catalog.has_table_privilege(api_reader, 'app_snapshot.identity', 'SELECT')
        OR NOT pg_catalog.has_table_privilege(api_reader, 'core.filings', 'SELECT')
        OR pg_catalog.has_table_privilege(api_reader, 'core.filings', 'INSERT, UPDATE, DELETE, TRUNCATE')
        OR pg_catalog.has_table_privilege(api_reader, 'raw.source_payloads', 'SELECT')
        OR pg_catalog.has_table_privilege(api_reader, 'raw.schema_migrations', 'SELECT')
        OR pg_catalog.has_table_privilege(api_reader, 'raw.source_fetches', 'SELECT')
        OR pg_catalog.has_column_privilege(api_reader, 'raw.source_fetches', 'recorded_at', 'SELECT')
        OR NOT pg_catalog.has_column_privilege(api_reader, 'raw.source_fetches', 'payload_sha256', 'SELECT')
    THEN
        RAISE EXCEPTION 'Unexpected API reader table or provenance privileges';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles r
        WHERE r.rolname = api_reader
          AND (r.rolsuper OR r.rolinherit OR r.rolcreatedb OR r.rolcreaterole
               OR r.rolreplication OR r.rolbypassrls OR r.rolconnlimit <> 4)
    ) OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_auth_members m
        JOIN pg_catalog.pg_roles r ON r.oid = m.member
        WHERE r.rolname = api_reader
    ) THEN
        RAISE EXCEPTION 'Unexpected API reader role configuration';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_database d
        CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(d.datacl, pg_catalog.acldefault('d', d.datdba))) acl
        WHERE d.datname = current_database() AND acl.grantee = 0
    ) THEN
        RAISE EXCEPTION 'PUBLIC must have zero snapshot database privileges';
    END IF;
END
$checks$;
ROLLBACK;
