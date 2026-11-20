"""Local catalog selection and read-only PostgreSQL connections."""

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Literal

import psycopg
from psycopg.rows import dict_row

from pipelines.publish_dataset import DATASETS, ROOT, read_catalog

PASSWORD_FILE = ROOT / ".local/phase2-api/password"
READER = "ftf_phase2_reader"
Mode = Literal["latest", "filed_by", "platform_snapshot"]
Duration = Literal["annual", "quarter", "ttm"]


@dataclass(frozen=True)
class Dataset:
    version: str
    snapshot_id: str
    methodology_version: str
    filing_cutoff: date
    published_at: str
    treasury_start: date
    treasury_end: date
    annual_and_revisions: bool
    validation_checks: tuple[str, ...]
    row_counts: dict[str, int]

    @property
    def database(self):
        return f"ftf_api_{self.version}_{self.snapshot_id[:12]}"


def catalog_datasets():
    catalog = read_catalog(DATASETS)
    datasets = []
    for entry in catalog["versions"]:
        version, snapshot_id = entry["version"], entry["snapshot_id"]
        if not re.fullmatch(r"v[0-9]{4,}", version) or not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise ValueError("Invalid local snapshot identity")
        details = json.loads((DATASETS / "snapshots" / snapshot_id / "snapshot.json").read_bytes())
        if details["snapshot_id"] != snapshot_id:
            raise ValueError("Snapshot metadata does not match the local catalog")
        datasets.append(Dataset(
            version, snapshot_id, details["methodology_sha256"],
            date.fromisoformat(entry["sec_filing_cutoff"]), entry["published_at"],
            *map(date.fromisoformat, entry["treasury_window"]),
            "database/migrations/008_fiscal_period_metrics.sql" in details["methodology_files"],
            tuple(details["validation_checks"]), details["row_counts"],
        ))
    return catalog["active_version"], datasets


def db_port():
    configured = os.environ.get("FILING_POSTGRES_PORT")
    if configured is None:
        for line in (ROOT / ".env").read_text().splitlines():
            match = re.fullmatch(r"\s*FILING_POSTGRES_PORT\s*=\s*['\"]?([0-9]+)['\"]?\s*(?:#.*)?", line)
            if match:
                configured = match[1]
    port = int(configured or 55432)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid PostgreSQL port")
    return port


@contextmanager
def reader(dataset):
    with psycopg.connect(
        host="127.0.0.1", port=db_port(), dbname=dataset.database,
        user=READER, password=PASSWORD_FILE.read_text().strip(),
        connect_timeout=3, row_factory=dict_row,
        options="-c default_transaction_read_only=on -c statement_timeout=6000 -c TimeZone=UTC",
    ) as connection:
        stamp = connection.execute(
            "SELECT snapshot_id, methodology_version FROM app_snapshot.identity"
        ).fetchone()
        if not stamp or (stamp["snapshot_id"], stamp["methodology_version"]) != (
            dataset.snapshot_id, dataset.methodology_version,
        ):
            raise ValueError("Prepared database identity does not match the selected snapshot")
        yield connection
