"""Check the age of the last successful hosted source refresh."""

import argparse
from datetime import timedelta

from pipelines import refresh_dataset


def read_source_attempt():
    from apps.api.dataset_access import HEARTBEAT_LOGIN, hosted_reader

    with hosted_reader("postgres", login_pattern=HEARTBEAT_LOGIN) as connection:
        row = connection.execute(
            "SELECT refresh_status->'sources' AS sources FROM ftf_release.state WHERE singleton"
        ).fetchone()
    return row["sources"] if row else None


def heartbeat_age(attempt, timestamp):
    _, _, last_success = refresh_dataset.public_attempt(attempt, timestamp)
    return (timestamp - last_success).total_seconds() if last_success is not None else None


def report(attempt, timestamp, *, drill=False):
    age = heartbeat_age(attempt, timestamp)
    limit = refresh_dataset.CHECK_LIMIT.total_seconds()
    fields = {"age_seconds": round(age, 3) if age is not None else None, "limit_seconds": int(limit), "drill": drill}
    if age is None:
        refresh_dataset.emit("source_heartbeat_unavailable", "ERROR", **fields)
    elif age > limit:
        refresh_dataset.emit("source_heartbeat_overdue", "WARNING", **fields)
    else:
        refresh_dataset.emit("source_heartbeat_current", **fields)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drill", action="store_true", help="Use an isolated heartbeat just beyond the alert threshold")
    args = parser.parse_args()
    timestamp = refresh_dataset.now()
    if args.drill:
        last_success = (timestamp - refresh_dataset.CHECK_LIMIT - timedelta(seconds=1)).isoformat()
        attempt = {"result": "ok", "started_at": last_success, "last_success_at": last_success}
    else:
        try:
            attempt = read_source_attempt()
        except Exception:
            refresh_dataset.emit("source_heartbeat_unavailable", "ERROR", drill=False, reason="catalog_lookup_failed")
            raise RuntimeError("The hosted source heartbeat could not be read") from None
    report(attempt, timestamp, drill=args.drill)


if __name__ == "__main__":
    main()
