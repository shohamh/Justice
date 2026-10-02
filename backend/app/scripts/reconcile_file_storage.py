"""Retry object deletes and report storage/database consistency."""
from __future__ import annotations

import argparse
import json
import sys

from app.db.session import session_scope
from app.settings import get_settings
from app.storage.reconciliation import reconcile_storage
from app.storage.s3 import S3MaintenanceObjectStorage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-than-hours", type=int, default=24)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.storage_bucket:
        print(json.dumps({"error": "storage_not_configured"}))
        return 2
    storage = S3MaintenanceObjectStorage(settings)
    try:
        with session_scope() as session:
            report = reconcile_storage(
                session, storage, older_than_hours=args.older_than_hours,
                delete_orphans=not args.dry_run,
                process_outbox=not args.dry_run,
            )
    except ValueError:
        print(json.dumps({"error": "invalid_older_than_hours"}))
        return 2
    summary = {
        "orphan_count": len(report.orphan_keys),
        "deleted_orphan_count": len(report.deleted_keys),
        "missing_reference_count": len(report.missing_references),
        "unknown_age_count": len(report.unknown_age_keys),
        "outbox_completed": report.outbox_completed,
        "outbox_failed": report.outbox_failed,
        "orphan_delete_failed": report.orphan_delete_failed,
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary, sort_keys=True))
    return 1 if report.outbox_failed or report.orphan_delete_failed or report.missing_references else 0


if __name__ == "__main__":
    sys.exit(main())
