"""Prepare read-only application copies of the published local dataset versions."""

import fcntl
import os
import subprocess
from contextlib import contextmanager
from secrets import token_hex

from apps.api.dataset_access import PASSWORD_FILE, READER, catalog_datasets, dataset_from_record, reader, reader_password
from pipelines import publish_dataset as publication

PERMISSIONS = publication.ROOT / "apps/api/reader_permissions.sql"


def setup_database(dataset, restore):
    admin = "filing_to_funding"
    exists = publication.run(
        publication.psql_command(admin, "-qAt", "-c",
                                 f"SELECT 1 FROM pg_database WHERE datname = '{dataset.database}'"),
        capture_output=True, text=True,
    ).stdout.strip()
    if exists:
        with reader(dataset):
            if publication.database_counts(dataset.database) != dataset.row_counts:
                raise ValueError("Prepared database row counts do not match the snapshot")
    else:
        restore(dataset.database)
    try:
        if not exists:
            statement = f"""
            BEGIN;
            CREATE SCHEMA app_snapshot;
            CREATE TABLE app_snapshot.identity AS
            SELECT '{dataset.snapshot_id}'::text AS snapshot_id,
                   '{dataset.methodology_version}'::text AS methodology_version;
            COMMIT;
            """
            publication.run(publication.psql_command(dataset.database, "-q"), input=statement, text=True)
        publication.run(publication.psql_command(
            dataset.database, "-q", "-v", f"snapshot_database={dataset.database}", "-v", f"reader={READER}",
        ), input=PERMISSIONS.read_text(), text=True)
        with reader(dataset):
            pass
    except BaseException:
        if not exists:
            publication.remove_database(dataset.database)
        raise


@contextmanager
def local_reader_setup():
    PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    with (PASSWORD_FILE.parent / "prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not PASSWORD_FILE.exists():
            with os.fdopen(os.open(PASSWORD_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
                handle.write(token_hex(32) + "\n")
        password = reader_password()
        role_sql = f"""
        DO $role$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{READER}') THEN
                CREATE ROLE {READER} LOGIN PASSWORD '{password}';
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_auth_members membership
                JOIN pg_roles member_role ON member_role.oid = membership.member
                WHERE member_role.rolname = '{READER}'
            ) THEN
                RAISE EXCEPTION 'Remove unexpected membership from the local API reader';
            END IF;
        END
        $role$;
        ALTER ROLE {READER} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS
            CONNECTION LIMIT 4;
        ALTER ROLE {READER} SET default_transaction_read_only = on;
        """
        try:
            publication.run(publication.psql_command("filing_to_funding", "-q"),
                            input=role_sql, text=True, capture_output=True)
        except subprocess.CalledProcessError:
            raise ValueError("Could not configure the local API reader") from None
        yield


def prepare_record(directory, record, details):
    with local_reader_setup():
        dataset = dataset_from_record(record, details)
        setup_database(dataset, lambda database: publication.restore_record(directory, record, database))


def main():
    with local_reader_setup():
        _, datasets = catalog_datasets()
        if not datasets:
            raise ValueError("Publish a local dataset before preparing the API")
        for dataset in datasets:
            setup_database(dataset, lambda database: publication.restore(publication.DATASETS, dataset.version, database))
            print(f"{dataset.version} ready")


if __name__ == "__main__":
    main()
