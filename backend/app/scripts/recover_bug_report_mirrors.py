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
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _verify_screenshot_object(storage, payload: dict) -> None:
    key = payload.get("screenshot_storage_key")
    if key is None:
        if payload.get("screenshot_storage_sha256") is not None or payload.get("screenshot_storage_size") is not None:
            raise ValueError("invalid_screenshot_metadata")
        return
    report_id = uuid.UUID(str(payload["id"]))
    if key != make_object_key("bug_report_screenshot", report_id):
        raise ValueError("invalid_screenshot_key")
    expected_size = payload.get("screenshot_storage_size")
    expected_hash = payload.get("screenshot_storage_sha256")
    if type(expected_size) is not int or not 0 < expected_size <= MAX_SCREENSHOT_BYTES:
        raise ValueError("invalid_screenshot_metadata")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise ValueError("invalid_screenshot_metadata")
    body, reported_size = storage.open_read(key=key)
    try:
        content = body.read(MAX_SCREENSHOT_BYTES + 1)
    finally:
        body.close()
    if (
        len(content) > MAX_SCREENSHOT_BYTES
        or len(content) != expected_size
        or reported_size != expected_size
        or hashlib.sha256(content).hexdigest() != expected_hash
        or not content.startswith(_PNG_MAGIC)
    ):
        raise ValueError("screenshot_integrity_failed")


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
                    _verify_screenshot_object(storage, payload)
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
