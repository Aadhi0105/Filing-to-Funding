"""Integration checks against prepared local snapshots."""

import csv
import io
import os
import unittest

if os.environ.get("FILING_TEST_LOCAL_API") == "1":
    import httpx
    import psycopg
    from apps.api.dataset_access import catalog_datasets, reader


@unittest.skipUnless(os.environ.get("FILING_TEST_LOCAL_API") == "1", "Start the prepared local API to run integration checks")
class ExplorerAPIIntegration(unittest.TestCase):
    def setUp(self):
        self.client = httpx.Client(base_url=os.environ.get("FILING_API_ORIGIN", "http://127.0.0.1:8000"))
        self.addCleanup(self.client.close)

    def get(self, suffix, **params):
        response = self.client.get(f"/api/v1/{suffix}", params=params)
        response.raise_for_status()
        return response.json()

    def flow(self, body):
        return next(row for row in body["metrics"] if row["metric"] == "free_cash_flow")

    def test_catalog_and_response_contract(self):
        catalog = self.get("datasets")
        self.assertEqual(catalog["active_version"], "v0003")
        companies = self.get("companies")
        self.assertEqual({item["ticker"] for item in companies["companies"]}, {"DOV", "ITW", "ROK"})
        contract = self.client.get("/openapi.json").json()
        self.assertIn("text/csv", contract["paths"]["/api/v1/companies/{cik}/export.csv"]["get"]["responses"]["200"]["content"])
        self.assertEqual(self.client.post("/api/v1/companies").status_code, 405)

    def test_filing_cutoff_and_lineage(self):
        endpoint = "companies/0000049826/analysis"
        args = {"fiscal_year": 2026, "quarter": 2, "mode": "filed_by"}
        prior = self.get(endpoint, **args, filed_by="2026-08-05")
        result = self.get(endpoint, **args, filed_by="2026-08-06")
        self.assertIsNone(self.flow(prior)["value"])
        self.assertEqual(self.flow(result)["value"], "631000000")
        self.assertEqual(result["context"]["cutoff_timezone"], "America/New_York")
        sources = {fact["fact_id"]: fact for fact in result["sources"]}
        for fact_id in self.flow(result)["fact_ids"]:
            self.assertTrue(sources[fact_id]["filing_url"].startswith("https://www.sec.gov/Archives/edgar/data/"))
            self.assertLessEqual(sources[fact_id]["filed_on"], "2026-08-06")

    def test_archive_annual_feature_and_invalid_selections(self):
        suffix = "companies/0001024478/analysis"
        args = {"fiscal_year": 2026, "duration": "annual", "mode": "platform_snapshot"}
        archived = self.get(suffix, **args, dataset_version="v0002")
        active = self.get(suffix, **args, dataset_version="v0003")
        self.assertEqual(self.flow(archived)["status"], "unsupported_by_snapshot")
        self.assertEqual(self.flow(active)["value"], "1701000000")
        self.assertNotEqual(archived["context"]["methodology_version"], active["context"]["methodology_version"])
        self.assertEqual(self.client.get(f"/api/v1/{suffix}", params=args).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/companies", params={"expected_dataset_version": "v0002"}).status_code, 409)

    def test_export_matches_exact_values_and_context(self):
        args = {"fiscal_year": 2026, "quarter": 2, "mode": "filed_by", "filed_by": "2026-08-06", "expected_dataset_version": "v0003"}
        prefix = "companies/0000049826"
        analysis = self.get(f"{prefix}/analysis", **args)
        result = self.client.get(f"/api/v1/{prefix}/export.csv", params=args)
        result.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(result.text)))
        for row in rows:
            self.assertEqual(row["dataset_version"], analysis["context"]["dataset_version"])
            self.assertEqual(row["methodology_version"], analysis["context"]["methodology_version"])
        self.assertEqual([row["value"] for row in rows if row["section"] == "selected_period"],
                         [metric["value"] or "" for metric in analysis["metrics"]])
        self.assertEqual([row["value"] for row in rows if row["section"] == "free_cash_flow_history"],
                         [point["value"] or "" for point in analysis["series"]])

    def test_reader_role_cannot_write(self):
        _, snapshots = catalog_datasets()
        active = next(item for item in snapshots if item.version == "v0003")
        with reader(active) as connection:
            self.assertEqual(connection.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"], "on")
            self.assertFalse(connection.execute(
                "SELECT has_table_privilege(current_user, 'core.issuers', 'UPDATE') AS permitted"
            ).fetchone()["permitted"])
            with self.assertRaises(psycopg.Error):
                with connection.transaction():
                    connection.execute("UPDATE core.issuers SET legal_name = legal_name")
