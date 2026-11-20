"""Qualify historical financial inputs from EDGAR primary statements."""

import argparse
import csv
import fcntl
import hashlib
import io
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile, is_zipfile

from pipelines.backfill_sec import utc_timestamp
from pipelines.sec_http import EdgarDownloadError, download_edgar, sec_contact
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
INVESTING_TOTALS = {"NetCashProvidedByUsedInInvestingActivities",
                    "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"}
FINANCING_TOTALS = {"NetCashProvidedByUsedInFinancingActivities",
                    "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"}
FLOW_TAGS = CAPEX | {TOTAL_CFO, CONTINUING_CFO} | INVESTING_TOTALS | FINANCING_TOTALS
REVENUE_TAGS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
}
INCOME_TAGS = {"ProfitLoss", "NetIncomeLoss", "IncomeLossFromContinuingOperations"}
INCOME_ANCHORS = {"CostOfGoodsAndServicesSold", "OperatingIncomeLoss"}
NONCONTROLLING_INCOME = "NetIncomeLossAttributableToNoncontrollingInterest"
STATEMENT_TAGS = BALANCE_TAGS | FLOW_TAGS | REVENUE_TAGS | INCOME_TAGS | INCOME_ANCHORS | {NONCONTROLLING_INCOME}
ROK_LEASE_POLICY = (
    "long-term finance lease liabilities are presented as long-term debt and current finance lease liabilities "
    "are included in current portion of long-term debt"
)
DOV_LEASE_POLICY = (
    "the related lease liabilities are included in other accrued expenses and other liabilities"
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
                if context and node.get("unitRef") in usd and local_name(node) in STATEMENT_TAGS:
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


def fact_evidence(rows, *, nonnegative=False):
    values = {}
    for row in rows:
        node = row[3]
        values.setdefault((amount(node), node.attrib["decimals"]), node)
    # Keep both sides of a conflict even if one amount would not qualify on its own.
    amounts = {value for value, _ in values}
    if nonnegative and len(amounts) == 1 and next(iter(amounts)) < 0:
        return ()
    return values.items()


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
    total_assets_label = {"DOV": "total assets", "ITW": "", "ROK": "total"}[filing["ticker"]]
    specs = {
        "total_assets": ({"Assets"}, total_assets_label),
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
        for evidence in fact_evidence(key):
            yield make_fact(filing, source, concept, period, "consolidated", "historical_balance_sheet", evidence)

    if filing["fiscal_period"] != "FY" or filing["ticker"] not in {"ROK", "DOV"}:
        return
    notes = text(document).lower()
    if filing["ticker"] == "ROK" and ROK_LEASE_POLICY in notes:
        concept = "finance_lease_liabilities"
    elif filing["ticker"] == "DOV" and DOV_LEASE_POLICY in notes:
        concept = "finance_lease_liabilities_outside_debt"
    else:
        return

    lease_tag = "FinanceLeaseLiability"
    usd = {unit.attrib["id"] for unit in document.iter(INSTANCE + "unit")
           if [child.text for child in unit] == ["iso4217:USD"]}
    disclosures = [
        ("", lease_tag, period, node) for node in document.iter(IX + "nonFraction")
        if local_name(node) == lease_tag and contexts.get(node.get("contextRef")) == period
        and node.get("unitRef") in usd
    ]
    for evidence in fact_evidence(disclosures, nonnegative=True):
        yield make_fact(filing, source, concept, period, "consolidated", "historical_balance_sheet", evidence)


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
        if scope:
            for evidence in fact_evidence(cfo_rows):
                yield make_fact(filing, source, "operating_cash_flow", period, *scope, evidence)
            for evidence in fact_evidence(cash_capex, nonnegative=True):
                yield make_fact(filing, source, "cash_capex_outflow", period, *scope, evidence, sign=-1)


def income_facts(filing, source, entries, cash_flows):
    revenue_label = {"DOV": "revenue", "ITW": "operating revenue", "ROK": ""}[filing["ticker"]]
    flow_contexts = dict.fromkeys(
        (flow["period_start"], flow["period_end"], flow["reporting_basis"], flow["scope_key"])
        for flow in cash_flows if flow["concept"] == "operating_cash_flow"
    )
    for start, end, basis, scope in flow_contexts:
        period = (date.fromisoformat(start), date.fromisoformat(end))
        rows = [row for row in entries if row[2] == period]
        if basis == "continuing_operations":
            income_tag, income_label = "IncomeLossFromContinuingOperations", "earnings from continuing operations"
        elif filing["ticker"] == "DOV":
            if any(row[1] == NONCONTROLLING_INCOME for row in rows):
                continue
            income_tag, income_label = "NetIncomeLoss", "net earnings"
        else:
            income_tag, income_label = "ProfitLoss", "net income"
        income_rows = [row for row in rows if row[:2] == (income_label, income_tag)]
        if not income_rows and basis == "continuing_operations":
            # The explicit continuing-operations earnings line also confirms revenue's presentation basis.
            continue
        revenue_rows = [row for row in rows if row[0] == revenue_label and row[1] in REVENUE_TAGS]
        for evidence in fact_evidence(revenue_rows):
            yield make_fact(filing, source, "revenue", period, basis, scope, evidence)
        for evidence in fact_evidence(income_rows):
            yield make_fact(filing, source, "net_income", period, basis, scope, evidence)


def qualify(filing, source, supported_ends):
    document = load_document(filing, source)
    contexts = entity_contexts(document, filing["cik"])
    end = date.fromisoformat(filing["report_end"])
    fiscal_year = int(filing["fiscal_year"])
    start = date(fiscal_year - 1, 10, 1) if filing["ticker"] == "ROK" else date(fiscal_year, 1, 1)
    as_of = (None, end)
    cumulative = (start, end)
    balances, flows, earnings = [], [], []
    for table in statement_rows(document, contexts):
        tags = {(entry[1], entry[2]) for entry in table}
        if all((tag, as_of) in tags for tag in ("Assets", "AssetsCurrent", "LiabilitiesCurrent")):
            balances.append(table)
        cumulative_tags = {tag for tag, period in tags if period == cumulative}
        if cumulative_tags & {TOTAL_CFO, CONTINUING_CFO} and (
            cumulative_tags & CAPEX or (cumulative_tags & INVESTING_TOTALS and cumulative_tags & FINANCING_TOTALS)
        ):
            flows.append(table)
        if cumulative_tags & REVENUE_TAGS and cumulative_tags & INCOME_TAGS and cumulative_tags & INCOME_ANCHORS:
            earnings.append(table)
    for statement, tables in (("balance sheets", balances), ("cash-flow statements", flows),
                              ("income statements", earnings)):
        if len(tables) > 1:
            raise ValueError(f"Ambiguous primary {statement} in {filing['accession']}")
    facts = []
    if balances:
        facts.extend(balance_facts(filing, source, balances[0], as_of, document, contexts))
    if flows:
        cash_flows = list(flow_facts(filing, source, flows[0], cumulative, supported_ends))
        facts.extend(cash_flows)
        if earnings:
            facts.extend(income_facts(filing, source, earnings[0], cash_flows))
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


def conflicting_concepts(facts):
    amounts = defaultdict(set)
    for fact in facts:
        context = (fact["concept"], fact["period_start"], fact["period_end"], fact["reporting_basis"], fact["scope_key"])
        amounts[context].add(Decimal(fact["value"]))
    return {context[0] for context, values in amounts.items() if len(values) > 1}


def coverage_status(required, concepts, conflicts, available, missing):
    if required & conflicts:
        return "conflicting_observations"
    return available if required <= concepts else missing


def report(records):
    output = csv.writer(sys.stdout, lineterminator="\n")
    output.writerow([
        "ticker", "window", "fiscal_year", "fiscal_period", "report_end", "accession", "statement_url",
        "statement_sha256", "liquidity_inputs", "reported_debt_inputs", "lease_adjustment",
        "cash_source_tag", "cash_flow_inputs", "cash_flow_basis", "cash_flow_scope", "capex_source_tag",
        "comparative_cash_flow_observations", "revenue_inputs", "net_income_inputs", "borrowing_debt_basis",
    ])
    for filing, source, facts in records:
        current = [fact for fact in facts if fact["period_end"] == filing["report_end"]]
        conflicts = conflicting_concepts(current)
        by_concept = {fact["concept"]: fact for fact in current if fact["concept"] not in conflicts}
        concepts = by_concept.keys()
        liquidity = {"current_assets", "current_liabilities", "cash_and_equivalents"}
        debt = {"short_term_debt", "noncurrent_debt"}
        if filing["ticker"] == "ROK":
            debt.add("current_portion_long_term_debt")
        flow = by_concept.get("operating_cash_flow", {})
        lease = {"finance_lease_liabilities"}
        lease_basis = lease | {"finance_lease_liabilities_outside_debt"}
        cash_flow = {"operating_cash_flow", "cash_capex_outflow"}
        debt_basis = "unverified"
        if conflicts & (debt | lease_basis):
            debt_basis = "conflicting_observations"
        elif debt <= concepts:
            if "finance_lease_liabilities" in concepts:
                debt_basis = "finance_leases_deducted"
            elif "finance_lease_liabilities_outside_debt" in concepts:
                debt_basis = "finance_leases_outside_debt"
        output.writerow([
            *(filing[key] for key in ("ticker", "window", "fiscal_year", "fiscal_period", "report_end", "accession")),
            filing["filing_url"], source["sha256"] if source else "",
            coverage_status(liquidity, concepts, conflicts, "qualified", "missing_statement_inputs"),
            coverage_status(debt, concepts, conflicts, "qualified_reported_basis", "missing_statement_inputs"),
            coverage_status(debt | lease, concepts, conflicts, "qualified", "unverified"),
            by_concept.get("cash_and_equivalents", {}).get("source_tag", ""),
            coverage_status(cash_flow, concepts, conflicts, "qualified", "missing_compatible_inputs"),
            flow.get("reporting_basis", ""),
            flow.get("scope_key", ""), by_concept.get("cash_capex_outflow", {}).get("source_tag", ""),
            sum(fact["period_end"] != filing["report_end"]
                and fact["concept"] in {"operating_cash_flow", "cash_capex_outflow"} for fact in facts),
            coverage_status({"revenue"}, concepts, conflicts, "qualified", "missing_compatible_inputs"),
            coverage_status({"net_income"}, concepts, conflicts, "qualified", "missing_compatible_inputs"),
            debt_basis,
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
