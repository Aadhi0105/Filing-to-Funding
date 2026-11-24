BEGIN;
REVOKE ALL ON SCHEMA ftf_release FROM ftf_source_checker;
REVOKE ALL ON TABLE ftf_release.state FROM ftf_source_checker;
GRANT USAGE ON SCHEMA ftf_release TO ftf_source_checker;
GRANT SELECT (singleton, catalog, refresh_status), UPDATE (refresh_status)
    ON ftf_release.state TO ftf_source_checker;
DROP POLICY IF EXISTS ftf_source_checker_read ON ftf_release.state;
DROP POLICY IF EXISTS ftf_source_checker_write ON ftf_release.state;
CREATE POLICY ftf_source_checker_read ON ftf_release.state
    FOR SELECT TO ftf_source_checker USING (singleton);
CREATE POLICY ftf_source_checker_write ON ftf_release.state
    FOR UPDATE TO ftf_source_checker USING (singleton) WITH CHECK (singleton);
COMMIT;
