"""Measure the reviewed API workload on an authorized Filing-to-Funding origin."""

import argparse
import asyncio
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from statistics import median
from time import perf_counter
from urllib.parse import urlsplit

import httpx

TARGET_MS = 2000
WARMUPS = 3
CONCURRENT = 2
ENDPOINTS = (
    ("Overview", "GET", "/overview", {}, None),
    ("Company Explorer", "GET", "/companies/0000049826/analysis", {"fiscal_year": 2026, "quarter": 2}, None),
    ("Peer Comparison", "GET", "/peers", {"duration": "annual"}, None),
    ("Filing History", "GET", "/companies/0000091142/filings", {"page": 1}, None),
    ("Treasury curve", "GET", "/funding/curve", {"curve_date": "2026-11-15"}, None),
    ("Funding scenario", "POST", "/funding/scenario", {}, {
        "principal_usd": "2000000000", "repricing_share": "0.25", "shock_bps": "100",
        "horizon_years": "1", "spread_bps": "125", "curve_date": "2026-11-15",
    }),
)


def origin_argument(value):
    try:
        origin = urlsplit(value)
        hostname, port = origin.hostname, origin.port
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid service origin.") from None
    local = hostname in {"localhost", "127.0.0.1", "::1"}
    if (not hostname or port == 0 or (origin.scheme != "https" and not (local and origin.scheme == "http"))
            or origin.username is not None or origin.path not in ("", "/") or origin.query or origin.fragment):
        raise argparse.ArgumentTypeError("Use an HTTPS service origin or an HTTP loopback origin without credentials.")
    return value.rstrip("/")


async def sample(client, endpoint, version, scheduled, semaphore):
    _, method, path, params, body = endpoint
    await asyncio.sleep(max(0, scheduled - perf_counter()))
    try:
        async with semaphore:
            started = perf_counter()
            response = await client.request(method, "/api/v1" + path,
                                            params={**params, "expected_dataset_version": version}, json=body)
            finished = perf_counter()
        if response.status_code != 200:
            return None, f"HTTP {response.status_code}"
        if response.json()["context"]["dataset_version"] != version:
            return None, "Unexpected dataset"
        return (finished - started) * 1000, None
    except httpx.RequestError as error:
        return None, type(error).__name__
    except (ValueError, KeyError, TypeError):
        return None, "Invalid response contract"


def summarize(results):
    samples = sorted(ms for ms, _ in results if ms is not None)
    errors = Counter(error for _, error in results if error)
    p95 = samples[math.ceil(0.95 * len(samples)) - 1] if samples else None
    return {
        "successful": len(samples), "errors": dict(errors),
        "median_ms": round(median(samples), 1) if samples else None,
        "p95_ms": round(p95, 1) if p95 is not None else None,
        "max_ms": round(samples[-1], 1) if samples else None,
        "passed": not errors and p95 is not None and p95 < TARGET_MS,
    }


async def benchmark(origin, version, requests, rate):
    results = {}
    semaphore = asyncio.Semaphore(CONCURRENT)
    async with httpx.AsyncClient(base_url=origin, timeout=10, trust_env=False) as client:
        # Use the same pacing for warm-ups and measured traffic.
        for endpoint in ENDPOINTS:
            start = perf_counter()
            warmups = await asyncio.gather(*(
                sample(client, endpoint, version, start + i / rate, semaphore) for i in range(WARMUPS)
            ))
            warm = summarize(warmups)
            if warm["errors"]:
                results[endpoint[0]] = {"warmup_errors": warm["errors"], "passed": False}
                break
            start = max(perf_counter(), start + WARMUPS / rate)
            measured = await asyncio.gather(*(
                sample(client, endpoint, version, start + i / rate, semaphore) for i in range(requests)
            ))
            results[endpoint[0]] = summarize(measured)
            await asyncio.sleep(max(0, start + requests / rate - perf_counter()))
    return {
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "origin": origin, "dataset_version": version, "requests_per_endpoint": requests,
        "warmups_per_endpoint": WARMUPS, "max_requests_per_second": rate, "max_in_flight": CONCURRENT,
        "target_p95_ms": TARGET_MS, "endpoints": results,
        "passed": len(results) == len(ENDPOINTS) and all(result["passed"] for result in results.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", type=origin_argument, required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--requests", type=int, default=30, metavar="20-100")
    parser.add_argument("--rate", type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    if not 20 <= args.requests <= 100:
        parser.error("--requests must be between 20 and 100 per endpoint")
    if not re.fullmatch(r"v[0-9]{4,8}", args.dataset_version):
        parser.error("--dataset-version must be a published version such as v0004")
    result = asyncio.run(benchmark(args.origin, args.dataset_version, args.requests, args.rate))
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
