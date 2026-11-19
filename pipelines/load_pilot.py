"""Import accession-linked SEC and Treasury samples from reviewed extracts."""

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "testdata" / "reconciled"
ARCHIVE_DIR = ROOT / ".local" / "source-cache"


def archive_review(filename, expected_format):
    content = (REVIEW_DIR / filename).read_bytes()
    review = json.loads(content)
    if review["format"] != expected_format:
        raise ValueError(f"Unexpected source format in {filename}")

    digest = hashlib.sha256(content).hexdigest()
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVE_DIR / f"{digest}.json"
    if archive.exists():
        if archive.read_bytes() != content:
            raise ValueError(f"Archived review does not match its digest: {archive.name}")
    else:
        with NamedTemporaryFile(dir=ARCHIVE_DIR, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(content)
                handle.close()
                os.replace(temporary, archive)
            finally:
                temporary.unlink(missing_ok=True)

    return review, {
        "sha256": digest,
        "storage_key": archive.relative_to(ROOT).as_posix(),
        "byte_count": len(content),
    }


def sec_documents(review, archived):
    accessions = set()
    for filing_no, report in enumerate(review["filings"]):
        accession = report["accession"]
        if accession in accessions:
            raise ValueError(f"Repeated accession in the pilot review: {accession}")
        accessions.add(accession)
        ticker = report["ticker"]
        issuer = {"ticker": ticker, **review["issuers"][ticker]}
        period = report["period"]
        scale = report["usd_scale"]
        decimals = {1000: "-3", 1000000: "-6"}[scale]
        facts = []
        for section_no, statement in enumerate(report["statements"]):
            for line_no, (concept, label, amount) in enumerate(statement["lines"]):
                if type(amount) is not int:
                    raise ValueError(f"Expected a whole displayed amount for {accession} / {label}")
                facts.append({
                    "concept": concept,
                    "period_start": statement.get("starts_on"),
                    "period_end": statement.get("ends_on", period["ends_on"]),
                    "reporting_basis": statement["basis"],
                    "scope_key": statement["scope"],
                    "value": amount * scale,
                    "reported_decimals": decimals,
                    "source_locator": f"/filings/{filing_no}/statements/{section_no}/lines/{line_no}",
                })

        yield {
            "source_kind": "sec_filing_review",
            "source_url": report["filing_url"],
            **archived,
            "issuer": issuer,
            "period": period,
            "filing": {
                "accession": accession,
                "form_type": report["form_type"],
                "filed_on": report["filed_on"],
                "accepted_at": report["accepted_at"],
                "acceptance_timezone": "America/New_York" if report["accepted_at"] else None,
            },
            "facts": facts,
        }


def treasury_document(review, archived):
    rates = []
    observations = set()
    for observed_on, *values in review["rows"]:
        for maturity, value in zip(review["maturities_months"], values, strict=True):
            key = (observed_on, maturity)
            if key in observations:
                raise ValueError(f"Repeated date and maturity in the Treasury review: {key}")
            observations.add(key)
            rates.append({
                "observation_date": observed_on,
                "maturity_months": maturity,
                "yield_percent": value,
            })
    return {"source_kind": "treasury_yield_review", "source_url": review["source_url"], **archived, "rates": rates}


def import_script():
    sec, sec_archive = archive_review("sec_pilot.json", "ftf-reviewed-sec-v1")
    treasury, treasury_archive = archive_review("treasury_pilot.json", "ftf-reviewed-treasury-v1")
    sec_rows = list(sec_documents(sec, sec_archive))
    treasury_row = treasury_document(treasury, treasury_archive)
    if not sec_rows or not treasury_row["rates"]:
        raise ValueError("Both reviewed source files must contain pilot observations")

    buffer = io.StringIO()
    buffer.write("BEGIN;\nCREATE TEMP TABLE pilot_input (document jsonb NOT NULL);\n")
    buffer.write("COPY pilot_input (document) FROM STDIN WITH (FORMAT csv);\n")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows([json.dumps(row)] for row in [*sec_rows, treasury_row])
    buffer.write("\\.\n")
    buffer.write((ROOT / "database" / "load_pilot.sql").read_text())
    return buffer.getvalue()


def compose_psql():
    docker = shutil.which("docker") or str(Path.home() / ".docker" / "bin" / "docker")
    if not Path(docker).is_file():
        raise ValueError("Docker CLI unavailable. Start Docker Desktop or pass a psql command after --.")
    return [
        docker, "compose", "--env-file", ".env", "-f", "infrastructure/docker/compose.yaml",
        "exec", "-T", "postgres", "psql", "-U", "filing_to_funding", "-d", "filing_to_funding",
    ]


def main(argv):
    if argv and (argv[0] != "--" or len(argv) < 2):
        raise ValueError("Usage: python3 -m pipelines.load_pilot [-- psql [connection options]]")
    command = argv[1:] if argv else compose_psql()
    subprocess.run(
        [*command, "-X", "-v", "ON_ERROR_STOP=1"],
        cwd=ROOT,
        input=import_script(),
        text=True,
        check=True,
    )


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"Pilot import failed: {error}", file=sys.stderr)
        raise SystemExit(1)
