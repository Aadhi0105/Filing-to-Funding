"""Backfill the three pilot issuers from a frozen EDGAR API capture."""

import argparse
import calendar
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from pipelines.load_pilot import ROOT, archive_payload, compose_psql

CUTOFF = date(2026, 11, 19)
SEC_API = "https://data.sec.gov"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
MANIFEST = ROOT / ".local/sec-history-2026-11-19.json"
MAX_BYTES = 24 * 1024 * 1024
ISSUERS = (
    ("0000049826", "ITW", "Illinois Tool Works Inc.", 12, 2021),
    ("0000029905", "DOV", "Dover Corporation", 12, 2021),
    ("0001024478", "ROK", "Rockwell Automation, Inc.", 9, 2022),
)
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}
# Candidate tags retained for review. A tag's presence does not qualify a metric.
CONCEPTS = {
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsDisposalGroupIncludingDiscontinuedOperations",
        "RestrictedCashAndCashEquivalentsAtCarryingValue", "RestrictedCashAndCashEquivalentsNoncurrent",
    ),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "debt": (
        "DebtCurrent", "ShortTermBorrowings", "LongTermDebtCurrent", "LongTermDebtNoncurrent",
        "LongTermDebt", "DebtLongtermAndShorttermCombinedAmount", "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        "FinanceLeaseLiability", "FinanceLeaseLiabilityCurrent", "FinanceLeaseLiabilityNoncurrent",
        "FinanceLeaseLiabilityCurrentAndNoncurrent",
    ),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "CashProvidedByUsedInOperatingActivitiesDiscontinuedOperations",
    ),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet", "Revenues",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss", "IncomeLossFromContinuingOperations"),
}
TAGS = {tag for group in CONCEPTS.values() for tag in group}


def periods(year_end, first_year):
    if year_end == 12:
        quarters = ((0, 3), (0, 6), (0, 9), (0, 12))
        start_month = 1
    else:
        quarters = ((-1, 12), (0, 3), (0, 6), (0, 9))
        start_month = 10
    result = {}
    for year in range(first_year - 1, CUTOFF.year + 1):
        year_start = date(year if year_end == 12 else year - 1, start_month, 1)
        start = year_start
        for quarter, (year_offset, month) in enumerate(quarters, 1):
            end_year = year + year_offset
            end = date(end_year, month, calendar.monthrange(end_year, month)[1])
            if end > CUTOFF:
                continue
            annual = quarter == 4
            result[end.isoformat()] = {
                "fiscal_year": year, "fiscal_quarter": None if annual else quarter,
                "starts_on": (year_start if annual else start).isoformat(), "ends_on": end.isoformat(),
                "form_type": "10-K" if annual else "10-Q",
                "window": "opening_input" if year < first_year else "coverage",
            }
            start = date.fromordinal(end.toordinal() + 1)
    return result


def endpoint(cik, source_kind):
    route = "submissions" if source_kind == "sec_submissions" else "api/xbrl/companyfacts"
    return f"{SEC_API}/{route}/CIK{cik}.json"


def utc_timestamp(value):
    if not value:
        return None
    timestamp = datetime.fromisoformat(value)
    if timestamp.utcoffset() is None:
        raise ValueError("SEC timestamp lacks an explicit UTC offset")
    return timestamp.astimezone(timezone.utc).isoformat()


def capture(cik, kind, url, retrieved_at, content):
    # Reject an HTML access block or partial response before adding it to the archive.
    json.loads(content)
    timestamp = utc_timestamp(retrieved_at)
    if not timestamp:
        raise ValueError(f"Missing download completion time for {url}")
    return {
        "cik": cik, "source_kind": kind, "source_url": url, "retrieved_at": timestamp,
        **archive_payload(content, "json"),
    }


def download_capture():
    contact = os.environ.get("SEC_CONTACT_EMAIL", "")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", contact):
        raise ValueError("Set SEC_CONTACT_EMAIL to an authorized project contact for EDGAR requests")
    archives = []
    for cik, *_ in ISSUERS:
        for kind in ("sec_submissions", "sec_company_facts"):
            url = endpoint(cik, kind)
            with NamedTemporaryFile() as response:
                request = subprocess.run([
                    "curl", "--disable", "--silent", "--show-error", "--fail",
                    "--retry", "2", "--retry-max-time", "50", "--max-time", "35",
                    "--max-filesize", str(MAX_BYTES),
                    "--user-agent", f"Filing-to-Funding {contact}", "--output", response.name,
                    "--write-out", "%{http_code}", url,
                ], capture_output=True, text=True)
                if request.returncode:
                    raise ValueError(f"EDGAR download failed for {url} (HTTP {request.stdout or 'unavailable'})")
                fetched = datetime.now(timezone.utc).isoformat()
                content = Path(response.name).read_bytes()
            archives.append(capture(cik, kind, url, fetched, content))
            time.sleep(0.5)
    return archives


def read_archive(source):
    digest = source["sha256"]
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid SHA-256 in the SEC capture")
    expected = f".local/source-cache/{digest}.json"
    if source["storage_key"] != expected or not utc_timestamp(source["retrieved_at"]):
        raise ValueError("Invalid storage location or retrieval time in the SEC capture")
    content = (ROOT / expected).read_bytes()
    if len(content) != source["byte_count"] or hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"SEC archive does not match its manifest: {expected}")
    return json.loads(content, parse_float=Decimal)


def filing_rows(cik, document, expected):
    recent = document["filings"]["recent"]
    first_end = min(expected)
    # A future capture may move these filings into an older shard. Fail explicitly if the main
    # response no longer proves coverage of the fixed window, instead of claiming missing filings.
    if any(first_end <= item["filingTo"] and item["filingFrom"] <= CUTOFF.isoformat()
           for item in document["filings"]["files"]):
        raise ValueError(f"{cik} has a historical submissions shard overlapping the backfill window")
    fields = ("accessionNumber", "form", "reportDate", "filingDate", "acceptanceDateTime", "primaryDocument")
    rows = {}
    for accession, form, end, filed, accepted, primary in zip(*(recent[field] for field in fields), strict=True):
        if form not in FORMS or date.fromisoformat(filed) > CUTOFF:
            continue
        if not end and filed >= first_end:
            raise ValueError(f"Report date missing for {accession}")
        if not first_end <= end <= max(expected):
            continue
        if end not in expected or expected[end]["form_type"] != form.removesuffix("/A"):
            raise ValueError(f"Unexpected fiscal period or form for {accession}")
        if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession) or accession in rows:
            raise ValueError(f"Invalid or duplicate SEC accession: {accession}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.html?", primary) or filed < end:
            raise ValueError(f"Unexpected filing document or date for {accession}")
        rows[accession] = {
            **expected[end], "accession": accession, "form_type": form, "filed_on": filed,
            "accepted_at": utc_timestamp(accepted), "primary_document": primary,
            "filing_url": f"{SEC_ARCHIVES}/{int(cik)}/{accession.replace('-', '')}/{primary}",
        }
    return rows


def financial_facts(document, filings, first_end):
    taxonomy = document["facts"]["us-gaap"]
    for tag in sorted(TAGS & taxonomy.keys()):
        for index, observation in enumerate(taxonomy[tag]["units"].get("USD", [])):
            accession = observation["accn"]
            filing = filings.get(accession)
            end = observation["end"]
            if not filing or not first_end <= end <= filing["ends_on"]:
                continue
            start = observation.get("start")
            date.fromisoformat(end)
            if start and date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError(f"Invalid financial interval for {accession} / {tag}")
            amount = observation["val"]
            if not isinstance(amount, (int, Decimal)) or isinstance(amount, bool) or not Decimal(amount).is_finite():
                raise ValueError(f"Invalid USD value for {accession} / {tag}")
            if observation["form"] != filing["form_type"] or observation["filed"] != filing["filed_on"]:
                raise ValueError(f"Company Facts metadata disagrees with Submissions for {accession} / {tag}")
            yield {
                "accession": accession, "concept": tag, "period_start": start, "period_end": end,
                "value": str(amount), "source_locator": f"/facts/us-gaap/{tag}/units/USD/{index}",
            }


def build_batch(sources):
    by_source = {(source["cik"], source["source_kind"]): source for source in sources}
    required = {(cik, kind) for cik, *_ in ISSUERS for kind in ("sec_submissions", "sec_company_facts")}
    if len(sources) != len(required) or by_source.keys() != required:
        raise ValueError("Expected one Submissions and one Company Facts capture for each pilot issuer")

    batch = []
    for cik, ticker, legal_name, year_end, first_year in ISSUERS:
        metadata = by_source[cik, "sec_submissions"]
        facts_source = by_source[cik, "sec_company_facts"]
        for source in (metadata, facts_source):
            if source["source_url"] != endpoint(cik, source["source_kind"]):
                raise ValueError(f"Unexpected EDGAR source URL for {ticker}")
        submissions, company_facts = read_archive(metadata), read_archive(facts_source)
        if str(submissions["cik"]).zfill(10) != cik or str(company_facts["cik"]).zfill(10) != cik:
            raise ValueError(f"EDGAR capture has the wrong CIK for {ticker}")
        if submissions["fiscalYearEnd"] != {12: "1231", 9: "0930"}[year_end]:
            raise ValueError(f"EDGAR's fiscal year-end changed for {ticker}")
        expected = periods(year_end, first_year)
        inventory = filing_rows(cik, submissions, expected)
        observations = list(financial_facts(company_facts, inventory, min(expected)))
        batch.append({
            "cik": cik, "ticker": ticker, "legal_name": legal_name,
            "sources": [metadata, facts_source], "periods": list(expected.values()),
            "filings": list(inventory.values()), "facts": observations,
        })
    return batch


def load_batch(batch, database):
    script = io.StringIO()
    script.write("BEGIN;\nCREATE TEMP TABLE edgar_input (document jsonb NOT NULL);\n")
    script.write("COPY edgar_input FROM STDIN WITH (FORMAT csv);\n")
    csv.writer(script, lineterminator="\n").writerows([json.dumps(record)] for record in batch)
    script.write("\\.\n")
    script.write((ROOT / "database/backfill_sec.sql").read_text())
    subprocess.run(
        [*compose_psql()[:-1], database, "-X", "-v", "ON_ERROR_STOP=1"],
        cwd=ROOT, input=script.getvalue(), text=True, check=True,
    )


def report_inventory(batch, output):
    fields = ("ticker", "cik", "window", "fiscal_year", "fiscal_period", "report_end", "status",
              "form_type", "accession", "filed_on", "accepted_at_utc", "filing_url", "candidate_fact_count")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for company in batch:
        by_period = defaultdict(list)
        fact_keys = defaultdict(set)
        for fact in company["facts"]:
            fact_keys[fact["accession"]].add((
                fact["concept"], fact["period_start"], fact["period_end"], Decimal(fact["value"]),
            ))
        for filing in company["filings"]:
            by_period[filing["ends_on"]].append(filing)
        for period in company["periods"]:
            filings = by_period[period["ends_on"]]
            if not any(filing["form_type"] == period["form_type"] for filing in filings):
                filings = [{**period, "accession": ""}, *filings]
            base_count = sum(filing["form_type"] == period["form_type"] and bool(filing["accession"])
                             for filing in filings)
            for filing in sorted(filings, key=lambda row: (row.get("filed_on", ""), row["accession"])):
                accession = filing["accession"]
                if not accession:
                    status = "missing_base_filing"
                elif filing["form_type"].endswith("/A"):
                    status = "amendment"
                else:
                    status = "base_filing" if base_count == 1 else "multiple_base_filings"
                writer.writerow({
                    "ticker": company["ticker"], "cik": company["cik"], "window": period["window"],
                    "fiscal_year": period["fiscal_year"],
                    "fiscal_period": f"Q{period['fiscal_quarter']}" if period["fiscal_quarter"] else "FY",
                    "report_end": period["ends_on"], "status": status, "form_type": filing["form_type"],
                    "accession": accession, "filed_on": filing.get("filed_on"),
                    "accepted_at_utc": filing.get("accepted_at"), "filing_url": filing.get("filing_url"),
                    "candidate_fact_count": len(fact_keys[accession]) if accession else "",
                })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", help="Load the verified capture into this PostgreSQL database")
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help="Local capture manifest")
    parser.add_argument("--download", action="store_true", help="Fetch a new capture from EDGAR")
    parser.add_argument("--inventory", action="store_true", help="Print the accession inventory as CSV")
    args = parser.parse_args()
    if not (args.database or args.inventory):
        parser.error("provide --database or --inventory")
    if args.database and args.inventory:
        parser.error("run --inventory separately from --database")
    sources = download_capture() if args.download else json.loads(args.manifest.read_bytes())
    batch = build_batch(sources)
    if args.database:
        load_batch(batch, args.database)
    if args.download:
        with NamedTemporaryFile(mode="w", dir=args.manifest.parent, delete=False, encoding="utf-8") as handle:
            temporary = Path(handle.name)
            try:
                json.dump(sources, handle, indent=2)
                handle.write("\n")
                handle.close()
                os.replace(temporary, args.manifest)
            finally:
                temporary.unlink(missing_ok=True)
    if args.inventory:
        report_inventory(batch, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, TypeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"SEC backfill failed: {error}") from None
