from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.settings import get_storage_maintenance_settings
from app.storage.migration import run_migration
from app.storage.reconciliation import reconcile_storage
from app.storage.s3 import S3MaintenanceObjectStorage


def _run(operation: str, batch_size: int) -> tuple[dict[str, Any], bool]:
    settings = get_storage_maintenance_settings()
    storage = S3MaintenanceObjectStorage(settings)
    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            if operation in {"preflight", "migrate"}:
                report = run_migration(
                    session, storage, settings,
                    dry_run=operation == "preflight",
                    batch_size=batch_size,
                )
                ok = report["failed"] == 0 and all(report["storage_check"].values())
                if operation == "migrate":
                    ok = ok and report["cutover_ready"]
            else:
                result = reconcile_storage(session, storage)
                report = asdict(result) if is_dataclass(result) else dict(result)
                ok = not report.get("orphan_delete_failed", 0)
                ok = ok and not report.get("outbox_delete_failed", 0)
        return report, ok
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one explicitly selected file-storage maintenance operation."
    )
    parser.add_argument(
        "operation", nargs="?", choices=("preflight", "migrate", "reconcile"),
        default="preflight",
        help="preflight is read-only; migrate and reconcile are explicit operations",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    report, ok = _run(args.operation, args.batch_size)
    print(json.dumps({"operation": args.operation, "report": report}, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
