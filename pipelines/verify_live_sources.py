"""Reconcile one downloaded SEC filing and a Treasury XML sample in PostgreSQL."""

import argparse
import csv
import io
import json
import re
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from pipelines.load_pilot import REVIEW_DIR, ROOT, archive_payload, compose_psql
from pipelines.treasury_history import treasury_curves

CIK = "0000049826"
ACCESSION = "0000049826-26-000049"
SEC_BASE = "https://www.sec.gov/Archives/edgar/data/49826/000004982626000049"
SEC_MEMBER = "itw-20260630.htm"
TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value_month=202410"
)
REPORT_END = "2026-06-30"
HALF_START = "2026-01-01"
MAX_BYTES = 8 * 1024 * 1024
IX = "{http://www.xbrl.org/2013/inlineXBRL}"
XBRL = "http://www.xbrl.org/2003/instance"
XML_NS = {"x": XBRL}
# XBRL's payments concept is positive for an outflow. The reviewed statement uses a cash-flow sign.
SEC_FACTS = (
    ("CashAndCashEquivalentsAtCarryingValue", "cash_and_equivalents", None, 1),
    ("AssetsCurrent", "current_assets", None, 1),
    ("LiabilitiesCurrent", "current_liabilities", None, 1),
    ("DebtCurrent", "short_term_debt", None, 1),
    ("LongTermDebtNoncurrent", "noncurrent_debt", None, 1),
    ("NetCashProvidedByUsedInOperatingActivities", "operating_cash_flow", HALF_START, 1),
    ("PaymentsToAcquirePropertyPlantAndEquipment", "cash_capex_outflow", HALF_START, -1),
)


def read_response(filename):
    with filename.open("rb") as handle:
        content = handle.read(MAX_BYTES + 1)
    if not content or len(content) > MAX_BYTES:
        raise ValueError(f"Unexpected size for source response {filename.name}")
    return content


def itw_facts(payload):
    with ZipFile(io.BytesIO(payload)) as archive:
        members = [member for member in archive.infolist() if member.filename == SEC_MEMBER]
        if len(members) != 1 or members[0].file_size > MAX_BYTES:
            raise ValueError(f"Expected one bounded {SEC_MEMBER} in the SEC ZIP")
        document = archive.read(members[0])

    xml = ET.iterparse(io.BytesIO(document), events=("start-ns", "start"))
    namespaces = {}
    for event, value in xml:
        if event == "start":
            break
        namespaces[value[0]] = value[1]
    if namespaces.get("us-gaap") != "http://fasb.org/us-gaap/2026":
        raise ValueError("Unexpected US GAAP namespace in the ITW instance")
    if namespaces.get("iso4217") != "http://www.xbrl.org/2003/iso4217":
        raise ValueError("Unexpected currency namespace in the ITW instance")

    for _ in xml:
        pass
    root = xml.root
    contexts = {}
    for context in root.findall(".//x:context", XML_NS):
        if (context.find(".//x:segment", XML_NS) is not None
                or context.find("x:scenario", XML_NS) is not None
                or context.findtext("x:entity/x:identifier", namespaces=XML_NS) != CIK):
            continue
        instant = context.findtext("x:period/x:instant", namespaces=XML_NS)
        start = context.findtext("x:period/x:startDate", namespaces=XML_NS)
        end = context.findtext("x:period/x:endDate", namespaces=XML_NS)
        if instant == REPORT_END and start is None and end is None:
            contexts[context.attrib["id"]] = None
        elif instant is None and start == HALF_START and end == REPORT_END:
            contexts[context.attrib["id"]] = HALF_START

    cover = {fact.get("name"): "".join(fact.itertext()).strip()
             for fact in root.iter(IX + "nonNumeric") if contexts.get(fact.get("contextRef")) == HALF_START}
    if (cover.get("dei:EntityCentralIndexKey"), cover.get("dei:DocumentType")) != (CIK, "10-Q"):
        raise ValueError("The ZIP member does not identify the expected issuer and form")

    usd_units = {unit.attrib["id"] for unit in root.findall(".//x:unit", XML_NS)
                 if unit.findtext("x:measure", namespaces=XML_NS) == "iso4217:USD"}
    numeric = list(root.iter(IX + "nonFraction"))
    for concept, reviewed_concept, start, reviewed_sign in SEC_FACTS:
        values = {}
        for fact in numeric:
            context = fact.get("contextRef")
            if (fact.get("name") != f"us-gaap:{concept}" or context not in contexts
                    or contexts[context] != start or fact.get("unitRef") not in usd_units):
                continue
            displayed = "".join(fact.itertext()).strip()
            transformation = fact.get("format")
            pattern = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?" if transformation else r"\d+(?:\.\d+)?"
            sign = fact.get("sign")
            if (transformation not in (None, "ixt:num-dot-decimal")
                    or not re.fullmatch(pattern, displayed, flags=re.ASCII) or sign not in (None, "-")):
                raise ValueError(f"Unexpected number format in {concept}")
            scale = int(fact.get("scale", "0"))
            if not -15 <= scale <= 15:
                raise ValueError(f"Unexpected XBRL scale in {concept}")
            value = Decimal(("-" if sign else "") + displayed.replace(",", "")).scaleb(scale)
            key = (value, fact.attrib["decimals"])
            values.setdefault(key, fact.attrib["id"])
        if len(values) != 1:
            raise ValueError(f"Expected one unambiguous consolidated USD value for {concept}")
        (value, precision), fact_id = next(iter(values.items()))
        yield {
            "concept": concept, "reviewed_concept": reviewed_concept, "reviewed_sign": reviewed_sign,
            "period_start": start, "period_end": REPORT_END, "value": str(value),
            "reported_decimals": precision, "source_locator": f"{SEC_MEMBER}#{fact_id}",
        }


def treasury_rates(payload):
    review = json.loads((REVIEW_DIR / "treasury_pilot.json").read_bytes())
    sample_dates = {row[0] for row in review["rows"]}
    curves = {day.isoformat(): rates for day, rates in treasury_curves(payload).items()}
    missing = sample_dates - curves.keys()
    if missing:
        raise ValueError(f"Treasury feed missing dates: {', '.join(sorted(missing))}")
    for day in sorted(sample_dates):
        for maturity, value in curves[day].items():
            yield {"observation_date": day, "maturity_months": maturity, "yield_percent": str(value)}


def retrieval_time(value):
    timestamp = datetime.fromisoformat(value)
    if timestamp.utcoffset() is None:
        raise argparse.ArgumentTypeError("Provide the download completion time with a UTC offset")
    return timestamp.astimezone(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Migrated test database with the reviewed pilot loaded")
    parser.add_argument("--sec-zip", type=Path, required=True)
    parser.add_argument("--sec-retrieved-at", type=retrieval_time, required=True)
    parser.add_argument("--treasury-xml", type=Path, required=True)
    parser.add_argument("--treasury-retrieved-at", type=retrieval_time, required=True)
    args = parser.parse_args()
    sec = read_response(args.sec_zip)
    treasury = read_response(args.treasury_xml)
    facts = list(itw_facts(sec))
    rates = list(treasury_rates(treasury))
    evidence = {
        "accession": ACCESSION,
        "facts": facts,
        "rates": rates,
        "sources": [
            {"kind": "sec_filing", "url": f"{SEC_BASE}/{ACCESSION}-xbrl.zip",
             "retrieved_at": args.sec_retrieved_at, **archive_payload(sec, "zip")},
            {"kind": "treasury_daily_par_yields", "url": TREASURY_URL,
             "retrieved_at": args.treasury_retrieved_at, **archive_payload(treasury, "xml")},
        ],
    }
    stream = io.StringIO()
    stream.write("BEGIN;\nCREATE TEMP TABLE live_input (document jsonb NOT NULL);\n")
    stream.write("COPY live_input FROM STDIN WITH (FORMAT csv);\n")
    csv.writer(stream, lineterminator="\n").writerow([json.dumps(evidence)])
    stream.write("\\.\n")
    stream.write((ROOT / "database" / "verify_live_sources.sql").read_text())
    subprocess.run(
        [*compose_psql()[:-1], args.database, "-X", "-v", "ON_ERROR_STOP=1"],
        cwd=ROOT, input=stream.getvalue(), text=True, check=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation, ET.ParseError,
            BadZipFile, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Live source verification failed: {error}") from None
