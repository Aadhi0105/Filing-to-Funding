"""Release checks for the six-company research views."""

import os
import unittest

if os.environ.get("FILING_TEST_LOCAL_API") == "1":
    import httpx


@unittest.skipUnless(os.environ.get("FILING_TEST_LOCAL_API") == "1", "Start the prepared local API to run integration checks")
class ResearchAPIIntegration(unittest.TestCase):
    def setUp(self):
        origin = os.environ.get("FILING_API_ORIGIN", "http://127.0.0.1:8000")
        self.client = httpx.Client(base_url=f"{origin}/api/v1", timeout=20)
        self.addCleanup(self.client.close)

    def get(self, route, **params):
        response = self.client.get(route, params=params)
        response.raise_for_status()
        return response.json()

    def test_overview_preserves_archive_membership_and_temporal_notes(self):
        current = self.get("/overview")
        rows = {row["company"]["ticker"]: row for row in current["rows"]}
        self.assertEqual(set(rows), {"AOS", "DOV", "IEX", "ITW", "LECO", "ROK"})
        self.assertEqual(next(metric["value"] for metric in rows["AOS"]["metrics"]
                              if metric["metric"] == "free_cash_flow"), "162900000")
        archived = self.get("/overview", mode="platform_snapshot", dataset_version="v0003")
        self.assertEqual({row["company"]["ticker"] for row in archived["rows"]}, {"DOV", "ITW", "ROK"})
        past = self.get("/overview", mode="filed_by", filed_by="2026-10-28")
        aos = next(row for row in past["rows"] if row["company"]["ticker"] == "AOS")
        self.assertEqual(aos["period"]["period_end"], "2026-06-30")
        self.assertIsNone(aos["note"])

    def test_peers_withhold_scope_and_window_mismatches(self):
        quarter = self.get("/peers", period_end="2026-09-30")
        rows = {row["company"]["ticker"]: row for row in quarter["rows"]}
        self.assertEqual(rows["AOS"]["metric"]["value"], "162900000")
        self.assertEqual(rows["DOV"]["status"], "different_reporting_basis")
        self.assertIsNone(rows["DOV"]["metric"])
        self.assertEqual(rows["DOV"]["reporting_basis"], "continuing_operations")
        self.assertEqual(rows["DOV"]["window_start"], "2026-07-01")
        self.assertIsNone(rows["ROK"]["metric"])
        annual = self.get("/peers", duration="annual")
        self.assertEqual(annual["period_end"], "2025-12-31")
        rows = {row["company"]["ticker"]: row for row in annual["rows"]}
        self.assertEqual(rows["IEX"]["metric"]["value"], "616800000")
        self.assertEqual(rows["ROK"]["status"], "different_period_end")

    def test_filing_metadata_is_distinct_from_qualified_facts(self):
        route = "/companies/0000091142/filings"
        current = self.get(route)
        self.assertEqual((current["total"], current["with_qualified_facts"]), (27, 4))
        self.assertEqual(current["filings"][0]["filed_on"], "2026-10-29")
        past = self.get(route, mode="filed_by", filed_by="2026-10-28")
        self.assertEqual(past["total"], 26)
        self.assertTrue(all(row["filed_on"] <= "2026-10-28" for row in past["filings"]))
        third_page = self.get(route, page=3)
        self.assertEqual(len(third_page["filings"]), 7)
        self.assertTrue(all(row["qualified_facts"] == 0 for row in third_page["filings"]))

    def test_funding_curve_and_signed_interest(self):
        weekend = self.get("/funding/curve", curve_date="2026-11-15")["curve"]
        self.assertEqual((weekend["observation_date"], weekend["status"]), ("2026-11-13", "carried_forward"))
        self.assertEqual(weekend["vintage_status"], "historical_vintage_unverified")
        args = {"principal_usd": "2000000000", "repricing_share": "0.25", "shock_bps": "-100",
                "horizon_years": "1", "spread_bps": "125", "curve_date": "2026-11-15"}
        response = self.client.post("/funding/scenario", json=args)
        response.raise_for_status()
        result = response.json()
        self.assertEqual(result["incremental_interest_usd"], "-5000000")
        self.assertEqual([point["shock_bps"] for point in result["sensitivity"]], ["-150", "-100", "-50"])
        self.assertEqual(result["curve"]["observation_date"], weekend["observation_date"])
        self.assertEqual(result["reference_maturity"], "five_year")
        self.assertEqual(result["illustrative_coupon"]["spread_bps"], "125")
        future_date = {**args, "spread_bps": None, "curve_date": "2026-11-20"}
        self.assertEqual(self.client.post("/funding/scenario", json=future_date).status_code, 422)
        self.assertEqual(self.client.post("/funding/scenario", json={**args, "repricing_share": "1.1"}).status_code, 422)
        self.assertEqual(self.client.get("/funding/curve", params={"curve_date": "2026-11-20"}).status_code, 422)


    def test_all_six_overview_metrics_resolve_to_explorer_evidence(self):
        overview = self.get("/overview", mode="filed_by", filed_by="2026-11-19")
        self.assertEqual(overview["context"]["cutoff_timezone"], "America/New_York")
        for summary in overview["rows"]:
            period = summary["period"]
            cik = summary["company"]["cik"]
            with self.subTest(ticker=summary["company"]["ticker"]):
                analysis = self.get(f"/companies/{cik}/analysis", fiscal_year=period["fiscal_year"],
                                    quarter=period["quarter"], mode="filed_by", filed_by="2026-11-19")
                self.assertEqual(analysis["context"], overview["context"])
                self.assertEqual(analysis["period"], period)
                metrics = {metric["metric"]: metric for metric in analysis["metrics"]}
                sources = {fact["fact_id"]: fact for fact in analysis["sources"]}
                for metric in summary["metrics"]:
                    self.assertEqual(metric, metrics[metric["metric"]])
                    if metric["value"] is None:
                        self.assertNotEqual(metric["status"], "available")
                        continue
                    self.assertTrue(metric["fact_ids"])
                    accessions = set()
                    for fact_id in metric["fact_ids"]:
                        source = sources[fact_id]
                        self.assertLessEqual(source["filed_on"], "2026-11-19")
                        self.assertRegex(source["payload_sha256"], r"^[0-9a-f]{64}$")
                        accessions.add(source["accession"])
                    self.assertEqual(accessions, set(metric["source_accessions"]))

    def test_view_inputs_and_api_surface_are_bounded(self):
        requests = (
            ("/peers", {"duration": "monthly"}, 422),
            ("/peers", {"metric": "undefined"}, 422),
            ("/peers", {"period_end": "2026-11-20"}, 422),
            ("/companies/0000091142/filings", {"page": 10001}, 422),
            ("/companies/unavailable/filings", {}, 422),
            ("/overview", {"expected_dataset_version": "v0001"}, 409),
            ("/overview", {"mode": "platform_snapshot", "dataset_version": "v9999"}, 404),
            ("/funding/curve", {"curve_date": "2026-10-25", "mode": "filed_by", "filed_by": "2026-10-24"}, 422),
            ("/raw/source_fetches", {}, 404),
        )
        for path, parameters, status in requests:
            with self.subTest(path=path, parameters=parameters):
                self.assertEqual(self.client.get(path, params=parameters).status_code, status)
        oversized = {"principal_usd": "1" * 129, "repricing_share": "1", "shock_bps": "0", "horizon_years": "1"}
        self.assertEqual(self.client.post("/funding/scenario", json=oversized).status_code, 422)
        self.assertEqual(self.client.post("/overview", json={}).status_code, 405)

    def test_revision_evidence_enters_only_on_its_filing_date(self):
        route = "/companies/0000029905/analysis"
        args = {"fiscal_year": 2024, "quarter": 2, "mode": "filed_by"}
        prior = self.get(route, **args, filed_by="2025-07-23")
        self.assertFalse(any(row["relationship"] == "scope_change" for row in prior["revisions"]))
        later = self.get(route, **args, filed_by="2025-07-24")
        revised = next(row for row in later["revisions"]
                       if row["concept"] == "operating_cash_flow" and row["relationship"] == "scope_change")
        self.assertEqual((revised["prior_value"], revised["later_value"]), ("370255000", "295637000"))
        self.assertEqual((revised["prior_accession"], revised["later_accession"]),
                         ("0000029905-24-000035", "0000029905-25-000024"))
        self.assertEqual((revised["prior_basis"], revised["later_basis"]), ("consolidated", "continuing_operations"))
