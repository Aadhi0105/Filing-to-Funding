"""Qualify historical liquidity and cash flows from EDGAR's primary statements."""

import argparse
import csv
import fcntl
import hashlib
import io
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile, is_zipfile

from pipelines.backfill_sec import EdgarDownloadError, download_edgar, sec_contact, utc_timestamp
from pipelines.load_pilot import ROOT, archive_payload, compose_psql

INVENTORY = ROOT / "docs/sec_filing_inventory.csv"
MANIFEST = ROOT / ".local/sec-statement-captures.jsonl"
XHTML = "{http://www.w3.org/1999/xhtml}"
IX = "{http://www.xbrl.org/2013/inlineXBRL}"
INSTANCE = "{http://www.xbrl.org/2003/instance}"
CASH = {
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
}
CURRENT_DEBT = {"DebtCurrent", "ShortTermBorrowings", "LongTermDebtCurrent"}
NONCURRENT_DEBT = {"LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"}
TOTAL_CFO = "NetCashProvidedByUsedInOperatingActivities"
CONTINUING_CFO = "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"
CAPEX = {"PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"}
BALANCE_TAGS = CASH | CURRENT_DEBT | NONCURRENT_DEBT | {"Assets", "AssetsCurrent", "LiabilitiesCurrent"}
FLOW_TAGS = CAPEX | {TOTAL_CFO, CONTINUING_CFO}
ROK_LEASE_POLICY = (
    "long-term finance lease liabilities are presented as long-term debt and current finance lease liabilities "
    "are included in current portion of long-term debt"
)
MAX_BYTES = 12 * 1024 * 1024


def text(element):
    return " ".join("".join(element.itertext()).split())


def local_name(node):
    name = node.get("name", "")
    return name.removeprefix("us-gaap:") if name.startswith("us-gaap:") else ""


def load_document(filing, source):
    accession = filing["accession"]
    base, member = filing["filing_url"].rsplit("/", 1)
    source_types = {
        f"{base}/{accession}-xbrl.zip": "zip",
        filing["filing_url"]: "html",
    }
    suffix = source_types.get(source["source_url"])
    digest = source["sha256"]
    expected = f".local/source-cache/{digest}.{suffix}"
    timestamp = utc_timestamp(source["retrieved_at"])
    if (suffix is None or source["member"] != member or source["source_kind"] != "sec_filing"
            or source["storage_key"] != expected or not timestamp
            or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError(f"Invalid evidence manifest for {accession}")

    with (ROOT / expected).open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if (not data or len(data) > MAX_BYTES or len(data) != source["byte_count"]
            or hashlib.sha256(data).hexdigest() != digest):
        raise ValueError(f"Archive checksum or length mismatch for {accession}")
    if suffix == "zip":
        with ZipFile(io.BytesIO(data)) as package:
            members = [info for info in package.infolist() if info.filename == member]
            if len(members) != 1 or members[0].file_size > MAX_BYTES:
                raise ValueError(f"Expected one primary statement document in {accession}")
            data = package.read(members[0])
    xml = ET.iterparse(io.BytesIO(data), events=("start-ns", "start"))
    namespaces = {}
    for event, item in xml:
        if event == "start":
            break
        namespaces[item[0]] = item[1]
    for _ in xml:
        pass
    if (xml.root.tag != XHTML + "html"
            or not re.fullmatch(r"https?://fasb\.org/us-gaap/[0-9]{4}(?:-01-31)?", namespaces.get("us-gaap", ""))
            or namespaces.get("iso4217") != "http://www.xbrl.org/2003/iso4217"):
        raise ValueError(f"Unexpected statement namespaces for {accession}")
    return xml.root


def entity_contexts(document, cik):
    contexts = {}
    for context in document.iter(INSTANCE + "context"):
        entity = context.find(INSTANCE + "entity")
        period = context.find(INSTANCE + "period")
        if entity is None or period is None or entity.find(INSTANCE + "segment") is not None:
            continue
        identifier = entity.findtext(INSTANCE + "identifier", "").strip()
        if identifier.zfill(10) != cik or context.find(INSTANCE + "scenario") is not None:
            continue
        instant = period.findtext(INSTANCE + "instant")
        start = period.findtext(INSTANCE + "startDate")
        end = period.findtext(INSTANCE + "endDate")
        if instant and not start and not end:
            contexts[context.attrib["id"]] = (None, date.fromisoformat(instant))
        elif not instant and start and end:
            contexts[context.attrib["id"]] = (date.fromisoformat(start), date.fromisoformat(end))
    return contexts


def statement_rows(document, contexts):
    usd = {unit.attrib["id"] for unit in document.iter(INSTANCE + "unit")
           if [child.text for child in unit] == ["iso4217:USD"]}
    hidden = {node.get("id"): node for section in document.iter(IX + "hidden")
              for node in section.iter(IX + "nonFraction")}
    styles = re.compile(r"-sec-ix-hidden\s*:\s*([^;\s]+)")
    for table in document.iter(XHTML + "table"):
        entries = []
        for row in table.iter(XHTML + "tr"):
            first = next(iter(row), None)
            if first is None:
                continue
            label = text(first).lower()
            nodes = list(row.iter(IX + "nonFraction"))
            for element in row.iter():
                reference = styles.search(element.get("style", ""))
                if reference and reference[1] in hidden:
                    nodes.append(hidden[reference[1]])
            for node in nodes:
                context = contexts.get(node.get("contextRef"))
                if context and node.get("unitRef") in usd and local_name(node) in BALANCE_TAGS | FLOW_TAGS:
                    entries.append((label, local_name(node), context, node))
        if entries:
            yield entries


def amount(node):
    displayed = text(node)
    transform = node.get("format", "").partition(":")[2]
    scale = int(node.get("scale", "0"))
    sign = node.get("sign")
    if not -12 <= scale <= 12 or sign not in (None, "-"):
        raise ValueError(f"Unsupported scale or sign on {node.get('id')}")
    if transform in {"zerodash", "fixed-zero", "numdash"} and displayed in {"-", "—", "–", "0"}:
        return Decimal(0)
    if transform not in {"", "numdotdecimal", "num-dot-decimal"} or not re.fullmatch(
        r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?", displayed
    ):
        raise ValueError(f"Unsupported numeric format {transform!r} on {node.get('id')}")
    return Decimal(("-" if sign else "") + displayed.replace(",", "")).scaleb(scale)


def consistent_value(rows):
    values = {}
    for row in rows:
        node = row[3]
        values.setdefault((amount(node), node.attrib["decimals"]), node)
    return next(iter(values.items())) if len(values) == 1 else None


def make_fact(filing, source, concept, period, basis, scope, evidence, sign=1):
    (value, precision), node = evidence
    start, end = period
    return {
        "accession": filing["accession"], "concept": concept, "source_tag": local_name(node),
        "period_start": start.isoformat() if start else None, "period_end": end.isoformat(),
        "reporting_basis": basis, "scope_key": scope, "value": str(sign * value),
        "reported_decimals": precision, "source_locator": f"{source['member']}#{node.attrib['id']}",
    }


def balance_facts(filing, source, entries, period, document, contexts):
    selected = [entry for entry in entries if entry[2] == period]
    specs = {
        "current_assets": ({"AssetsCurrent"}, r"total current assets"),
        "current_liabilities": ({"LiabilitiesCurrent"}, r"total current liabilities"),
        "cash_and_equivalents": (CASH, r"cash and (?:cash )?equivalents"),
        "short_term_debt": (CURRENT_DEBT, r"(?:short.term (?:debt|borrowings)(?: and current portion of long.term debt)?|current maturities of long.term debt|current portion of long.term debt)"),
        "noncurrent_debt": (NONCURRENT_DEBT, r"long.term debt(?:, net)?"),
    }
    if filing["ticker"] == "DOV":
        tags, label = specs["short_term_debt"]
        specs["short_term_debt"] = (tags, label + "|notes payable")
    if filing["ticker"] == "ROK":
        specs["short_term_debt"] = ({"ShortTermBorrowings"}, r"short.term debt")
        specs["current_portion_long_term_debt"] = ({"LongTermDebtCurrent"}, r"current portion of long.term debt")
    for concept, (tags, label) in specs.items():
        key = [entry for entry in selected if entry[1] in tags and re.fullmatch(label, entry[0])]
        value = consistent_value(key)
        if value:
            yield make_fact(filing, source, concept, period, "consolidated", "historical_balance_sheet", value)

    # The total lease liability can be deducted only when the note includes both portions in debt.
    if filing["ticker"] == "ROK" and filing["fiscal_period"] == "FY" and ROK_LEASE_POLICY in text(document).lower():
        lease_tag = "FinanceLeaseLiability"
        usd = {unit.attrib["id"] for unit in document.iter(INSTANCE + "unit")
               if [child.text for child in unit] == ["iso4217:USD"]}
        disclosures = [
            ("", lease_tag, period, node) for node in document.iter(IX + "nonFraction")
            if local_name(node) == lease_tag and contexts.get(node.get("contextRef")) == period
            and node.get("unitRef") in usd
        ]
        leases = consistent_value(disclosures)
        if leases and leases[0][0] >= 0:
            yield make_fact(filing, source, "finance_lease_liabilities", period, "consolidated",
                            "historical_balance_sheet", leases)


def cash_flow_scope(filing, period, tag):
    start, _ = period
    year = int(filing["fiscal_year"])
    if filing["ticker"] == "ITW":
        if (start.year >= 2024) != (year >= 2024) or tag != TOTAL_CFO:
            return None
        scope = "itw_from_fifo_change" if year >= 2024 else "itw_before_fifo_change"
        return "consolidated", scope
    if filing["ticker"] == "ROK":
        if (start.year >= 2025) != (year >= 2026) or tag != TOTAL_CFO:
            return None
        scope = "rok_sensia_transition_year" if year >= 2026 else "rok_before_sensia_transition"
        return "consolidated", scope
    if year == 2020 and tag == CONTINUING_CFO and start.year == 2020:
        return "continuing_operations", "dov_2020_continuing_operations"
    if filing["report_end"] >= "2024-09-30" and tag == CONTINUING_CFO and start.year >= 2024:
        return "continuing_operations", "dov_excluding_esg"
    if filing["report_end"] < "2024-09-30" and tag == TOTAL_CFO and start.year >= 2021:
        return "consolidated", "dov_including_esg"
    return None


def flow_facts(filing, source, entries, current, supported_ends):
    current_start, current_end = current
    for offset in range(3 if filing["fiscal_period"] == "FY" else 2):
        earlier_end_year = current_end.year - offset
        # February does not appear as a fiscal end in these issuer calendars.
        period = (current_start.replace(year=current_start.year - offset), current_end.replace(year=earlier_end_year))
        if period[1] not in supported_ends:
            continue
        rows = [entry for entry in entries if entry[2] == period]
        cfo_rows = [entry for entry in rows if entry[1] in {TOTAL_CFO, CONTINUING_CFO}]
        cfo_tags = {entry[1] for entry in cfo_rows}
        cash_capex = [
            entry for entry in rows if entry[1] in CAPEX and re.fullmatch(
                r"(?:additions to (?:property, )?plant and equipment|capital expenditures)", entry[0]
            )
        ]
        if len(cfo_tags) != 1:
            continue
        scope = cash_flow_scope(filing, period, next(iter(cfo_tags)))
        cfo = consistent_value(cfo_rows)
        capex = consistent_value(cash_capex)
        if cfo and capex and capex[0][0] >= 0 and scope:
            yield make_fact(filing, source, "operating_cash_flow", period, *scope, cfo)
            yield make_fact(filing, source, "cash_capex_outflow", period, *scope, capex, sign=-1)


def qualify(filing, source, supported_ends):
    document = load_document(filing, source)
    contexts = entity_contexts(document, filing["cik"])
    end = date.fromisoformat(filing["report_end"])
    fiscal_year = int(filing["fiscal_year"])
    start = date(fiscal_year - 1, 10, 1) if filing["ticker"] == "ROK" else date(fiscal_year, 1, 1)
    as_of = (None, end)
    cumulative = (start, end)
    balances, flows = [], []
    for table in statement_rows(document, contexts):
        tags = {(entry[1], entry[2]) for entry in table}
        if all((tag, as_of) in tags for tag in ("Assets", "AssetsCurrent", "LiabilitiesCurrent")):
            balances.append(table)
        if (any((tag, cumulative) in tags for tag in {TOTAL_CFO, CONTINUING_CFO})
                and any((tag, cumulative) in tags for tag in CAPEX)):
            flows.append(table)
    facts = []
    if len(balances) == 1:
        facts.extend(balance_facts(filing, source, balances[0], as_of, document, contexts))
    if len(flows) == 1:
        facts.extend(flow_facts(filing, source, flows[0], cumulative, supported_ends))
    return facts


def inventory_rows():
    with INVENTORY.open(newline="") as handle:
        return [row for row in csv.DictReader(handle) if row["accession"]]


def capture_sources(records, inventory):
    captures = [json.loads(line) for line in records if line.strip()]
    sources = {entry["accession"]: entry for entry in captures}
    if len(sources) != len(captures) or sources.keys() - {row["accession"] for row in inventory}:
        raise ValueError("Duplicate or unexpected accession in statement evidence manifest")
    return sources


def download_statements(manifest):
    inventory = inventory_rows()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a+", encoding="utf-8") as records:
        fcntl.flock(records, fcntl.LOCK_EX)
        records.seek(0)
        existing = capture_sources(records, inventory)
        pending = [row for row in inventory if row["accession"] not in existing]
        if not pending:
            return
        contact = sec_contact()
        for filing in pending:
            accession = filing["accession"]
            primary = filing["filing_url"]
            base, member = primary.rsplit("/", 1)
            url, suffix = f"{base}/{accession}-xbrl.zip", "zip"
            try:
                data, retrieved_at = download_edgar(url, contact, MAX_BYTES)
                if not is_zipfile(io.BytesIO(data)):
                    raise ValueError(f"Expected an EDGAR ZIP for {accession}")
            except EdgarDownloadError as error:
                if error.status not in {"404", "500", "502", "503", "504"}:
                    raise
                time.sleep(0.85)
                url, suffix = primary, "html"
                data, retrieved_at = download_edgar(url, contact, MAX_BYTES)
                if ET.fromstring(data).tag != XHTML + "html":
                    raise ValueError(f"Expected the inline XBRL document for {accession}")
            source = {
                "accession": accession, "member": member, "source_kind": "sec_filing",
                "source_url": url, "retrieved_at": retrieved_at, **archive_payload(data, suffix),
            }
            records.write(json.dumps(source) + "\n")
            records.flush()
            time.sleep(0.85)


def input_batch(manifest):
    inventory = inventory_rows()
    if not manifest.exists():
        raise ValueError("Capture the original EDGAR filings with --download or supply a saved manifest")
    with manifest.open(encoding="utf-8") as records:
        fcntl.flock(records, fcntl.LOCK_SH)
        sources = capture_sources(records, inventory)
    supported_ends = defaultdict(set)
    for row in inventory:
        supported_ends[row["cik"]].add(date.fromisoformat(row["report_end"]))
    for row in inventory:
        source = sources.get(row["accession"])
        yield row, source, qualify(row, source, supported_ends[row["cik"]]) if source else []


def report(records):
    output = csv.writer(sys.stdout, lineterminator="\n")
    output.writerow([
        "ticker", "window", "fiscal_year", "fiscal_period", "report_end", "accession", "statement_url",
        "statement_sha256", "liquidity_inputs", "reported_debt_inputs", "lease_adjustment",
        "cash_source_tag", "cash_flow_inputs", "cash_flow_basis", "cash_flow_scope", "capex_source_tag",
        "comparative_cash_flow_observations",
    ])
    for filing, source, facts in records:
        current = [fact for fact in facts if fact["period_end"] == filing["report_end"]]
        concepts = {fact["concept"] for fact in current}
        liquidity = {"current_assets", "current_liabilities", "cash_and_equivalents"}
        debt = {"short_term_debt", "noncurrent_debt"}
        if filing["ticker"] == "ROK":
            debt.add("current_portion_long_term_debt")
        by_concept = {fact["concept"]: fact for fact in current}
        flow = by_concept.get("operating_cash_flow", {})
        output.writerow([
            *(filing[key] for key in ("ticker", "window", "fiscal_year", "fiscal_period", "report_end", "accession")),
            filing["filing_url"], source["sha256"] if source else "",
            "qualified" if liquidity <= concepts else "missing_statement_inputs",
            "qualified_reported_basis" if debt <= concepts else "missing_statement_inputs",
            "qualified" if debt <= concepts and "finance_lease_liabilities" in concepts else "unverified",
            by_concept.get("cash_and_equivalents", {}).get("source_tag", ""),
            "qualified" if flow else "missing_compatible_inputs", flow.get("reporting_basis", ""),
            flow.get("scope_key", ""), by_concept.get("cash_capex_outflow", {}).get("source_tag", ""),
            len(facts) - len(current),
        ])


def load(records, database):
    script = io.StringIO()
    script.write("BEGIN;\nCREATE TEMP TABLE statement_input (document jsonb NOT NULL);\n")
    script.write("COPY statement_input FROM STDIN WITH (FORMAT csv);\n")
    writer = csv.writer(script, lineterminator="\n")
    writer.writerows(
        [json.dumps({"source": source, "facts": facts})] for _, source, facts in records if source is not None
    )
    script.write("\\.\n")
    script.write((ROOT / "database/load_sec_statements.sql").read_text())
    subprocess.run(
        [*compose_psql()[:-1], database, "-X", "-v", "ON_ERROR_STOP=1"],
        cwd=ROOT, input=script.getvalue(), text=True, check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--download", action="store_true", help="Capture original SEC filings missing from the manifest")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--coverage", action="store_true", help="Print the per-filing qualification report as CSV")
    action.add_argument("--database", help="Load qualified observations into a migrated, backfilled database")
    args = parser.parse_args()
    if args.download:
        download_statements(args.manifest)
    records = list(input_batch(args.manifest))
    if args.coverage:
        report(records)
    else:
        load(records, args.database)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, BadZipFile, ET.ParseError, InvalidOperation,
            subprocess.CalledProcessError) as error:
        raise SystemExit(f"SEC statement qualification failed: {error}") from None
