"""Load the expanded SEC inventory and verify reviewed samples against original filings."""

import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from pipelines import backfill_sec, qualify_sec

ROOT = backfill_sec.ROOT
SAMPLES = ROOT / "testdata/cohort_expansion/statement_samples.csv"
INVENTORY = ROOT / "docs/cohort_expansion_filing_inventory.csv"
ISSUERS = (
    ("0000091142", "AOS", "A. O. Smith Corporation", 12, 2021),
    ("0000832101", "IEX", "IDEX Corporation", 12, 2021),
    ("0000059527", "LECO", "Lincoln Electric Holdings, Inc.", 12, 2021),
)


def checksum(content):
    return hashlib.sha256(content).hexdigest()


def bundle(captures, base_snapshot_id=None):
    return {
        "base_snapshot_id": base_snapshot_id,
        "sec": json.loads((captures / "sec.json").read_bytes()),
        "statements": [json.loads(line) for line in (captures / "sample-statements.jsonl").read_text().splitlines()],
        "samples_sha256": checksum(SAMPLES.read_bytes()),
        "inventory_sha256": checksum(INVENTORY.read_bytes()),
    }


def qualified_records(manifest, batch):
    filings = {filing["accession"]: (issuer, filing) for issuer in batch for filing in issuer["filings"]}
    samples = defaultdict(list)
    data = SAMPLES.read_bytes()
    if checksum(data) != manifest["samples_sha256"]:
        raise ValueError("Reviewed statement sample checksum mismatch")
    for sample in csv.DictReader(io.StringIO(data.decode("utf-8"))):
        samples[sample["accession"]].append(sample)
    if set(samples) != {source["accession"] for source in manifest["statements"]}:
        raise ValueError("Expected an original statement capture for every reviewed filing")
    records = []
    for source in manifest["statements"]:
        accession = source["accession"]
        issuer, filing = filings[accession]
        doc = qualify_sec.load_document(filing, source)
        contexts = qualify_sec.entity_contexts(doc, issuer["cik"])
        usd = {unit.attrib["id"] for unit in doc.iter(qualify_sec.INSTANCE + "unit")
               if [child.text for child in unit] == ["iso4217:USD"]}
        nodes = {node.attrib["id"]: node for node in doc.iter(qualify_sec.IX + "nonFraction")
                 if node.get("id") and node.get("unitRef") in usd and node.get("contextRef") in contexts}
        facts = []
        for row in samples[accession]:
            node = nodes.get(row["source_locator"].rsplit("#", 1)[1])
            if node is None:
                raise ValueError(f"No exact USD fact with entity context at {accession} {row['source_locator']}")
            tag = qualify_sec.local_name(node)
            period = contexts[node.attrib["contextRef"]]
            precision = node.attrib["decimals"]
            sign = -1 if row["concept"] == "cash_capex_outflow" else 1
            value = qualify_sec.amount(node)
            fact = qualify_sec.make_fact(filing, source, row["concept"], period, row["reporting_basis"],
                                         row["scope_key"], ((value, precision), node), sign)
            expected_scope = f"{issuer['ticker'].lower()}_reviewed" if period[0] else "historical_balance_sheet"
            if (row["cik"], row["ticker"], row["filed_on"], row["filing_url"], row["source_url"],
                row["source_sha256"], row["unit"], row["reporting_basis"], row["scope_key"]) != (
                    issuer["cik"], issuer["ticker"], filing["filed_on"], filing["filing_url"], source["source_url"],
                    source["sha256"], "USD", "consolidated", expected_scope,
                ) or tag != row["source_tag"] or any(
                    fact[key] != (row[key] or None)
                    for key in ("period_start", "period_end", "reported_decimals", "source_locator")
                ) or Decimal(fact["value"]) != Decimal(row["value"]) or period[1] > date.fromisoformat(filing["ends_on"]):
                raise ValueError(f"Reviewed fact mismatch for {accession} {row['source_locator']}")
            facts.append(fact)
        records.append((filing, source, facts))
    return records


def load(manifest, database):
    batch = backfill_sec.build_batch(manifest["sec"], ISSUERS)
    inventory = io.StringIO()
    backfill_sec.report_inventory(batch, inventory)
    if (checksum(inventory.getvalue().encode()) != manifest["inventory_sha256"]
            or checksum(INVENTORY.read_bytes()) != manifest["inventory_sha256"]):
        raise ValueError("Expanded SEC inventory does not match the reviewed inventory")
    records = qualified_records(manifest, batch)
    backfill_sec.load_batch(batch, database)
    qualify_sec.load(records, database)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_directory", type=Path)
    parser.add_argument("--base-snapshot-id", help="Reuse a validated three-company snapshot with identical base inputs")
    args = parser.parse_args()
    print(json.dumps(bundle(args.capture_directory, args.base_snapshot_id), indent=2))


if __name__ == "__main__":
    main()
