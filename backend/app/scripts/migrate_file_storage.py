"""Preflight and resumably backfill legacy file objects."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.db.session import session_scope
from app.settings import get_settings
from app.storage.migration import run_migration, write_restricted_report
from app.storage.s3 import S3MaintenanceObjectStorage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate and inventory without migrating rows")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--report", type=Path, default=Path("var/file-storage-migration-report.json"))
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.storage_bucket:
        print(json.dumps({"error": "storage_not_configured"}))
        return 2
    storage = S3MaintenanceObjectStorage(settings)
    try:
        with session_scope() as session:
            report = run_migration(
                session, storage, settings, dry_run=args.dry_run, batch_size=args.batch_size
            )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(report, sort_keys=True))
    if report["failed"]:
        write_restricted_report(args.report, report)
        return 1
    return 0 if all(report["storage_check"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
