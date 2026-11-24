"""Check source coverage, refresh reviewed data, and recover local snapshots."""

import argparse
import json
import re
import shutil
import signal
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from zoneinfo import ZoneInfo

from pipelines import backfill_sec, expand_cohort, treasury_history
from pipelines import publish_dataset as publication
from pipelines.load_pilot import archive_payload
from pipelines.sec_http import download_edgar, sec_contact

STATUS = "refresh-status.json"
BACKUP = "backup.json"
EASTERN = ZoneInfo("America/New_York")
COVERAGE_LIMIT_DAYS = 5
CHECK_LIMIT = timedelta(hours=36)
RUN_LIMIT = timedelta(minutes=15)


def now():
    return datetime.now(timezone.utc)


def read_status(directory):
    try:
        status = json.loads((directory / STATUS).read_bytes())
        return status if isinstance(status, dict) else {}
    except (OSError, ValueError):
        return {}


def public_attempt(value, timestamp):
    if not isinstance(value, dict):
        return "unknown", None, None
    status = value.get("result")
    if status not in ("running", "ok", "review_required", "failed"):
        return "unknown", None, None
    try:
        attempted = datetime.fromisoformat(value["started_at"])
        last_ok = datetime.fromisoformat(value["last_success_at"]) if value.get("last_success_at") else None
        if (attempted.utcoffset() is None or attempted > timestamp
                or (last_ok and (last_ok.utcoffset() is None or last_ok > timestamp))):
            raise ValueError("Invalid status timestamp")
    except (ValueError, KeyError, TypeError):
        return "unknown", None, None
    if status == "running" and timestamp - attempted > RUN_LIMIT:
        status = "failed"
    if status == "ok" and timestamp - attempted > CHECK_LIMIT:
        status = "overdue"
    return status, attempted, last_ok


def health(directory, filing_cutoff, treasury_end, *, timestamp=None):
    return health_from_status(read_status(directory), filing_cutoff, treasury_end, timestamp=timestamp)


def health_from_status(state, filing_cutoff, treasury_end, *, timestamp=None):
    timestamp = timestamp or now()
    today = timestamp.astimezone(EASTERN).date()
    source_status, source_attempt, source_success = public_attempt(state.get("sources"), timestamp)
    refresh_status, refresh_attempt, refresh_success = public_attempt(state.get("publication"), timestamp)
    return {
        "source_status": source_status, "source_attempt_at": source_attempt, "source_success_at": source_success,
        "source_check_overdue": source_success is not None and timestamp - source_success > CHECK_LIMIT,
        "publication_status": "ok" if refresh_status == "overdue" else refresh_status,
        "publication_attempt_at": refresh_attempt, "publication_success_at": refresh_success,
        "filing_coverage_stale": (today - filing_cutoff).days >= COVERAGE_LIMIT_DAYS,
        "treasury_coverage_stale": (today - treasury_end).days >= COVERAGE_LIMIT_DAYS,
    }


def emit(event, severity="INFO", **fields):
    print(json.dumps({"event": event, "severity": severity, **fields}, sort_keys=True), flush=True)


def run_attempt(directory, channel, operation):
    with publication.publication_lock(directory):
        state = read_status(directory)
        previous = state.get(channel)
        previous_success = previous.get("last_success_at") if isinstance(previous, dict) else None
        started = now().isoformat()
        attempt = {"run_id": uuid4().hex, "started_at": started,
                   "last_success_at": previous_success, "result": "running"}
        state[channel] = attempt
        publication.write_json(directory / STATUS, state)
        emit("refresh_started", channel=channel, run_id=attempt["run_id"])
        try:
            record = publication.catalog_entry(publication.read_catalog(directory))
            result, fields = operation(record)
            attempt.update(result=result, finished_at=now().isoformat(), **fields)
            if result in ("ok", "review_required"):
                attempt["last_success_at"] = attempt["finished_at"]
            publication.write_json(directory / STATUS, state)
        except BaseException:
            attempt.update(result="failed", finished_at=now().isoformat(), last_success_at=previous_success)
            publication.write_json(directory / STATUS, state)
            emit("refresh_failed", "ERROR", channel=channel, run_id=attempt["run_id"])
            raise
        emit("refresh_completed", "WARNING" if result == "review_required" else "INFO",
             channel=channel, run_id=attempt["run_id"], result=result, **fields)
        return attempt


def check_sec(cutoff, *, archive=archive_payload):
    contact = sec_contact()
    captures = []
    later = set()
    for cik, *_ in (*backfill_sec.ISSUERS, *expand_cohort.ISSUERS):
        url = backfill_sec.endpoint(cik, "sec_submissions")
        content, retrieved_at = download_edgar(url, contact, backfill_sec.MAX_BYTES)
        document = json.loads(content)
        if str(document["cik"]).zfill(10) != cik:
            raise ValueError("SEC response has the wrong issuer")
        inventory = document["filings"]
        recent = inventory["recent"]
        if not recent["accessionNumber"] or any(
            date.fromisoformat(part["filingTo"]) > cutoff for part in inventory["files"]
        ):
            raise ValueError("Recent SEC inventory does not cover the required checking window")
        for accession, form, filed in zip(recent["accessionNumber"], recent["form"], recent["filingDate"], strict=True):
            if form in backfill_sec.FORMS and date.fromisoformat(filed) > cutoff:
                if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
                    raise ValueError("Invalid accession in SEC response")
                later.add((cik, accession))
        fields = backfill_sec.capture(cik, "sec_submissions", url, retrieved_at, content, archive=archive)
        captures.append(fields)
    return captures, len(later)


def check_treasury(directory, cutoff, *, archive=archive_payload):
    today = now().astimezone(EASTERN).date()
    if not 0 <= today.year - cutoff.year <= 1:
        raise ValueError("Treasury source check requires a recent reviewed baseline")
    captures = []
    newest = None
    for year in range(cutoff.year, today.year + 1):
        url = treasury_history.annual_url(year)
        with TemporaryDirectory(prefix=".treasury-", dir=directory) as temp:
            body = Path(temp) / "response.xml"
            subprocess.run([
                "curl", "--disable", "--silent", "--show-error", "--fail", "--proto", "=https",
                "--connect-timeout", "10", "--max-time", "35", "--retry", "1", "--retry-max-time", "40",
                "--max-filesize", str(treasury_history.MAX_BYTES), "--output", str(body), "--", url,
            ], check=True, capture_output=True)
            retrieved_at = now().isoformat()
            content = body.read_bytes()
        if not content or len(content) > treasury_history.MAX_BYTES:
            raise ValueError("Unexpected Treasury response size")
        curves = treasury_history.treasury_curves(content)
        if any(day.year != year or day > today for day in curves):
            raise ValueError("Treasury response has an invalid observation date")
        latest = max(curves)
        newest = max(newest, latest) if newest else latest
        captures.append({"year": year, "source_url": url, "retrieved_at": retrieved_at,
                         **archive(content, "xml")})
    if newest < cutoff:
        raise ValueError("Treasury feed does not reach the published coverage date")
    return captures, newest


def check_sources(directory):
    def check(record):
        # Use the newest qualified coverage even when the serving pointer is rolled back.
        newest = publication.read_catalog(directory)["versions"][-1]
        sec_cutoff = date.fromisoformat(newest["sec_filing_cutoff"])
        treasury_end = date.fromisoformat(newest["treasury_window"][1])
        sec, pending = check_sec(sec_cutoff)
        treasury, latest = check_treasury(directory, treasury_end)
        publication.write_json(directory / "latest-source-check.json", {
            "reviewed_version": newest["version"], "sec": sec, "treasury": treasury,
        })
        return ("review_required" if pending or latest > treasury_end else "ok"), {
            "active_version": record["version"], "new_sec_filings": pending, "treasury_latest": latest.isoformat(),
        }

    return run_attempt(directory, "sources", check)


def refresh(directory, manifests_from=None):
    from apps.api.prepare_local import prepare_record

    def apply_reviewed(record):
        if (directory / BACKUP).exists():
            raise ValueError("Use a working catalog to refresh a preserved backup")
        folder, details = publication.snapshot_details(directory, record["snapshot_id"])
        if manifests_from is None:
            prepare_record(directory, record, details)
            return "ok", {"active_version": record["version"], "publication": "verified"}
        manifests = {name: manifests_from / filename for name, (_, filename) in publication.IMPORTS.items()}
        cohort = manifests_from / publication.COHORT_FILENAME
        if cohort.exists() or "cohort" in details["input_hashes"]:
            manifests["cohort"] = cohort
        outcome, selected = publication.publish_locked(directory, manifests, prepare=prepare_record)
        return "ok", {"active_version": selected["version"], "publication": outcome}

    return run_attempt(directory, "publication", apply_reviewed)


def verify_backup(directory):
    manifest = json.loads((directory / BACKUP).read_bytes())
    if manifest != {"format_version": 1, "catalog_sha256": publication.file_digest(directory / "catalog.json")}:
        raise ValueError("Backup catalog checksum does not match")
    catalog = publication.read_catalog(directory)
    publication.catalog_entry(catalog)
    for record in catalog["versions"]:
        _, details = publication.snapshot_details(directory, record["snapshot_id"])
        if any(record[key] != details[key] for key in ("snapshot_id", "sec_filing_cutoff", "treasury_window", "row_counts")):
            raise ValueError("Backup catalog metadata does not match an archived snapshot")
    return catalog


def backup(directory, destination):
    if destination.is_relative_to(directory) or destination.exists() or destination.is_symlink():
        raise ValueError("Choose a new backup directory outside the source catalog")
    with publication.publication_lock(directory):
        catalog = publication.read_catalog(directory)
        active = publication.catalog_entry(catalog)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Also serialize writers targeting this destination, even from other source catalogs.
        with publication.publication_lock(destination.parent):
            if destination.exists() or destination.is_symlink():
                raise ValueError("The backup destination already exists")
            with TemporaryDirectory(prefix=".backup-", dir=destination.parent) as temp:
                stage = Path(temp)
                (stage / "snapshots").mkdir()
                for record in catalog["versions"]:
                    folder, _ = publication.snapshot_details(directory, record["snapshot_id"])
                    shutil.copytree(folder, stage / "snapshots" / folder.name)
                shutil.copyfile(directory / "catalog.json", stage / "catalog.json")
                publication.write_json(stage / BACKUP, {
                    "format_version": 1, "catalog_sha256": publication.file_digest(stage / "catalog.json"),
                })
                verify_backup(stage)
                stage.rename(destination)
    return {"backup_active_version": active["version"], "versions": len(catalog["versions"])}


def activate(directory, version):
    from apps.api.prepare_local import prepare_record

    with publication.publication_lock(directory):
        if (directory / BACKUP).exists():
            raise ValueError("Use a working catalog to change the active version")
        catalog = publication.read_catalog(directory)
        record = publication.catalog_entry(catalog, version)
        _, details = publication.snapshot_details(directory, record["snapshot_id"])
        prepare_record(directory, record, details)
        previous = catalog["active_version"]
        if previous != version:
            catalog["active_version"] = version
            publication.write_json(directory / "catalog.json", catalog)
        return {"previous_version": previous, "active_version": version}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=publication.DATASETS)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("check-sources", help="Capture official source signals for review")
    apply = actions.add_parser("refresh", help="Verify the active release or publish reviewed manifests")
    apply.add_argument("--manifests-from", type=Path)
    save = actions.add_parser("backup", help="Copy and verify all published snapshot archives")
    save.add_argument("--destination", required=True, type=Path)
    recover = actions.add_parser("restore", help="Restore a verified backup into a new database")
    recover.add_argument("--version")
    recover.add_argument("--database", required=True)
    switch = actions.add_parser("activate", help="Activate a verified published version")
    switch.add_argument("--version", required=True)
    actions.add_parser("status", help="Show active version and freshness status")
    args = parser.parse_args()
    directory = args.directory.resolve()

    def terminate(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    try:
        if args.action == "check-sources":
            check_sources(directory)
        elif args.action == "refresh":
            refresh(directory, args.manifests_from)
        elif args.action == "backup":
            emit("backup_completed", **backup(directory, args.destination.resolve()))
        elif args.action == "restore":
            verify_backup(directory)
            record = publication.restore(directory, args.version, args.database)
            emit("restore_completed", version=record["version"], row_counts=record["row_counts"])
        elif args.action == "activate":
            emit("activation_completed", **activate(directory, args.version))
        else:
            record = publication.catalog_entry(publication.read_catalog(directory))
            data = health(directory, date.fromisoformat(record["sec_filing_cutoff"]),
                          date.fromisoformat(record["treasury_window"][1]))
            public = {key: value.isoformat() if isinstance(value, datetime) else value for key, value in data.items()}
            emit("refresh_status", active_version=record["version"], **public)
    except publication.PublicationBusy:
        if args.action in {"check-sources", "refresh"}:
            emit("refresh_skipped", action=args.action, reason="catalog_busy")
            return 0
        emit("operation_failed", "ERROR", action=args.action, error_type="PublicationBusy")
        return 1
    except (Exception, KeyboardInterrupt) as error:
        emit("operation_failed", "ERROR", action=args.action, error_type=type(error).__name__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
