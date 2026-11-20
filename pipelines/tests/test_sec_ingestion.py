"""Offline coverage for historical SEC submissions captures and the shared access budget."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipelines import backfill_sec, publish_dataset, qualify_sec, sec_http


class SubmissionsHistoryTests(unittest.TestCase):
    issuer = backfill_sec.ISSUERS[0]
    cik = issuer[0]
    root_url = backfill_sec.endpoint(cik, "sec_submissions")
    facts_url = backfill_sec.endpoint(cik, "sec_company_facts")
    history_name = f"CIK{cik}-submissions-003.json"
    history_url = f"{backfill_sec.SEC_API}/submissions/{history_name}"
    first = ("0000049826-21-000028", "10-Q", "2021-03-31", "2021-05-06",
             "2021-05-06T18:00:00Z", "itw-20210331.htm")
    second = ("0000049826-21-000059", "10-Q", "2021-06-30", "2021-08-05",
              "2021-08-05T20:12:40Z", "itw-20210630.htm")

    @staticmethod
    def columns(*rows):
        return {name: [row[position] for row in rows]
                for position, name in enumerate(backfill_sec.FILING_COLUMNS)}

    def setUp(self):
        self.documents = {
            self.root_url: {"cik": self.cik, "fiscalYearEnd": "1231", "filings": {
                "recent": self.columns(self.first),
                "files": [
                    {"name": f"CIK{self.cik}-submissions-002.json", "filingFrom": "2010-01-01", "filingTo": "2019-12-31"},
                    {"name": self.history_name, "filingFrom": "2021-05-06", "filingTo": "2021-08-05"},
                ],
            }},
            self.history_url: self.columns(self.first, self.second),
            self.facts_url: {"cik": int(self.cik), "facts": {"us-gaap": {}}},
        }
        self.sources = [
            {"cik": self.cik, "source_kind": kind, "source_url": url}
            for kind, url in (("sec_submissions", self.root_url), ("sec_company_facts", self.facts_url),
                              (backfill_sec.HISTORY_KIND, self.history_url))
        ]
        self.recent = self.documents[self.root_url]["filings"]["recent"]

    def build(self, sources=None):
        with patch.object(backfill_sec, "ISSUERS", (self.issuer,)):
            with patch.object(backfill_sec, "read_archive", side_effect=lambda source: self.documents[source["source_url"]]):
                return backfill_sec.build_batch(self.sources if sources is None else sources)[0]

    def test_history_contributes_rows_and_equal_duplicates_keep_recent_source(self):
        self.documents[self.history_url]["acceptanceDateTime"][0] = "2021-05-06T14:00:00-04:00"
        batch = self.build()
        self.assertEqual([filing["accession"] for filing in batch["filings"]], [self.first[0], self.second[0]])
        self.assertEqual([filing["metadata_source_url"] for filing in batch["filings"]], [self.root_url, self.history_url])
        self.assertEqual(len(batch["sources"]), 3)

    def test_history_fills_missing_acceptance_and_retains_the_cited_archive(self):
        self.recent["acceptanceDateTime"][0] = ""
        filing = self.build()["filings"][0]
        self.assertEqual(filing["accepted_at"], "2021-05-06T18:00:00+00:00")
        self.assertEqual(filing["metadata_source_url"], self.history_url)

    def test_conflicting_duplicate_fails_even_if_one_row_is_outside_the_report_window(self):
        self.documents[self.history_url]["reportDate"][0] = "2019-12-31"
        with self.assertRaisesRegex(ValueError, f"Conflicting EDGAR submissions metadata for {self.first[0]}"):
            self.build()

    def test_conflicting_acceptance_is_not_resolved_by_source_order(self):
        self.documents[self.history_url]["acceptanceDateTime"][0] = "2021-05-06T18:00:01Z"
        with self.assertRaisesRegex(ValueError, "Conflicting EDGAR submissions metadata"):
            self.build()

    def test_required_shard_and_valid_column_arrays_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "Missing required EDGAR source capture"):
            self.build(self.sources[:-1])
        self.documents[self.history_url]["primaryDocument"].pop()
        with self.assertRaisesRegex(ValueError, "zip"):
            self.build()

    def test_download_follows_only_overlapping_shards_and_archives_their_identity(self):
        def response(url, contact, limit):
            return json.dumps(self.documents[url]).encode(), "2026-11-20T00:00:00Z"

        def capture(cik, kind, url, timestamp, content):
            return {"cik": cik, "source_kind": kind, "source_url": url}

        with (patch.object(backfill_sec, "ISSUERS", (self.issuer,)),
              patch.object(backfill_sec, "sec_contact", return_value="test@example.com"),
              patch.object(backfill_sec, "download_edgar", side_effect=response) as download,
              patch.object(backfill_sec, "capture", side_effect=capture)):
            sources = backfill_sec.download_capture()
        self.assertCountEqual(sources, self.sources)
        self.assertEqual([call.args[0] for call in download.call_args_list],
                         [self.root_url, self.history_url, self.facts_url])

    def test_unsafe_shard_name_is_rejected(self):
        self.documents[self.root_url]["filings"]["files"][1]["name"] = "../foreign.json"
        with self.assertRaisesRegex(ValueError, "Invalid EDGAR historical submissions filename"):
            self.build()

    def test_independent_shard_watermarks_and_changed_root_allow_repacking(self):
        early = {"retrieved_at": "2026-11-20T00:00:00Z", "sha256": "a" * 64}
        later = {"retrieved_at": "2026-11-20T01:00:00Z", "sha256": "b" * 64}
        root, _, shard = self.sources
        second_shard = {**shard, "source_url": self.history_url.replace("003.json", "004.json")}
        def watermarks(*sources):
            return publish_dataset.capture_identity({"sec": json.dumps(sources).encode()})[1]

        saved = watermarks({**root, **early}, {**shard, **early}, {**second_shard, **early})
        self.assertEqual(len(saved), 3)
        with self.assertRaisesRegex(ValueError, "Candidate source capture is missing or older"):
            publish_dataset.require_current_sources(saved, watermarks({**root, **early}))
        publish_dataset.require_current_sources(saved, watermarks({**root, **later}))


class SecRequestBudgetTests(unittest.TestCase):
    data_url = "https://data.sec.gov/submissions/CIK0000049826.json"
    archive_url = "https://www.sec.gov/Archives/edgar/data/49826/test.htm"

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.now = 1000.0
        self.starts = []
        for mocked in (
            patch.object(sec_http, "REQUEST_BUDGET", Path(directory.name) / "budget.lock"),
            patch.object(sec_http.time, "time", side_effect=lambda: self.now),
            patch.object(sec_http.time, "sleep", side_effect=self.sleep),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)

    def sleep(self, seconds):
        self.now += seconds

    def transport(self, responses):
        stream = iter(responses)

        def attempt(url, contact, limit):
            self.starts.append((url, self.now))
            return next(stream)

        return patch.object(sec_http, "curl_attempt", side_effect=attempt)

    def test_retry_after_and_budget_are_shared_by_both_capture_steps(self):
        with self.transport([("503", 22, None, "3"), ("200", 0, b"source", ""), ("200", 0, b"filing", "")]):
            self.assertEqual(backfill_sec.download_edgar(self.data_url, "test@example.com", 100)[0], b"source")
            self.assertEqual(qualify_sec.download_edgar(self.archive_url, "test@example.com", 100)[0], b"filing")
        self.assertEqual(self.starts, [(self.data_url, 1000), (self.data_url, 1003), (self.archive_url, 1003.5)])

    def test_transport_failure_retries_once_and_then_stops(self):
        with self.transport([("000", 28, None, ""), ("000", 28, None, "")]):
            with self.assertRaisesRegex(sec_http.EdgarDownloadError, "unavailable"):
                backfill_sec.download_edgar(self.data_url, "test@example.com", 100)
        self.assertEqual(self.starts, [(self.data_url, 1000), (self.data_url, 1002)])

    def test_rate_limit_pauses_both_capture_steps_until_deadline(self):
        with self.transport([("429", 22, None, "660"), ("200", 0, b"source", "")]):
            with self.assertRaisesRegex(sec_http.EdgarDownloadError, "HTTP 429"):
                backfill_sec.download_edgar(self.data_url, "test@example.com", 100)
            with self.assertRaisesRegex(ValueError, "SEC requests paused locally"):
                qualify_sec.download_edgar(self.archive_url, "test@example.com", 100)
            self.now += 660
            self.assertEqual(qualify_sec.download_edgar(self.archive_url, "test@example.com", 100)[0], b"source")
        self.assertEqual(self.starts, [(self.data_url, 1000), (self.archive_url, 1660)])

    def test_access_denial_is_not_retried_and_unofficial_url_is_rejected(self):
        with self.transport([("403", 22, None, "")]):
            with self.assertRaisesRegex(sec_http.EdgarDownloadError, "HTTP 403"):
                backfill_sec.download_edgar(self.data_url, "test@example.com", 100)
            with self.assertRaisesRegex(ValueError, "official SEC source URL"):
                qualify_sec.download_edgar("https://data.sec.gov.example.com/submissions/detail", "test@example.com", 100)
        self.assertEqual(self.starts, [(self.data_url, 1000)])

    def test_retry_after_http_date_uses_utc_and_past_deadlines_are_ignored(self):
        self.assertEqual(sec_http.retry_after_seconds("Thu, 01 Jan 1970 00:16:44 GMT"), 4)
        self.assertEqual(sec_http.retry_after_seconds("Thu, 01 Jan 1970 00:16:00 GMT"), 0)


if __name__ == "__main__":
    unittest.main()
