from __future__ import annotations

import base64
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.db.models import Soldier
from app.db.session import get_session
from app.services import bug_reports as svc

router = APIRouter(tags=["bug_reports"])

_MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024  # 5 MB
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class NavHistoryEntry(BaseModel):
    path: str
    timestamp: str


class BugReportSubmitBody(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    severity: Literal["low", "medium", "high"]
    screenshot: str | None = None
    route: str
    nav_history: list[NavHistoryEntry] = Field(default_factory=list)


def _decode_screenshot(b64: str) -> bytes | None:
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception:
        return None
    if len(data) > _MAX_SCREENSHOT_BYTES or not data.startswith(_PNG_MAGIC):
        return None
    return data


@router.post("/bug-reports", status_code=status.HTTP_201_CREATED)
def submit_bug_report(
    body: BugReportSubmitBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    screenshot_bytes = _decode_screenshot(body.screenshot) if body.screenshot else None
    try:
        svc.write_bug_report(
            session,
            reporter=user,
            description=body.description,
            severity=body.severity,
            screenshot=screenshot_bytes,
            route=body.route,
            nav_history=[entry.model_dump() for entry in body.nav_history],
        )
    except svc.BugReportWriteError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="bug_report_write_failed") from exc
    session.commit()
    return {"status": "ok"}
