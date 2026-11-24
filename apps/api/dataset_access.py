"""Dataset selection and read-only PostgreSQL connections."""

import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import psycopg
from psycopg.rows import dict_row

from pipelines.publish_dataset import DATASETS, FORMAT_VERSION, ROOT, read_catalog

PASSWORD_FILE = ROOT / ".local/phase2-api/password"
READER = "ftf_phase2_reader"
API_LOGIN = r"(?:ftf_phase2_reader|ftf_api_reader_[ab])"
HEARTBEAT_LOGIN = r"(?:ftf_phase2_reader|ftf_heartbeat_reader_[ab])"
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


def dataset_from_record(entry, details):
    version, snapshot_id = entry["version"], entry["snapshot_id"]
    methodology = details["methodology_sha256"]
    if (not re.fullmatch(r"v[0-9]{4,}", version) or not re.fullmatch(r"[0-9a-f]{64}", snapshot_id)
            or not re.fullmatch(r"[0-9a-f]{64}", methodology)):
        raise ValueError("Invalid snapshot identity")
    if any(details[key] != entry[key] for key in ("snapshot_id", "sec_filing_cutoff", "treasury_window", "row_counts")):
        raise ValueError("Snapshot metadata does not match the catalog")
    return Dataset(
        version, snapshot_id, methodology, date.fromisoformat(entry["sec_filing_cutoff"]), entry["published_at"],
        *map(date.fromisoformat, entry["treasury_window"]),
        "database/migrations/008_fiscal_period_metrics.sql" in details["methodology_files"],
        tuple(details["validation_checks"]), details["row_counts"],
    )


def catalog_datasets():
    catalog = read_catalog(DATASETS)
    datasets = []
    for entry in catalog["versions"]:
        snapshot_id = entry["snapshot_id"]
        if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
            raise ValueError("Invalid local snapshot identity")
        details = json.loads((DATASETS / "snapshots" / snapshot_id / "snapshot.json").read_bytes())
        datasets.append(dataset_from_record(entry, details))
    return catalog["active_version"], datasets


def catalog_state():
    if not hosted_runtime():
        active, datasets = catalog_datasets()
        return active, datasets, None
    schema = "ftf_release_drill" if os.environ.get("FILING_ROLLBACK_DRILL") == "1" else "ftf_release"
    with hosted_reader("postgres") as connection:
        state = connection.execute(
            f"SELECT catalog, snapshots, refresh_status FROM {schema}.state WHERE singleton"
        ).fetchone()
    if state is None:
        raise ValueError("The hosted release catalog has no state")
    catalog = state["catalog"]
    if catalog["format_version"] != FORMAT_VERSION:
        raise ValueError("Unsupported hosted dataset catalog format")
    datasets = [
        dataset_from_record(entry, state["snapshots"][entry["snapshot_id"]])
        for entry in catalog["versions"]
    ]
    if len({dataset.version for dataset in datasets}) != len(datasets):
        raise ValueError("Duplicate hosted dataset versions")
    return catalog["active_version"], datasets, state["refresh_status"]


def hosted_runtime():
    runtime = os.environ.get("FILING_RUNTIME", "local")
    if runtime not in {"local", "hosted"}:
        raise ValueError("Invalid API runtime")
    return runtime == "hosted"


@contextmanager
def hosted_reader(database, *, login_pattern=API_LOGIN):
    host = os.environ.get("FILING_DB_HOST", "")
    user = os.environ.get("FILING_DB_USER", "")
    port = int(os.environ.get("FILING_DB_PORT", "5432"))
    if (not re.fullmatch(r"[A-Za-z0-9.-]+", host) or not 1 <= port <= 65535
            or not re.fullmatch(rf"{login_pattern}(?:\.[a-z0-9]+)?", user)):
        raise ValueError("The hosted reader requires a TCP endpoint and dedicated login")
    password_file = os.environ.get("FILING_DB_PASSWORD_FILE")
    ca_file = os.environ.get("FILING_DB_CA_FILE")
    if not password_file or not ca_file or not Path(ca_file).is_file():
        raise ValueError("The hosted reader requires mounted password and CA files")
    password = Path(password_file).read_text(encoding="ascii")
    if not re.fullmatch(r"[a-f0-9]{64}\n?", password):
        raise ValueError("Invalid hosted reader password file")
    with psycopg.connect(
        host=host, port=port, dbname=database, user=user, password=password.rstrip("\n"),
        sslmode="verify-full", sslrootcert=ca_file, gssencmode="disable",
        connect_timeout=3, row_factory=dict_row,
    ) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute("SET LOCAL statement_timeout = '6s'")
        connection.execute("SET LOCAL search_path = pg_catalog")
        connection.execute("SET LOCAL TimeZone = 'UTC'")
        yield connection


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


def reader_password():
    descriptor = os.open(PASSWORD_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, encoding="ascii") as handle:
        mode = os.fstat(handle.fileno()).st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise ValueError("The local reader credential requires a private regular file")
        value = handle.read(66)
        if not re.fullmatch(r"[a-f0-9]{64}\n?", value):
            raise ValueError("Invalid local reader password file")
        return value.rstrip("\n")


def local_reader(database):
    return psycopg.connect(
        host="127.0.0.1", port=db_port(), dbname=database,
        user=READER, password=reader_password(),
        connect_timeout=3, row_factory=dict_row,
        options="-c default_transaction_read_only=on -c statement_timeout=6000 -c search_path=pg_catalog -c TimeZone=UTC",
    )


@contextmanager
def reader(dataset):
    connect = hosted_reader if hosted_runtime() else local_reader
    with connect(dataset.database) as connection:
        stamp = connection.execute(
            "SELECT snapshot_id, methodology_version FROM app_snapshot.identity"
        ).fetchone()
        if not stamp or (stamp["snapshot_id"], stamp["methodology_version"]) != (
            dataset.snapshot_id, dataset.methodology_version,
        ):
            raise ValueError("Prepared database identity does not match the selected snapshot")
        yield connection
