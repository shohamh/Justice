"""Create and inspect synthetic file records for the isolated storage rehearsal."""

from __future__ import annotations

import argparse
import json
import os
import struct
import uuid
import zlib
from datetime import date
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db.models import (
    BugReport,
    BugReportComment,
    BugReportCommentAttachment,
    DutyAssignment,
    DutyDismissal,
    DutyLocation,
    DutyType,
    ExemptionRequest,
    ExemptionRequestFile,
    ExemptionType,
    GimelimAttachment,
    ImportSession,
    Soldier,
    SoldierExemption,
    SoldierExemptionFile,
)
from app.logging_config import LOG_DIR
from app.settings import get_storage_maintenance_settings

PROJECT_NAME = "justice-storage-migration-e2e"
INVALID_GIMELIM_BYTES = b"synthetic invalid PDF; intentionally repaired before retry"


def _assert_disposable_database() -> str:
    if os.getenv("STORAGE_MIGRATION_REHEARSAL_PROJECT") != PROJECT_NAME:
        raise RuntimeError("fixture only runs for its dedicated rehearsal project")
    if os.getenv("ENVIRONMENT", "development").lower() == "production":
        raise RuntimeError("fixture refuses to run in production")
    database_url = get_storage_maintenance_settings().database_url
    if make_url(database_url).host != "db":
        raise RuntimeError("fixture only runs against the isolated Compose db service")
    return database_url


def _png_chunk(kind: bytes, value: bytes) -> bytes:
    return (
        struct.pack(">I", len(value))
        + kind
        + value
        + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)
    )


def _png() -> bytes:
    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\x10\x20\x30"))
        + _png_chunk(b"IEND", b"")
    )


def _workbook() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("xl/workbook.xml", "<workbook></workbook>")
    return buffer.getvalue()


def create_fixture(session: Session) -> dict[str, str]:
    token = uuid.uuid4().hex
    today = date.today()
    soldier = Soldier(
        personal_number=f"storage-rehearsal-{token}",
        full_name="Synthetic Storage Rehearsal",
        password_hash="not-used-by-rehearsal",
    )
    exemption_type = ExemptionType(name=f"Storage Rehearsal {token}")
    duty_type = DutyType(name=f"Storage Rehearsal {token}", score_per_day=1)
    duty_location = DutyLocation(name=f"Storage Rehearsal {token}")
    session.add_all([soldier, exemption_type, duty_type, duty_location])
    session.flush()

    soldier_exemption = SoldierExemption(
        soldier_id=soldier.id,
        exemption_type_id=exemption_type.id,
        start_date=today,
        reason="synthetic storage migration rehearsal",
    )
    exemption_request = ExemptionRequest(
        soldier_id=soldier.id,
        exemption_type_id=exemption_type.id,
        reason="synthetic storage migration rehearsal",
    )
    assignment = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=duty_type.id,
        duty_location_id=duty_location.id,
        start_date=today,
        end_date=today,
    )
    session.add_all([soldier_exemption, exemption_request, assignment])
    session.flush()

    dismissal = DutyDismissal(
        duty_assignment_id=assignment.id,
        dismissed_from=today,
        dismissed_to=today,
        is_gimelim=True,
    )
    bug_report = BugReport(
        description=f"Synthetic storage rehearsal {token}",
        severity="low",
        route=f"/storage-migration-rehearsal/{token}",
        screenshot=_png(),
    )
    session.add_all([dismissal, bug_report])
    session.flush()

    comment = BugReportComment(
        bug_report_id=bug_report.id,
        author_id=soldier.id,
        body=f"Synthetic storage rehearsal {token}",
    )
    session.add(comment)
    session.flush()

    source_path = LOG_DIR / "bug_reports" / f"storage-rehearsal-{token}.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        json.dumps({"synthetic": True, "rehearsal": token}), encoding="utf-8"
    )
    bug_report.json_file_path = str(source_path)

    soldier_file = SoldierExemptionFile(
        soldier_exemption_id=soldier_exemption.id,
        file_name=f"{token}-soldier-exemption.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4\nsynthetic soldier exemption\n%%EOF",
    )
    request_file = ExemptionRequestFile(
        exemption_request_id=exemption_request.id,
        file_name=f"{token}-exemption-request.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4\nsynthetic exemption request\n%%EOF",
    )
    gimelim_file = GimelimAttachment(
        dismissal_id=dismissal.id,
        file_name=f"{token}-gimelim.pdf",
        content_type="application/pdf",
        data=INVALID_GIMELIM_BYTES,
    )
    comment_file = BugReportCommentAttachment(
        comment_id=comment.id,
        file_name=f"{token}-comment.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4\nsynthetic bug comment\n%%EOF",
    )
    import_session = ImportSession(
        filename=f"{token}-workbook.xlsx",
        raw_excel=_workbook(),
    )
    session.add_all([soldier_file, request_file, gimelim_file, comment_file, import_session])
    session.commit()
    return {"token": token, "gimelim_file_id": str(gimelim_file.id)}


def repair_gimelim(session: Session, *, token: str, file_id: uuid.UUID) -> dict[str, str]:
    filename = f"{token}-gimelim.pdf"
    record = session.scalar(
        select(GimelimAttachment).where(
            GimelimAttachment.id == file_id,
            GimelimAttachment.file_name == filename,
        )
    )
    if record is None or record.data != INVALID_GIMELIM_BYTES:
        raise RuntimeError("the targeted synthetic Gimelim record is missing or already changed")
    record.data = b"%PDF-1.4\nsynthetic Gimelim repaired for retry\n%%EOF"
    session.commit()
    return {"repaired": str(record.id), "token": token}


def verify_fixture(session: Session, *, token: str) -> dict[str, object]:
    soldier_file = session.scalar(
        select(SoldierExemptionFile).where(SoldierExemptionFile.file_name == f"{token}-soldier-exemption.pdf")
    )
    request_file = session.scalar(
        select(ExemptionRequestFile).where(ExemptionRequestFile.file_name == f"{token}-exemption-request.pdf")
    )
    gimelim_file = session.scalar(
        select(GimelimAttachment).where(GimelimAttachment.file_name == f"{token}-gimelim.pdf")
    )
    comment_file = session.scalar(
        select(BugReportCommentAttachment).where(BugReportCommentAttachment.file_name == f"{token}-comment.pdf")
    )
    bug_report = session.scalar(
        select(BugReport).where(BugReport.route == f"/storage-migration-rehearsal/{token}")
    )
    import_session = session.scalar(
        select(ImportSession).where(ImportSession.filename == f"{token}-workbook.xlsx")
    )
    records = [soldier_file, request_file, gimelim_file, comment_file, bug_report, import_session]
    if any(record is None for record in records) or bug_report is None:
        raise RuntimeError("one or more synthetic legacy records are missing")
    keys = [
        soldier_file.storage_key,
        request_file.storage_key,
        gimelim_file.storage_key,
        comment_file.storage_key,
        bug_report.storage_key,
        bug_report.json_mirror_storage_key,
        import_session.storage_key,
    ]
    if any(not key for key in keys) or len(set(keys)) != 7:
        raise RuntimeError("not all seven synthetic object references were stored distinctly")
    return {"token": token, "verified_file_classes": 7, "keys_present": len(keys)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "repair", "verify"))
    parser.add_argument("--token")
    parser.add_argument("--gimelim-file-id")
    args = parser.parse_args()
    database_url = _assert_disposable_database()
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            if args.operation == "create":
                result = create_fixture(session)
            elif args.operation == "repair":
                if not args.token or not args.gimelim_file_id:
                    parser.error("repair requires --token and --gimelim-file-id")
                result = repair_gimelim(
                    session, token=args.token, file_id=uuid.UUID(args.gimelim_file_id)
                )
            else:
                if not args.token:
                    parser.error("verify requires --token")
                result = verify_fixture(session, token=args.token)
        print(json.dumps(result, sort_keys=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
