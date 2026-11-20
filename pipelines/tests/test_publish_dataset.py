"""Regression tests for the local publication boundary."""

import fcntl
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipelines import publish_dataset as datasets


class LocalPublicationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.catalog = root / "datasets"
        self.catalog_path = self.catalog / "catalog.json"
        self.manifests = {kind: root / name for kind, (_, name) in datasets.IMPORTS.items()}
        self.write_inputs("2026-11-20T12:00:00+00:00")
        builder = patch.object(datasets, "build_snapshot", side_effect=self.build_snapshot)
        self.builder = builder.start()
        self.addCleanup(builder.stop)

    def write_inputs(self, treasury_timestamp, treasury_hash="a" * 64):
        capture = {"retrieved_at": "2026-11-20T11:00:00+00:00", "sha256": "a" * 64}
        self.manifests["sec"].write_text(json.dumps([
            {**capture, "cik": "0000049826", "source_kind": "sec_submissions"},
        ]))
        self.manifests["statements"].write_text(
            json.dumps({**capture, "accession": "0000049826-26-000001"}) + "\n"
        )
        self.manifests["treasury"].write_text(json.dumps([
            {"year": 2026, "retrieved_at": treasury_timestamp, "sha256": treasury_hash},
        ]))

    @staticmethod
    def build_snapshot(stage, captures):
        for kind, (_, filename) in datasets.IMPORTS.items():
            (stage / filename).write_bytes(captures[kind])
        (stage / "snapshot.dump").write_bytes(b"test archive")
        return {"filings": 1}

    def publish(self):
        return datasets.publish(self.catalog, self.manifests)

    def test_versions_are_retained_and_retries_are_idempotent(self):
        first_status, first = self.publish()
        self.assertEqual(first_status, "published")
        old_catalog = self.catalog_path.read_bytes()
        self.assertEqual(self.publish(), ("already_active", first))
        self.assertEqual(self.catalog_path.read_bytes(), old_catalog)
        self.write_inputs("2026-11-20T13:00:00+00:00")
        self.assertEqual(self.publish()[0], "published")
        catalog = datasets.read_catalog(self.catalog)
        self.assertEqual(catalog["active_version"], "v0002")
        self.assertEqual([entry["version"] for entry in catalog["versions"]], ["v0001", "v0002"])
        datasets.snapshot_details(self.catalog, first["snapshot_id"])
        self.assertEqual(self.builder.call_count, 2)

    def test_late_or_conflicting_refresh_cannot_replace_the_active_version(self):
        self.publish()
        before = self.catalog_path.read_bytes()
        self.write_inputs("2026-11-20T06:00:00-05:00")
        with self.assertRaisesRegex(ValueError, "missing or older for treasury:2026"):
            self.publish()
        self.write_inputs("2026-11-20T07:00:00-05:00", treasury_hash="b" * 64)
        with self.assertRaisesRegex(ValueError, "Conflicting source captures"):
            self.publish()
        self.assertEqual(self.catalog_path.read_bytes(), before)
        self.builder.assert_called_once()

    def test_failed_or_interrupted_candidate_leaves_catalog_intact(self):
        self.publish()
        before = self.catalog_path.read_bytes()
        self.write_inputs("2026-11-20T13:00:00+00:00")
        for error in (ValueError("candidate failed validation"), KeyboardInterrupt()):
            with self.subTest(error=type(error)):
                self.builder.side_effect = error
                with self.assertRaises(type(error)):
                    self.publish()
                self.assertEqual(self.catalog_path.read_bytes(), before)
                self.assertEqual(len(list((self.catalog / "snapshots").iterdir())), 1)

    def test_retry_reuses_a_validated_archive_after_interrupted_catalog_write(self):
        self.publish()
        before = self.catalog_path.read_bytes()
        self.write_inputs("2026-11-20T13:00:00+00:00")
        write_json = datasets.write_json

        def interrupt_catalog_write(path, document):
            if path == self.catalog_path:
                raise KeyboardInterrupt
            write_json(path, document)

        with patch.object(datasets, "write_json", side_effect=interrupt_catalog_write):
            with self.assertRaises(KeyboardInterrupt):
                self.publish()
        self.assertEqual(self.catalog_path.read_bytes(), before)
        status, record = self.publish()
        self.assertEqual((status, record["version"]), ("published", "v0002"))
        self.assertEqual(self.builder.call_count, 2)

    def test_overlapping_refresh_fails_before_building_candidate(self):
        self.publish()
        before = self.catalog_path.read_bytes()
        with (self.catalog / "publish.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "already running"):
                self.publish()
        self.assertEqual(self.catalog_path.read_bytes(), before)
        self.builder.assert_called_once()

    def test_restore_rejects_a_corrupted_archive_before_creating_database(self):
        _, version = self.publish()
        archive = self.catalog / "snapshots" / version["snapshot_id"] / "snapshot.dump"
        archive.write_bytes(b"damaged")
        with patch.object(datasets, "run") as run:
            with self.assertRaisesRegex(ValueError, "recorded checksum"):
                datasets.restore(self.catalog, "v0001", "ftf_test_restore")
        run.assert_not_called()

    def test_restore_rejects_a_changed_source_manifest_before_creating_database(self):
        _, version = self.publish()
        manifest = self.catalog / "snapshots" / version["snapshot_id"] / "treasury.json"
        manifest.write_text("[]")
        with patch.object(datasets, "run") as run:
            with self.assertRaisesRegex(ValueError, "recorded inputs"):
                datasets.restore(self.catalog, "v0001", "ftf_test_restore")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
