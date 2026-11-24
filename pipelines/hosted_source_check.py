"""Check and archive new SEC and Treasury inputs without publishing a dataset."""

import argparse
import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from pipelines import refresh_dataset
from pipelines.sec_http import ACCESS_BLOCKS, BLOCK_COOLDOWN, EdgarDownloadError


def connect():
    host = os.environ["FILING_DB_HOST"]
    user = os.environ["FILING_SOURCE_DB_USER"]
    password = Path(os.environ["FILING_SOURCE_DB_PASSWORD_FILE"]).read_text(encoding="ascii").rstrip("\n")
    if (not re.fullmatch(r"[A-Za-z0-9.-]+", host) or not re.fullmatch(r"(?:ftf_source_checker|ftf_source_runner_[ab])(?:\.[a-z0-9]+)?", user)
            or not re.fullmatch(r"[a-f0-9]{64}", password)):
        raise ValueError("Invalid hosted source-check database settings")
    return psycopg.connect(
        host=host, dbname="postgres", user=user, password=password,
        sslmode="verify-full", sslrootcert=os.environ["FILING_DB_CA_FILE"],
        gssencmode="disable", connect_timeout=5,
    )


def acquire(simulate_failure):
    with connect() as connection:
        connection.execute("SET LOCAL statement_timeout = '8s'")
        row = connection.execute(
            "SELECT catalog, refresh_status->'sources' FROM ftf_release.state WHERE singleton FOR UPDATE"
        ).fetchone()
        if row is None:
            raise ValueError("No reviewed release is available")
        catalog, previous = row
        previous = previous or {}
        started = refresh_dataset.now()
        if previous.get("result") == "running":
            opened = datetime.fromisoformat(previous["started_at"])
            if started - opened <= refresh_dataset.RUN_LIMIT:
                refresh_dataset.emit("refresh_skipped", channel="sources", reason="lease_busy")
                return None
        if not simulate_failure and previous.get("sec_http_status") in ACCESS_BLOCKS:
            blocked_at = datetime.fromisoformat(previous["finished_at"])
            if (started - blocked_at).total_seconds() < BLOCK_COOLDOWN:
                refresh_dataset.emit("refresh_skipped", channel="sources", reason="sec_cooldown")
                return None
        attempt = {
            "run_id": uuid4().hex, "started_at": started.isoformat(),
            "last_success_at": previous.get("last_success_at"), "result": "running",
        }
        connection.execute(
            "UPDATE ftf_release.state SET refresh_status = jsonb_set(refresh_status, '{sources}', %s) WHERE singleton",
            [Jsonb(attempt)],
        )
        return catalog, attempt


def finish(attempt, result, **evidence):
    completed = refresh_dataset.now().isoformat()
    status = dict(attempt, result=result, finished_at=completed, **evidence)
    if result != "failed":
        status["last_success_at"] = completed
    with connect() as connection:
        connection.execute("SET LOCAL statement_timeout = '8s'")
        changed = connection.execute(
            """UPDATE ftf_release.state SET refresh_status = jsonb_set(refresh_status, '{sources}', %s)
               WHERE singleton AND refresh_status #>> '{sources,run_id}' = %s""",
            (Jsonb(status), attempt["run_id"]),
        ).rowcount
        if changed != 1:
            raise ValueError("The hosted source-check lease changed")


class CloudArchive:
    def __init__(self):
        bucket = os.environ["FILING_ARCHIVE_BUCKET"]
        if not re.fullmatch(r"[a-z0-9-]{3,63}", bucket):
            raise ValueError("Invalid hosted archive bucket")
        self.bucket = bucket
        with urlopen(Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        ), timeout=5) as response:
            self.token = json.load(response)["access_token"]

    def upload(self, key, body, content_type):
        parameters = urlencode({"uploadType": "media", "name": key, "ifGenerationMatch": 0})
        address = f"https://storage.googleapis.com/upload/storage/v1/b/{quote(self.bucket, safe='')}/o?{parameters}"
        try:
            with urlopen(Request(address, data=body, headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": content_type,
            }), timeout=25) as response:
                response.read()
        except HTTPError as error:
            if error.code != 412:
                raise
            error.close()

    def payload(self, content, extension):
        digest = hashlib.sha256(content).hexdigest()
        key = f"sources/{digest}.{extension}"
        self.upload(key, content, "application/octet-stream")
        return {"sha256": digest, "storage_key": key, "byte_count": len(content)}


def check(simulate_failure=False):
    claim = acquire(simulate_failure)
    if claim is None:
        return
    catalog, attempt = claim
    run_id = attempt["run_id"]
    active = catalog["active_version"]
    refresh_dataset.emit("refresh_started", channel="sources", run_id=run_id, active_version=active)
    try:
        if simulate_failure:
            raise ValueError("Source-check failure drill")
        newest = catalog["versions"][-1]
        archive = CloudArchive()
        sec, count = refresh_dataset.check_sec(date.fromisoformat(newest["sec_filing_cutoff"]), archive=archive.payload)
        cutoff = date.fromisoformat(newest["treasury_window"][1])
        with TemporaryDirectory(prefix="ftf-treasury-") as temp:
            treasury, latest = refresh_dataset.check_treasury(Path(temp), cutoff, archive=archive.payload)
        archive.upload(
            f"sources/checks/{run_id}.json",
            json.dumps({"reviewed_version": newest["version"], "sec": sec, "treasury": treasury}).encode(),
            "application/json",
        )
        result = "review_required" if count or latest > cutoff else "ok"
        fields = {"active_version": active, "new_sec_filings": count, "treasury_latest": latest.isoformat()}
        finish(attempt, result, **fields)
    except Exception as error:
        status = error.status if isinstance(error, EdgarDownloadError) else None
        try:
            finish(attempt, "failed", active_version=active, sec_http_status=status)
        finally:
            refresh_dataset.emit(
                "refresh_failed", "ERROR", channel="sources", run_id=run_id, active_version=active,
                error_type=type(error).__name__, sec_http_status=status, drill=simulate_failure,
            )
        raise RuntimeError("Hosted source check failed") from None
    refresh_dataset.emit(
        "refresh_completed", "WARNING" if result == "review_required" else "INFO",
        channel="sources", run_id=run_id, result=result, **fields,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulate-failure", action="store_true", help="Exercise monitoring without contacting a source")
    args = parser.parse_args()
    contact_file = os.environ.get("FILING_SEC_CONTACT_FILE")
    if contact_file:
        os.environ["SEC_CONTACT_EMAIL"] = Path(contact_file).read_text(encoding="ascii").strip()
    check(args.simulate_failure)


if __name__ == "__main__":
    main()
