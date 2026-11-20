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
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile

from pipelines.load_pilot import ROOT, archive_payload, compose_psql
from pipelines.sec_http import download_edgar, sec_contact

CUTOFF = date(2026, 11, 19)
SEC_API = "https://data.sec.gov"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
MANIFEST = ROOT / ".local/sec-history-2026-11-19.json"
MAX_BYTES = 24 * 1024 * 1024
HISTORY_KIND = "sec_submissions_history"
FILING_COLUMNS = ("accessionNumber", "form", "reportDate", "filingDate", "acceptanceDateTime", "primaryDocument")
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


def overlapping_shards(cik, submissions, first_end):
    shards = {}
    for descriptor in submissions["filings"]["files"]:
        name = descriptor["name"]
        if not re.fullmatch(rf"CIK{cik}-submissions-[0-9]+\.json", name):
            raise ValueError(f"Invalid EDGAR historical submissions filename for {cik}")
        start = date.fromisoformat(descriptor["filingFrom"])
        end = date.fromisoformat(descriptor["filingTo"])
        url = f"{SEC_API}/submissions/{name}"
        if start > end or url in shards:
            raise ValueError(f"Invalid or duplicate EDGAR historical submissions range for {name}")
        shards[url] = (start, end)
    return {url: bounds for url, bounds in sorted(shards.items())
            if bounds[0] <= CUTOFF and bounds[1] >= date.fromisoformat(first_end)}


def download_capture():
    contact = sec_contact()
    archives = []
    for cik, _, _, year_end, first_year in ISSUERS:
        url = endpoint(cik, "sec_submissions")
        content, fetched = download_edgar(url, contact, MAX_BYTES)
        submissions = json.loads(content)
        if str(submissions["cik"]).zfill(10) != cik:
            raise ValueError(f"EDGAR capture has the wrong CIK for {cik}")
        archives.append(capture(cik, "sec_submissions", url, fetched, content))
        for history_url in overlapping_shards(cik, submissions, min(periods(year_end, first_year))):
            content, fetched = download_edgar(history_url, contact, MAX_BYTES)
            archives.append(capture(cik, HISTORY_KIND, history_url, fetched, content))
        url = endpoint(cik, "sec_company_facts")
        content, fetched = download_edgar(url, contact, MAX_BYTES)
        archives.append(capture(cik, "sec_company_facts", url, fetched, content))
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


def filing_rows(cik, document, expected, history=()):
    first_end, last_end = min(expected), max(expected)
    captures = [(endpoint(cik, "sec_submissions"), document["filings"]["recent"], None), *history]
    by_accession = defaultdict(list)
    in_window = set()
    for url, columns, bounds in captures:
        if any(not isinstance(columns[field], list) for field in FILING_COLUMNS):
            raise ValueError(f"Expected EDGAR filing columns in {url}")
        for accession, form, end, filed, accepted, primary in zip(
            *(columns[field] for field in FILING_COLUMNS), strict=True
        ):
            filed_date = date.fromisoformat(filed) if bounds or form in FORMS else None
            if bounds and not bounds[0] <= filed_date <= bounds[1]:
                raise ValueError(f"EDGAR filing date outside advertised history range for {url}")
            if form in FORMS and filed_date <= CUTOFF:
                if not end and filed >= first_end:
                    raise ValueError(f"Report date missing for {accession}")
                if first_end <= end <= last_end:
                    in_window.add(accession)
            by_accession[accession].append(((form, end, filed, primary), accepted, url))

    rows = {}
    for accession, observations in by_accession.items():
        if accession not in in_window:
            continue
        fields, accepted, url = observations[0]
        timestamp = utc_timestamp(accepted)
        for other, other_accepted, other_url in observations[1:]:
            other_timestamp = utc_timestamp(other_accepted)
            if fields != other or (timestamp and other_timestamp and timestamp != other_timestamp):
                raise ValueError(f"Conflicting EDGAR submissions metadata for {accession}")
            if not timestamp and other_timestamp:
                timestamp, url = other_timestamp, other_url
        form, end, filed, primary = fields
        if end not in expected or expected[end]["form_type"] != form.removesuffix("/A"):
            raise ValueError(f"Unexpected fiscal period or form for {accession}")
        if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
            raise ValueError(f"Invalid SEC accession: {accession}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.html?", primary) or filed < end:
            raise ValueError(f"Unexpected filing document or date for {accession}")
        rows[accession] = {
            **expected[end], "accession": accession, "form_type": form, "filed_on": filed,
            "accepted_at": timestamp, "primary_document": primary, "metadata_source_url": url,
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
    by_url = {source["source_url"]: source for source in sources}
    if len(by_url) != len(sources):
        raise ValueError("Duplicate EDGAR source URL in the capture")

    def read_source(cik, kind, url):
        if url not in by_url:
            raise ValueError(f"Missing required EDGAR source capture for {url}")
        source = by_url.pop(url)
        if (source["cik"], source["source_kind"]) != (cik, kind):
            raise ValueError(f"Unexpected EDGAR source identity for {url}")
        return source, read_archive(source)

    batch = []
    for cik, ticker, legal_name, year_end, first_year in ISSUERS:
        metadata, submissions = read_source(cik, "sec_submissions", endpoint(cik, "sec_submissions"))
        facts_source, company_facts = read_source(cik, "sec_company_facts", endpoint(cik, "sec_company_facts"))
        if str(submissions["cik"]).zfill(10) != cik or str(company_facts["cik"]).zfill(10) != cik:
            raise ValueError(f"EDGAR capture has the wrong CIK for {ticker}")
        if submissions["fiscalYearEnd"] != {12: "1231", 9: "0930"}[year_end]:
            raise ValueError(f"EDGAR's fiscal year-end changed for {ticker}")
        expected = periods(year_end, first_year)
        history = []
        archived = [metadata, facts_source]
        for url, bounds in overlapping_shards(cik, submissions, min(expected)).items():
            source, columns = read_source(cik, HISTORY_KIND, url)
            history.append((url, columns, bounds))
            archived.append(source)
        inventory = filing_rows(cik, submissions, expected, history)
        observations = list(financial_facts(company_facts, inventory, min(expected)))
        batch.append({
            "cik": cik, "ticker": ticker, "legal_name": legal_name,
            "sources": archived, "periods": list(expected.values()),
            "filings": list(inventory.values()), "facts": observations,
        })
    if by_url:
        raise ValueError("Unexpected supplemental EDGAR captures in the manifest")
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
