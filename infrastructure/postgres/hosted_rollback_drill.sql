BEGIN;
CREATE SCHEMA IF NOT EXISTS ftf_release_drill;
CREATE TABLE IF NOT EXISTS ftf_release_drill.state (LIKE ftf_release.state INCLUDING ALL);
INSERT INTO ftf_release_drill.state (singleton, catalog, snapshots, refresh_status)
SELECT singleton, catalog, snapshots, refresh_status FROM ftf_release.state WHERE singleton
ON CONFLICT (singleton) DO NOTHING;
REVOKE ALL ON SCHEMA ftf_release_drill FROM PUBLIC;
REVOKE ALL ON TABLE ftf_release_drill.state FROM PUBLIC, ftf_phase2_reader;
GRANT USAGE ON SCHEMA ftf_release_drill TO ftf_phase2_reader;
GRANT SELECT ON TABLE ftf_release_drill.state TO ftf_phase2_reader;
ALTER TABLE ftf_release_drill.state ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ftf_drill_reader ON ftf_release_drill.state;
CREATE POLICY ftf_drill_reader ON ftf_release_drill.state FOR SELECT TO ftf_phase2_reader USING (singleton);
COMMIT;
