\set ON_ERROR_STOP on

BEGIN;
CREATE SCHEMA IF NOT EXISTS ftf_release;
CREATE TABLE IF NOT EXISTS ftf_release.state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    catalog jsonb NOT NULL CHECK (jsonb_typeof(catalog) = 'object'),
    snapshots jsonb NOT NULL CHECK (jsonb_typeof(snapshots) = 'object'),
    refresh_status jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(refresh_status) = 'object')
);
REVOKE ALL ON SCHEMA ftf_release FROM PUBLIC;
REVOKE ALL ON TABLE ftf_release.state FROM PUBLIC, :"reader";
GRANT USAGE ON SCHEMA ftf_release TO :"reader";
GRANT SELECT ON TABLE ftf_release.state TO :"reader";
ALTER TABLE ftf_release.state ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ftf_reader_catalog ON ftf_release.state;
CREATE POLICY ftf_reader_catalog ON ftf_release.state FOR SELECT TO :"reader" USING (true);
COMMIT;
