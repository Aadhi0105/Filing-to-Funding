import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

from pipelines import hosted_heartbeat, refresh_dataset


class HostedHeartbeatTests(unittest.TestCase):
    def test_boundary_measures_last_success_even_after_failure(self):
        now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
        for offset, event in ((0, "source_heartbeat_current"), (1, "source_heartbeat_overdue")):
            with self.subTest(offset=offset), redirect_stdout(io.StringIO()) as captured:
                last_success = now - refresh_dataset.CHECK_LIMIT - timedelta(seconds=offset)
                attempt = {
                    "result": "failed",
                    "started_at": (now - timedelta(minutes=1)).isoformat(),
                    "last_success_at": last_success.isoformat(),
                }
                hosted_heartbeat.report(attempt, now)
                self.assertEqual(json.loads(captured.getvalue())["event"], event)

    def test_missing_heartbeat_is_reported_separately(self):
        with redirect_stdout(io.StringIO()) as captured:
            hosted_heartbeat.report(None, datetime(2026, 11, 24, 12, tzinfo=timezone.utc))
        self.assertEqual(json.loads(captured.getvalue())["event"], "source_heartbeat_unavailable")
