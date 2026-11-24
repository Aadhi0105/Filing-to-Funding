-- One-time authorization migration after hosted_catalog.sql and hosted_sources.sql.
-- The active login and its expiry are configured separately. Keep credentials out of SQL files.
BEGIN;
CREATE ROLE ftf_api_reader_a NOLOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS CONNECTION LIMIT 12;
CREATE ROLE ftf_api_reader_b NOLOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS CONNECTION LIMIT 12;
CREATE ROLE ftf_source_runner_a NOLOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS CONNECTION LIMIT 2;
CREATE ROLE ftf_source_runner_b NOLOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS CONNECTION LIMIT 2;
CREATE ROLE ftf_heartbeat_reader_a NOLOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS CONNECTION LIMIT 2;
CREATE ROLE ftf_heartbeat_reader_b NOLOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS CONNECTION LIMIT 2;
CREATE ROLE ftf_heartbeat_read NOLOGIN NOCREATEDB NOCREATEROLE NOBYPASSRLS;

GRANT ftf_phase2_reader TO ftf_api_reader_a, ftf_api_reader_b WITH INHERIT TRUE, SET FALSE;
GRANT ftf_source_checker TO ftf_source_runner_a, ftf_source_runner_b WITH INHERIT TRUE, SET FALSE;
GRANT ftf_heartbeat_read TO ftf_heartbeat_reader_a, ftf_heartbeat_reader_b WITH INHERIT TRUE, SET FALSE;

GRANT USAGE ON SCHEMA ftf_release TO ftf_heartbeat_read;
GRANT SELECT (singleton, refresh_status) ON ftf_release.state TO ftf_heartbeat_read;
CREATE POLICY ftf_heartbeat_reader ON ftf_release.state FOR SELECT TO ftf_heartbeat_read USING (singleton);
COMMIT;
