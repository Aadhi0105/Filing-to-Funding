"""Restore a private Cloud Storage backup into a disposable PostgreSQL instance."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from urllib.parse import quote
from urllib.request import Request, urlopen

from pipelines import publish_dataset, refresh_dataset


def download_backup(destination):
    bucket = os.environ["FILING_ARCHIVE_BUCKET"]
    prefix = os.environ["FILING_BACKUP_PREFIX"]
    if not re.fullmatch(r"[a-z0-9-]{3,63}", bucket) or not re.fullmatch(r"backups/v[0-9]{4,8}-[0-9a-f]{16}", prefix):
        raise ValueError("Invalid hosted backup location")
    with urlopen(Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    ), timeout=5) as response:
        token = json.load(response)["access_token"]

    def download(relative):
        key = quote(f"{prefix}/{relative}", safe="")
        request = Request(
            f"https://storage.googleapis.com/download/storage/v1/b/{quote(bucket, safe='')}/o/{key}?alt=media",
            headers={"Authorization": f"Bearer {token}"},
        )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(request, timeout=30) as response, target.open("xb") as output:
            shutil.copyfileobj(response, output)
        return target

    manifest = json.loads(download("backup.json").read_bytes())
    actual = publish_dataset.file_digest(download("catalog.json"))
    if manifest.get("catalog_sha256") != actual:
        raise ValueError("Recovered catalog checksum differs")
    catalog = publish_dataset.read_catalog(destination)
    for record in catalog["versions"]:
        snapshot_id = record["snapshot_id"]
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise ValueError("Invalid archive snapshot identity")
        root = f"snapshots/{snapshot_id}"
        details = json.loads(download(f"{root}/snapshot.json").read_bytes())
        for _, filename in publish_dataset.IMPORTS.values():
            download(f"{root}/{filename}")
        if "cohort" in details["input_hashes"]:
            download(f"{root}/{publish_dataset.COHORT_FILENAME}")
        download(f"{root}/snapshot.dump")
    return refresh_dataset.verify_backup(destination)


def restore(working, backup, catalog):
    socket_dir = working / "socket"
    socket_dir.mkdir(mode=0o700)
    data = working / "postgres"
    subprocess.run(["initdb", "-D", data, "--auth-local=trust", "--auth-host=reject"], check=True, stdout=subprocess.DEVNULL)
    control = ["pg_ctl", "-D", data]
    options = f"-c listen_addresses='' -c unix_socket_directories='{socket_dir}' -c shared_buffers=32MB"
    subprocess.run([*control, "-l", working / "postgres.log", "-o", options, "-w", "start"], check=True)
    try:
        client = ["-h", socket_dir, "-U", "postgres"]
        current = publish_dataset.catalog_entry(catalog)
        archive = next(record for record in reversed(catalog["versions"]) if record["version"] != current["version"])
        for label, record in (("archived", archive), ("active", current)):
            database = f"recovered_{label}"
            folder, details = publish_dataset.snapshot_details(backup, record["snapshot_id"])
            subprocess.run(["createdb", *client, "--template", "template0", database], check=True)
            subprocess.run([
                "pg_restore", *client, "--no-owner", "--no-privileges", "--single-transaction",
                "--exit-on-error", "-d", database, folder / "snapshot.dump",
            ], check=True)
            psql = ["psql", *client, "-d", database, "-X", "-v", "ON_ERROR_STOP=1"]
            counts = subprocess.check_output([*psql, "-Atq", "-c", publish_dataset.COUNTS_SQL], text=True)
            if json.loads(counts) != record["row_counts"] or details["snapshot_id"] != record["snapshot_id"]:
                raise ValueError(f"Recovered identity or counts differ for {record['version']}")
            checks = ["filing_revisions", "treasury_history", "fiscal_period_metrics"]
            if "cohort" in details["input_hashes"]:
                checks += ["cohort_expansion", "sec_statement_conflicts"]
            for check in checks:
                subprocess.run([*psql, "-q", "-f", f"database/tests/{check}.sql"], check=True, stdout=subprocess.DEVNULL)
            refresh_dataset.emit(
                "snapshot_recovered", version=record["version"], snapshot_id=record["snapshot_id"],
                row_counts=record["row_counts"], checks=checks,
            )
    finally:
        subprocess.run([*control, "-m", "fast", "-w", "stop"], check=True)


def main():
    started = monotonic()
    with TemporaryDirectory(prefix="ftf-recovery-") as directory:
        working = Path(directory)
        backup = working / "backup"
        catalog = download_backup(backup)
        restore(working, backup, catalog)
    refresh_dataset.emit("hosted_recovery_completed", seconds=round(monotonic() - started, 2), versions_verified=2)


if __name__ == "__main__":
    main()
