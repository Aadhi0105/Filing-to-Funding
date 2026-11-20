"""Prepare read-only application copies of the published local dataset versions."""

import fcntl
import os
import re
from secrets import token_hex

from apps.api.dataset_access import PASSWORD_FILE, READER, catalog_datasets, reader
from pipelines import publish_dataset as publication


def setup_database(dataset):
    admin = "filing_to_funding"
    exists = publication.run(
        publication.psql_command(admin, "-qAt", "-c",
                                 f"SELECT 1 FROM pg_database WHERE datname = '{dataset.database}'"),
        capture_output=True, text=True,
    ).stdout.strip()
    if exists:
        with reader(dataset):
            return
    publication.restore(publication.DATASETS, dataset.version, dataset.database)
    try:
        statement = f"""
        BEGIN;
        REVOKE ALL ON DATABASE {dataset.database} FROM PUBLIC;
        GRANT CONNECT ON DATABASE {dataset.database} TO {READER};
        GRANT USAGE ON SCHEMA analytics, core, raw TO {READER};
        GRANT SELECT ON core.issuers, core.issuer_aliases, core.reporting_periods, core.filings,
            core.reported_facts, core.treasury_yield_observations, raw.source_fetches TO {READER};
        CREATE SCHEMA app_snapshot;
        CREATE TABLE app_snapshot.identity AS
        SELECT '{dataset.snapshot_id}'::text AS snapshot_id,
               '{dataset.methodology_version}'::text AS methodology_version;
        GRANT USAGE ON SCHEMA app_snapshot TO {READER};
        GRANT SELECT ON app_snapshot.identity TO {READER};
        COMMIT;
        """
        publication.run(publication.psql_command(dataset.database, "-q"), input=statement, text=True)
        with reader(dataset):
            pass
    except BaseException:
        publication.remove_database(dataset.database)
        raise


def main():
    PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
    with (PASSWORD_FILE.parent / "prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not PASSWORD_FILE.exists():
            with os.fdopen(os.open(PASSWORD_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as handle:
                handle.write(token_hex(32) + "\n")
        password = PASSWORD_FILE.read_text().strip()
        if not re.fullmatch(r"[a-f0-9]{64}", password):
            raise ValueError("Invalid local reader password file")
        role_sql = f"""
        DO $role$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{READER}') THEN
                CREATE ROLE {READER} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT CONNECTION LIMIT 12
                    PASSWORD '{password}';
            END IF;
        END
        $role$;
        """
        publication.run(publication.psql_command("filing_to_funding", "-q"), input=role_sql, text=True)
        _, datasets = catalog_datasets()
        if not datasets:
            raise ValueError("Publish a local dataset before preparing the API")
        for dataset in datasets:
            if not re.fullmatch(r"[0-9a-f]{64}", dataset.methodology_version):
                raise ValueError("Invalid snapshot methodology identity")
            setup_database(dataset)
            print(f"{dataset.version} ready")


if __name__ == "__main__":
    main()
