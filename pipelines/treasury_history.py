"""Archive and replay the Treasury daily par curves for the pilot window."""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree as ET

from pipelines.load_pilot import ROOT, archive_payload, compose_psql

WINDOW_START = date(2020, 1, 1)
WINDOW_END = date(2026, 11, 19)
MANIFEST = ROOT / ".local/treasury-history-2026-11-19.json"
YEARS = tuple(range(WINDOW_START.year, WINDOW_END.year + 1))
FEED = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
MAX_BYTES = 3 * 1024 * 1024
XML_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
}
FIELDS = {24: "BC_2YEAR", 60: "BC_5YEAR", 120: "BC_10YEAR"}


def annual_url(year):
    return f"{FEED}?data=daily_treasury_yield_curve&field_tdr_date_value={year}"


def treasury_curves(payload):
    root = ET.fromstring(payload)
    if (root.tag != f"{{{XML_NS['a']}}}feed"
            or root.findtext("a:title", namespaces=XML_NS) != "DailyTreasuryYieldCurveRateData"):
        raise ValueError("Expected the Treasury daily par yield XML feed")
    if root.find("a:link[@rel='next']", XML_NS) is not None:
        raise ValueError("The Treasury feed contains an uncaptured next page")
    curves = {}
    for entry in root.findall("a:entry", XML_NS):
        record = entry.find("a:content/m:properties", XML_NS)
        if record is None:
            raise ValueError("A Treasury entry is missing its observation data")
        date_text = record.findtext("d:NEW_DATE", namespaces=XML_NS)
        if not date_text:
            raise ValueError("A Treasury entry is missing its observation date")
        marker = datetime.fromisoformat(date_text)
        if marker.time() != time.min or marker.tzinfo is not None:
            raise ValueError(f"Unexpected Treasury observation date marker: {date_text}")
        observed_on = marker.date()
        if observed_on in curves:
            raise ValueError(f"Treasury feed repeated {observed_on}")
        rates = {}
        for maturity, field in FIELDS.items():
            value = record.findtext(f"d:{field}", namespaces=XML_NS)
            if not value:
                raise ValueError(f"Missing Treasury yield for {observed_on} / {maturity} months")
            numeric = Decimal(value)
            if not numeric.is_finite():
                raise ValueError(f"Non-finite Treasury yield for {observed_on} / {maturity} months")
            rates[maturity] = numeric
        curves[observed_on] = rates
    if not curves:
        raise ValueError("The Treasury feed contains no observation dates")
    return curves


def annual_rates(payload, year):
    curves = treasury_curves(payload)
    if any(observed_on.year != year for observed_on in curves):
        raise ValueError(f"The Treasury response includes dates outside {year}")
    selected = sorted(day for day in curves if WINDOW_START <= day <= WINDOW_END)
    last_month = WINDOW_END.month if year == WINDOW_END.year else 12
    if {day.month for day in selected} != set(range(1, last_month + 1)):
        raise ValueError(f"The Treasury response does not cover every requested month of {year}")
    return [
        {"observation_date": day.isoformat(), "maturity_months": maturity, "yield_percent": str(value)}
        for day in selected for maturity, value in curves[day].items()
    ]


def retrieval_time(value):
    timestamp = datetime.fromisoformat(value)
    if timestamp.utcoffset() is None:
        raise ValueError("Treasury retrieval timestamps require a UTC offset")
    return timestamp.astimezone(timezone.utc).isoformat()


def capture(year, payload, retrieved_at):
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError(f"Unexpected Treasury response size for {year}")
    annual_rates(payload, year)
    return {
        "year": year, "source_url": annual_url(year), "retrieved_at": retrieval_time(retrieved_at),
        **archive_payload(payload, "xml"),
    }


def download():
    sources = []
    for year in YEARS:
        with NamedTemporaryFile() as response:
            subprocess.run([
                "curl", "--disable", "--silent", "--show-error", "--fail",
                "--retry", "1", "--retry-delay", "2", "--retry-max-time", "70", "--max-time", "35",
                "--max-filesize", str(MAX_BYTES),
                "--user-agent", "Filing-to-Funding (https://github.com/Aadhi0105/Filing-to-Funding)",
                "--output", response.name, annual_url(year),
            ], check=True)
            retrieved_at = datetime.now(timezone.utc).isoformat()
            sources.append(capture(year, Path(response.name).read_bytes(), retrieved_at))
    return sources


def write_manifest(manifest, sources):
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=manifest.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(sources, handle, indent=2)
            handle.write("\n")
            handle.close()
            os.replace(temporary, manifest)
        finally:
            temporary.unlink(missing_ok=True)


def batch(sources):
    if sorted(source["year"] for source in sources) != list(YEARS):
        raise ValueError("The Treasury manifest must contain one response for each pilot year")
    for source in sorted(sources, key=lambda entry: entry["year"]):
        year = source["year"]
        digest = source["sha256"]
        key = f".local/source-cache/{digest}.xml"
        if (not re.fullmatch(r"[0-9a-f]{64}", digest) or source["storage_key"] != key
                or source["source_url"] != annual_url(year)):
            raise ValueError(f"Invalid Treasury manifest entry for {year}")
        with (ROOT / key).open("rb") as handle:
            payload = handle.read(MAX_BYTES + 1)
        if (len(payload) > MAX_BYTES or len(payload) != source["byte_count"]
                or hashlib.sha256(payload).hexdigest() != digest):
            raise ValueError(f"Treasury response does not match the manifest for {year}")
        yield {
            **source, "retrieved_at": retrieval_time(source["retrieved_at"]),
            "rates": annual_rates(payload, year),
        }


def import_history(records, database):
    script = io.StringIO()
    script.write("BEGIN;\nCREATE TEMP TABLE treasury_input (document jsonb NOT NULL);\n")
    script.write("COPY treasury_input FROM STDIN WITH (FORMAT csv);\n")
    writer = csv.writer(script, lineterminator="\n")
    writer.writerows([json.dumps(record)] for record in records)
    script.write("\\.\n")
    script.write((ROOT / "database/load_treasury_history.sql").read_text())
    subprocess.run(
        [*compose_psql()[:-1], database, "-X", "-v", "ON_ERROR_STOP=1"],
        cwd=ROOT, input=script.getvalue(), text=True, check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST, help="Local archive capture manifest")
    parser.add_argument("--download", action="store_true", help="Download and validate a fresh annual capture")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--database", help="Load the archived Treasury history into this migrated PostgreSQL database")
    action.add_argument("--coverage", action="store_true", help="Print checked annual observation coverage")
    args = parser.parse_args()
    sources = download() if args.download else json.loads(args.manifest.read_bytes())
    records = list(batch(sources))
    if args.database:
        import_history(records, args.database)
    else:
        for item in records:
            rates = item["rates"]
            print(f"{item['year']} {rates[0]['observation_date']} to {rates[-1]['observation_date']}: "
                  f"{len(rates) // len(FIELDS)} dates, {len(rates)} yields")
    if args.download:
        write_manifest(args.manifest, sources)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, TypeError, InvalidOperation, ET.ParseError, OSError, ValueError,
            subprocess.CalledProcessError) as error:
        raise SystemExit(f"Treasury history import failed: {error}") from None
