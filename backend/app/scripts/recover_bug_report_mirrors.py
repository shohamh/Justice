"""Recover bug reports whose database insert failed using private object mirrors."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid

from app.db.session import session_scope
from app.services.bug_reports import BugReportImportError, import_bug_report_json
from app.settings import get_settings
from app.storage.keys import make_object_key
from app.storage.s3 import S3MaintenanceObjectStorage

MAX_MIRROR_BYTES = 1 * 1024 * 1024


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.storage_bucket:
        print(json.dumps({"error": "storage_not_configured"}))
        return 2
    storage = S3MaintenanceObjectStorage(settings)
    recovered = already_exists = failed = 0
    try:
        with session_scope() as session:
            for key in storage.iter_keys(prefix="bug_report_json_mirror/"):
                try:
                    report_id = uuid.UUID(key.split("/", 1)[1])
                    if key != make_object_key("bug_report_json_mirror", report_id):
                        raise ValueError("invalid_key")
                    body, length = storage.open_read(key=key)
                    try:
                        raw = body.read(MAX_MIRROR_BYTES + 1)
                    finally:
                        body.close()
                    if length > MAX_MIRROR_BYTES or len(raw) != length:
                        raise ValueError("invalid_size")
                    payload = json.loads(raw)
                    if not isinstance(payload, dict) or str(payload.get("id")) != str(report_id):
                        raise ValueError("invalid_record")
                    if args.dry_run:
                        recovered += 1
                        continue
                    import_bug_report_json(
                        session, payload, mirror_sha256=hashlib.sha256(raw).hexdigest(),
                    )
                    session.commit()
                    recovered += 1
                except BugReportImportError as exc:
                    session.rollback()
                    if str(exc) == "already_exists":
                        already_exists += 1
                    else:
                        failed += 1
                except Exception:
                    session.rollback()
                    failed += 1
    except Exception:
        print(json.dumps({"error": "recovery_unavailable"}))
        return 2
    print(json.dumps({"recovered": recovered, "already_exists": already_exists, "failed": failed, "dry_run": args.dry_run}, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
