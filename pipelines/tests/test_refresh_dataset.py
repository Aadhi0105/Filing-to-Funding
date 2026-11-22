"""Exercise the refresh state, pre-publication readiness, and recovery boundaries."""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from pipelines import publish_dataset as publication
from pipelines import refresh_dataset as operations


class RefreshOperationsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.catalog = self.root / "datasets"
        self.manifests = self.root / "inputs"
        self.manifests.mkdir()
        self.paths = {name: self.manifests / filename for name, (_, filename) in publication.IMPORTS.items()}
        self.builder = self.enterContext(patch.object(publication, "build_snapshot", side_effect=self.build))
        self.enterContext(patch.object(publication, "methodology", return_value={}))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.write_inputs("2026-11-20T11:00:00+00:00")
        publication.publish(self.catalog, self.paths)

    def write_inputs(self, treasury_time):
        capture = {"retrieved_at": "2026-11-20T11:00:00+00:00", "sha256": "a" * 64}
        self.paths["sec"].write_text(json.dumps([{**capture, "cik": "0000049826", "source_kind": "sec_submissions"}]))
        self.paths["statements"].write_text(json.dumps({**capture, "accession": "0000049826-26-000001"}) + "\n")
        self.paths["treasury"].write_text(json.dumps([{**capture, "year": 2026, "retrieved_at": treasury_time}]))

    @staticmethod
    def build(stage, captures):
        for kind, (_, filename) in publication.IMPORTS.items():
            (stage / filename).write_bytes(captures[kind])
        (stage / "snapshot.dump").write_bytes(b"test only")
        return {"filings": 1}

    def test_readiness_failure_preserves_serving_version_and_retry_can_publish(self):
        before = publication.read_catalog(self.catalog)
        self.write_inputs("2026-11-20T12:00:00+00:00")
        with patch("apps.api.prepare_local.prepare_record", side_effect=ValueError("PRIVATE")):
            with self.assertRaises(ValueError):
                operations.refresh(self.catalog, self.manifests)
        self.assertEqual(publication.read_catalog(self.catalog), before)
        status = operations.read_status(self.catalog)["publication"]
        self.assertEqual(status["result"], "failed")
        self.assertNotIn("PRIVATE", (self.catalog / operations.STATUS).read_text())
        with patch("apps.api.prepare_local.prepare_record") as prepare:
            result = operations.refresh(self.catalog, self.manifests)
        prepare.assert_called_once()
        self.assertEqual(result["active_version"], "v0002")
        self.assertEqual(publication.read_catalog(self.catalog)["active_version"], "v0002")
        self.assertEqual(self.builder.call_count, 2)

    def test_backup_is_independent_and_rejects_corrupt_copies(self):
        destination = self.root / "backup"
        record = publication.catalog_entry(publication.read_catalog(self.catalog))
        self.assertEqual(operations.backup(self.catalog, destination)["versions"], 1)
        self.assertEqual(operations.verify_backup(destination)["active_version"], "v0001")
        with self.assertRaisesRegex(ValueError, "new backup directory"):
            operations.backup(self.catalog, destination)
        (destination / "snapshots" / record["snapshot_id"] / "snapshot.dump").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "recorded checksum"):
            operations.verify_backup(destination)
        publication.snapshot_details(self.catalog, record["snapshot_id"])

    def test_rollback_keeps_history_and_the_newest_source_watermark(self):
        self.write_inputs("2026-11-20T13:00:00+00:00")
        publication.publish(self.catalog, self.paths)
        with patch("apps.api.prepare_local.prepare_record") as prepare:
            self.assertEqual(operations.activate(self.catalog, "v0001")["previous_version"], "v0002")
        prepare.assert_called_once()
        catalog = publication.read_catalog(self.catalog)
        self.assertEqual([row["version"] for row in catalog["versions"]], ["v0001", "v0002"])
        self.assertEqual(catalog["active_version"], "v0001")
        self.write_inputs("2026-11-20T12:30:00+00:00")
        with self.assertRaisesRegex(ValueError, "missing or older"):
            publication.publish(self.catalog, self.paths)

    def test_source_check_stages_new_coverage_and_records_later_failure(self):
        before = publication.read_catalog(self.catalog)
        with patch.object(operations, "check_sec", return_value=([{"source": "sec"}], 0)):
            with patch.object(operations, "check_treasury", return_value=([{"source": "treasury"}], date(2026, 11, 20))):
                result = operations.check_sources(self.catalog)
        self.assertEqual(result["result"], "review_required")
        self.assertTrue((self.catalog / "latest-source-check.json").exists())
        with patch.object(operations, "check_sec", side_effect=OSError("PRIVATE")):
            with self.assertRaises(OSError):
                operations.check_sources(self.catalog)
        self.assertEqual(publication.read_catalog(self.catalog), before)
        view = operations.health(self.catalog, date(2026, 11, 19), date(2026, 11, 19))
        self.assertEqual(view["source_status"], "failed")
        self.assertEqual(view["source_success_at"].isoformat(), result["last_success_at"])

    def test_health_keeps_coverage_age_separate_from_the_source_heartbeat(self):
        timestamp = datetime(2026, 11, 25, 16, tzinfo=timezone.utc)
        recent = (timestamp - timedelta(hours=1)).isoformat()
        old = (timestamp - timedelta(hours=37)).isoformat()
        publication.write_json(self.catalog / operations.STATUS, {
            "sources": {"result": "review_required", "started_at": old, "last_success_at": old},
            "publication": {"result": "running", "started_at": recent},
        })
        view = operations.health(self.catalog, date(2026, 11, 19), date(2026, 11, 24), timestamp=timestamp)
        self.assertEqual(view["source_status"], "review_required")
        self.assertTrue(view["source_check_overdue"])
        self.assertTrue(view["filing_coverage_stale"])
        self.assertFalse(view["treasury_coverage_stale"])
        self.assertEqual(view["publication_status"], "failed")
