"""Build, validate, publish, and restore local Filing-to-Funding datasets."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from uuid import uuid4

from pipelines import expand_cohort
from pipelines.backfill_sec import CUTOFF, HISTORY_KIND, MANIFEST as SEC_MANIFEST
from pipelines.load_pilot import ROOT, compose_psql
from pipelines.qualify_sec import MANIFEST as STATEMENT_MANIFEST
from pipelines.treasury_history import MANIFEST as TREASURY_MANIFEST, WINDOW_END, WINDOW_START

DATASETS = ROOT / ".local/datasets"
FORMAT_VERSION = 1
CHECKS = (
    "sec_statement_conflicts",
    "pilot_storage", "pilot_ingestion", "pilot_analytics", "sec_backfill",
    "historical_cash_flow", "financial_ratios", "treasury_history",
    "filing_revisions", "fiscal_period_metrics",
)
IMPORTS = {
    "sec": ("pipelines.backfill_sec", "sec.json"),
    "statements": ("pipelines.qualify_sec", "statements.jsonl"),
    "treasury": ("pipelines.treasury_history", "treasury.json"),
}
COHORT_FILENAME = "cohort.json"
COHORT_CHECKS = ("sec_statement_conflicts", "cohort_expansion")
COUNTS_SQL = """
SELECT json_build_object(
    'issuers', (SELECT count(*) FROM core.issuers),
    'filings', (SELECT count(*) FROM core.filings),
    'qualified_statement_observations', (
        SELECT count(*) FROM core.reported_facts WHERE taxonomy = 'filing-statement-v1'
    ),
    'treasury_observation_dates', (
        SELECT count(DISTINCT observation.observation_date)
        FROM core.treasury_yield_observations AS observation
        JOIN raw.source_fetches AS source ON source.fetch_id = observation.source_fetch_id
        WHERE source.source_kind = 'treasury_daily_par_yields'
    ),
    'treasury_yields', (
        SELECT count(*) FROM core.treasury_yield_observations AS observation
        JOIN raw.source_fetches AS source ON source.fetch_id = observation.source_fetch_id
        WHERE source.source_kind = 'treasury_daily_par_yields'
    )
);
"""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def methodology():
    paths = [
        *ROOT.glob("database/*.sql"),
        *(ROOT / "database/migrations").glob("*.sql"),
        *(ROOT / "database/analytics").rglob("*.sql"),
        *(ROOT / "database/tests").glob("*.sql"),
        *(ROOT / "testdata/reconciled").glob("*.json"),
        *(ROOT / name for name in (
            "docs/sec_filing_inventory.csv", "pipelines/load_pilot.py", "pipelines/backfill_sec.py",
            "pipelines/qualify_sec.py", "pipelines/sec_http.py", "pipelines/treasury_history.py",
            "pipelines/expand_cohort.py", "docs/cohort_expansion_filing_inventory.csv",
            "testdata/cohort_expansion/statement_samples.csv",
        )),
    ]
    return {path.relative_to(ROOT).as_posix(): file_digest(path) for path in sorted(paths)}


def capture_identity(captures):
    watermarks = {}
    inputs = {}
    cohort = captures.get("cohort")
    if cohort is not None:
        bundle = json.loads(cohort)
        expanded_hashes, expanded_watermarks = capture_identity({
            "sec": canonical(bundle["sec"]),
            "statements": b"\n".join(canonical(record) for record in bundle["statements"]),
        })
        if not expanded_watermarks:
            raise ValueError("Missing cohort source watermarks")
        inputs["cohort"] = digest({
            **expanded_hashes, "samples_sha256": bundle["samples_sha256"],
            "inventory_sha256": bundle["inventory_sha256"], "base_snapshot_id": bundle.get("base_snapshot_id"),
        })
    for kind, content in captures.items():
        if kind == "cohort":
            continue
        records = (
            [json.loads(line) for line in content.splitlines() if line.strip()]
            if kind == "statements" else json.loads(content)
        )
        for record in records:
            if kind == "sec":
                key = f"sec:{record['cik']}:{record['source_kind']}"
                if record["source_kind"] == HISTORY_KIND:
                    key += f":{record['source_url']}"
            elif kind == "statements":
                key = f"filing:{record['accession']}"
            else:
                key = f"treasury:{record['year']}"
            timestamp = datetime.fromisoformat(record["retrieved_at"])
            if timestamp.utcoffset() is None or key in watermarks:
                raise ValueError(f"Invalid or duplicate capture watermark for {key}")
            watermarks[key] = {
                "retrieved_at": timestamp.astimezone(timezone.utc).isoformat(timespec="microseconds"),
                "sha256": record["sha256"],
            }
        inputs[kind] = digest(sorted(records, key=canonical))
    if cohort is not None:
        if expanded_watermarks.keys() & watermarks.keys():
            raise ValueError("Expanded and original source captures overlap")
        watermarks.update(expanded_watermarks)
    return inputs, watermarks


def require_current_sources(previous, candidate):
    for key, old in previous.items():
        new = candidate.get(key)
        if new is None and key.startswith("sec:") and f":{HISTORY_KIND}:" in key:
            root_key = f"sec:{key.split(':', 2)[1]}:sec_submissions"
            old_root, new_root = previous.get(root_key), candidate.get(root_key)
            # EDGAR can move reports between files. The new index must change and the
            # normal backfill checks must validate all of its required files and accessions.
            if (old_root and new_root and new_root["retrieved_at"] > old_root["retrieved_at"]
                    and new_root["sha256"] != old_root["sha256"]):
                continue
        if new is None or new["retrieved_at"] < old["retrieved_at"]:
            raise ValueError(f"Candidate source capture is missing or older for {key}")
        if new["retrieved_at"] == old["retrieved_at"] and new["sha256"] != old["sha256"]:
            raise ValueError(f"Conflicting source captures at the same retrieval time for {key}")


def write_json(path, document):
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        staged = Path(handle.name)
        try:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            os.replace(staged, path)
        finally:
            staged.unlink(missing_ok=True)


def read_catalog(directory):
    path = directory / "catalog.json"
    if not path.exists():
        return {"format_version": FORMAT_VERSION, "active_version": None, "versions": []}
    catalog = json.loads(path.read_bytes())
    if catalog["format_version"] != FORMAT_VERSION:
        raise ValueError("Unsupported local dataset catalog format")
    return catalog


def catalog_entry(catalog, version=None):
    selected = version or catalog["active_version"]
    for record in catalog["versions"]:
        if record["version"] == selected:
            return record
    raise ValueError(f"Dataset version {selected} is unavailable" if selected else "No dataset has been published")


def tool_command(tool, *arguments):
    config = compose_psql()
    return [*config[:config.index("psql")], tool, "-U", config[config.index("-U") + 1], *arguments]


def psql_command(database, *arguments):
    return tool_command("psql", "-X", "-v", "ON_ERROR_STOP=1", "-d", database, *arguments)


def run(command, **options):
    return subprocess.run(command, cwd=ROOT, check=True, **options)


def database_counts(database):
    output = run(psql_command(database, "-At", "-c", COUNTS_SQL), stdout=subprocess.PIPE)
    return json.loads(output.stdout)


def remove_database(database):
    subprocess.run(tool_command("dropdb", "--if-exists", database), cwd=ROOT, check=False)


def build_snapshot(stage, captures):
    for name, (_, filename) in IMPORTS.items():
        (stage / filename).write_bytes(captures[name])
    database = "ftf_candidate_" + uuid4().hex
    run(tool_command("createdb", "--template=template0", database))
    try:
        cohort = json.loads(captures["cohort"]) if "cohort" in captures else None
        baseline_id = cohort.get("base_snapshot_id") if cohort else None
        if baseline_id:
            archive, baseline = snapshot_details(stage.parent.parent, baseline_id)
            base_inputs, _ = capture_identity({name: captures[name] for name in IMPORTS})
            sql_files = {name: checksum for name, checksum in methodology().items()
                         if name.startswith("database/") and not name.startswith("database/tests/")}
            base_sql = {name: checksum for name, checksum in baseline["methodology_files"].items()
                        if name.startswith("database/") and not name.startswith("database/tests/")}
            if (base_inputs != baseline["input_hashes"] or base_sql != sql_files
                    or not set(CHECKS).issubset(baseline["validation_checks"])):
                raise ValueError("The cohort baseline must have identical original inputs and database methodology")
            restore_dump(archive, database)
            if database_counts(database) != baseline["row_counts"]:
                raise ValueError("Cohort baseline row counts do not match the archive")
        else:
            run(psql_command(database, "-f", "/workspace/database/migrate.sql"), stdout=subprocess.DEVNULL)
            pilot = [sys.executable, "-B", "-m", "pipelines.load_pilot", "--",
                     *tool_command("psql", "-d", database)]
            run(pilot, stdout=subprocess.DEVNULL)
            for module, filename in IMPORTS.values():
                run([sys.executable, "-B", "-m", module, "--manifest", str(stage / filename), "--database", database],
                    stdout=subprocess.DEVNULL)
        for check in CHECKS:
            run(psql_command(database, "-f", f"/workspace/database/tests/{check}.sql"), stdout=subprocess.DEVNULL)
        if cohort is not None:
            (stage / COHORT_FILENAME).write_bytes(captures["cohort"])
            expand_cohort.load(cohort, database)
            for check in COHORT_CHECKS:
                run(psql_command(database, "-f", f"/workspace/database/tests/{check}.sql"),
                    stdout=subprocess.DEVNULL)
        counts = database_counts(database)
        with (stage / "snapshot.dump").open("wb") as archive:
            run(tool_command("pg_dump", "--format=custom", "--no-owner", "--no-privileges", database),
                stdout=archive)
            archive.flush()
            os.fsync(archive.fileno())
        with (stage / "snapshot.dump").open("rb") as archive:
            run(tool_command("pg_restore", "--list"), stdin=archive, stdout=subprocess.DEVNULL)
        return counts
    finally:
        remove_database(database)


def snapshot_details(directory, snapshot_id):
    if not re.fullmatch(r"[a-f0-9]{64}", snapshot_id):
        raise ValueError("Invalid dataset snapshot ID")
    folder = directory / "snapshots" / snapshot_id
    details = json.loads((folder / "snapshot.json").read_bytes())
    captures = {kind: (folder / filename).read_bytes() for kind, (_, filename) in IMPORTS.items()}
    if "cohort" in details["input_hashes"]:
        captures["cohort"] = (folder / COHORT_FILENAME).read_bytes()
    input_hashes, watermarks = capture_identity(captures)
    identity = {key: details[key] for key in (
        "format_version", "input_hashes", "methodology_sha256", "sec_filing_cutoff", "treasury_window",
    )}
    if (details["snapshot_id"] != snapshot_id or digest(identity) != snapshot_id
            or input_hashes != details["input_hashes"] or watermarks != details["source_watermarks"]
            or digest(details["methodology_files"]) != details["methodology_sha256"]):
        raise ValueError("The archived dataset does not match its recorded inputs")
    if file_digest(folder / "snapshot.dump") != details["dump_sha256"]:
        raise ValueError("The archived dataset does not match its recorded checksum")
    return folder, details


def publish(directory, manifests):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "publish.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("A dataset refresh is already running") from None
        return publish_locked(directory, manifests)


def publish_locked(directory, manifests):
    catalog = read_catalog(directory)
    active = catalog_entry(catalog) if catalog["active_version"] else None
    captures = {name: path.read_bytes() for name, path in manifests.items()}
    inputs, watermarks = capture_identity(captures)
    files = methodology()
    identity = {
        "format_version": FORMAT_VERSION,
        "input_hashes": inputs,
        "methodology_sha256": digest(files),
        "sec_filing_cutoff": CUTOFF.isoformat(),
        "treasury_window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
    }
    snapshot_id = digest(identity)
    if active:
        _, previous = snapshot_details(directory, active["snapshot_id"])
        if active["snapshot_id"] == snapshot_id:
            return "already_active", active
        require_current_sources(previous["source_watermarks"], watermarks)
    if any(entry["snapshot_id"] == snapshot_id for entry in catalog["versions"]):
        raise ValueError("This dataset version has already been superseded")

    snapshots = directory / "snapshots"
    snapshots.mkdir(exist_ok=True)
    folder = snapshots / snapshot_id
    if folder.exists():
        # The last attempt may have stopped after preserving the dump and before updating the catalog.
        _, details = snapshot_details(directory, snapshot_id)
    else:
        with TemporaryDirectory(prefix=".candidate-", dir=snapshots) as staging:
            stage = Path(staging)
            counts = build_snapshot(stage, captures)
            if methodology() != files:
                raise ValueError("Project methodology changed during the refresh")
            details = {
                **identity, "snapshot_id": snapshot_id, "source_watermarks": watermarks,
                "methodology_files": files, "row_counts": counts,
                "validation_checks": list(dict.fromkeys(CHECKS + (COHORT_CHECKS if "cohort" in captures else ()))),
                "dump_sha256": file_digest(stage / "snapshot.dump"),
            }
            write_json(stage / "snapshot.json", details)
            stage.rename(folder)

    record = {
        "version": f"v{len(catalog['versions']) + 1:04d}", "snapshot_id": snapshot_id,
        "published_at": datetime.now(timezone.utc).isoformat(), "row_counts": details["row_counts"],
        "sec_filing_cutoff": details["sec_filing_cutoff"], "treasury_window": details["treasury_window"],
    }
    catalog["versions"].append(record)
    catalog["active_version"] = record["version"]
    write_json(directory / "catalog.json", catalog)
    return "published", record


def restore_dump(folder, database):
    with (folder / "snapshot.dump").open("rb") as archive:
        run(tool_command("pg_restore", "--no-owner", "--no-privileges", "--single-transaction",
                         "--exit-on-error", "-d", database), stdin=archive)


def restore(directory, version, database):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", database):
        raise ValueError("Use a new PostgreSQL database name made of lowercase letters, numbers, and underscores")
    record = catalog_entry(read_catalog(directory), version)
    folder, details = snapshot_details(directory, record["snapshot_id"])
    run(tool_command("createdb", "--template=template0", database))
    try:
        restore_dump(folder, database)
        if database_counts(database) != details["row_counts"]:
            raise ValueError("The restored dataset row counts do not match the published snapshot")
    except BaseException:
        remove_database(database)
        raise
    return {**record, "database": database}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DATASETS, help="Local dataset catalog directory")
    actions = parser.add_subparsers(dest="action", required=True)
    refresh = actions.add_parser("publish", help="Validate and atomically publish an archived candidate")
    refresh.add_argument("--sec-manifest", type=Path, default=SEC_MANIFEST)
    refresh.add_argument("--statement-manifest", type=Path, default=STATEMENT_MANIFEST)
    refresh.add_argument("--treasury-manifest", type=Path, default=TREASURY_MANIFEST)
    refresh.add_argument("--cohort-manifest", type=Path)
    actions.add_parser("status", help="List published dataset versions and the active version")
    replay = actions.add_parser("restore", help="Restore an archived version into a new database")
    replay.add_argument("--version", help="Published version. Defaults to the active version.")
    replay.add_argument("--database", required=True, help="New database for the restored snapshot")
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.action == "publish":
        manifests = {
            "sec": args.sec_manifest, "statements": args.statement_manifest, "treasury": args.treasury_manifest,
        }
        if args.cohort_manifest:
            manifests["cohort"] = args.cohort_manifest
        status, record = publish(directory, manifests)
        result = {"status": status, **record}
    elif args.action == "restore":
        result = restore(directory, args.version, args.database)
    else:
        result = read_catalog(directory)
    print(json.dumps(result, indent=2))


def interrupt(_signum, _frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupt)
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Local dataset operation interrupted") from None
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Local dataset operation failed: {error}") from None
