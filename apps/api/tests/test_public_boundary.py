"""Defensive regression tests for the anonymous API boundary."""

import asyncio
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from apps.api import public_boundary
from apps.api.main import Context, app, selection
from apps.api.public_boundary import MAX_BODY_BYTES, MAX_QUERY_BYTES, PublicBoundary, csv_cell


async def probe(scope, receive, send):
    request = Request(scope, receive)
    response = JSONResponse({"body_bytes": len(await request.body())})
    await response(scope, receive, send)


class RequestLimits(unittest.IsolatedAsyncioTestCase):
    def client(self, wrapped):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://testserver")

    async def test_request_limits_cover_declared_and_streamed_body_lengths(self):
        async def chunks():
            yield b" " * (MAX_BODY_BYTES // 2)
            yield b" " * (MAX_BODY_BYTES // 2 + 1)

        async with self.client(PublicBoundary(probe)) as client:
            for payload in (b" " * (MAX_BODY_BYTES + 1), chunks()):
                response = await client.post("/api/v1/funding/scenario", content=payload,
                                             headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, 413)
                self.assertEqual(response.headers["cache-control"], "no-store")
            response = await client.post("/api/v1/funding/scenario", json={})
            self.assertEqual(response.json(), {"body_bytes": 2})

    async def test_due_limits_reject_urls_and_unexpected_media_before_app(self):
        async with self.client(PublicBoundary(probe)) as client:
            response = await client.get("/api/v1/companies?q=" + "a" * MAX_QUERY_BYTES)
            self.assertEqual(response.status_code, 414)
            response = await client.post("/api/v1/funding/scenario", content="example",
                                         headers={"Content-Type": "text/plain"})
            self.assertEqual(response.status_code, 415)
            response = await client.post("/api/v1/funding/scenario", json={},
                                         headers={"Content-Encoding": "gzip"})
            self.assertEqual(response.status_code, 415)

    async def test_body_deadline_releases_concurrency_slot(self):
        async def slow_body():
            await asyncio.sleep(30)
            yield b"{}"

        async with self.client(PublicBoundary(probe, concurrent=1)) as client:
            with patch.object(public_boundary, "BODY_TIMEOUT_SECONDS", 0.05):
                response = await client.post("/api/v1/funding/scenario", content=slow_body(),
                                             headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 408)
            self.assertEqual((await client.get("/api/v1/companies")).status_code, 200)

    async def test_rate_limit_refills_and_is_independent_of_forwarded_headers(self):
        clock = [0.0]
        async with self.client(PublicBoundary(probe, rate=2, burst=1, clock=lambda: clock[0])) as client:
            self.assertEqual((await client.get("/api/v1/companies")).status_code, 200)
            response = await client.get("/api/v1/companies", headers={"X-Forwarded-For": "192.0.2.10"})
            self.assertEqual((response.status_code, response.headers["retry-after"]), (429, "1"))
            clock[0] += 0.5
            self.assertEqual((await client.get("/api/v1/companies")).status_code, 200)

    async def test_in_flight_limit_releases_slot_on_response(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def paused(scope, receive, send):
            started.set()
            await release.wait()
            await probe(scope, receive, send)

        async with self.client(PublicBoundary(paused, concurrent=1)) as client:
            first = asyncio.create_task(client.get("/api/v1/companies"))
            try:
                await asyncio.wait_for(started.wait(), 2)
                response = await client.get("/api/v1/companies")
                self.assertEqual((response.status_code, response.headers["retry-after"]), (429, "1"))
            finally:
                release.set()
                self.assertEqual((await first).status_code, 200)
            response = await client.get("/api/v1/companies")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")


class PublicSurface(unittest.TestCase):
    def test_validation_omits_submitted_values_and_unknown_field_names(self):
        stub_context = Context(dataset_version="v0004", methodology_version="reviewed", mode="latest",
                               filed_by=None, filing_cutoff=date(2026, 11, 19))
        app.dependency_overrides[selection] = lambda: (SimpleNamespace(), stub_context)
        self.addCleanup(app.dependency_overrides.pop, selection)
        with TestClient(app) as client:
            response = client.post("/api/v1/funding/scenario", json={
                "principal_usd": ["sample-private-value"], "repricing_share": "0.25", "shock_bps": "100",
                "horizon_years": "1", "sample-private-field": "value",
            })
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"][0]["loc"], ["body", "principal_usd"])
            self.assertNotIn("sample-private", response.text)
            denied = client.post("/api/v1/refresh", json={})
            self.assertEqual(denied.status_code, 404)

    def test_export_protects_text_and_preserves_signed_values(self):
        for value in ("=1+1", "  +example", "@example", "\ttext", "\ntext", "＝example"):
            with self.subTest(value=value):
                self.assertEqual(csv_cell(value), "'" + value)
        for value in ("-45.10", "+72", "2026-11-19", "ordinary text", None):
            with self.subTest(value=value):
                self.assertEqual(csv_cell(value), value)
