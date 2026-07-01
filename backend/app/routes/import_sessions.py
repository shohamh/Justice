from __future__ import annotations

import io
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_duty_manager_or_admin
from app.db.models import ImportSession, Soldier
from app.db.session import get_session
from app.services.import_sessions import (
    ImportSessionError,
    cancel_session,
    confirm_session,
    create_session,
    mark_done,
    reparse_session,
    set_selections,
)

router = APIRouter(prefix="/import/sessions", tags=["import-sessions"])


DEFAULT_STATUSES = ["draft", "confirmed"]


class SelectionsRequest(BaseModel):
    selections: dict


def _session_summary(sess: ImportSession) -> dict[str, Any]:
    state = sess.parsed_state or {}
    return {
        "id": str(sess.id),
        "status": sess.status,
        "filename": sess.filename,
        "created_at": sess.created_at.isoformat() if sess.created_at else None,
        "row_summary": {
            "soldiers": len(state.get("soldiers", [])),
            "duty_shifts": len(state.get("duty_shifts", [])),
            "shift_templates": len(state.get("shift_templates", [])),
        },
    }


def _session_detail(sess: ImportSession) -> dict[str, Any]:
    return {
        "id": str(sess.id),
        "status": sess.status,
        "filename": sess.filename,
        "parsed_state": sess.parsed_state,
        "user_selections": sess.user_selections,
        "created_links": sess.created_links,
    }


def _get_owned_or_404(
    session: Session, session_id: uuid.UUID, actor: Soldier
) -> ImportSession:
    sess = session.get(ImportSession, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="not_found")
    if actor.role != "admin" and sess.created_by != actor.id:
        raise HTTPException(status_code=403, detail="forbidden")
    return sess


@router.post("")
async def upload_import_session(
    file: UploadFile = File(...),
    parser_id: str | None = None,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    content = await file.read()
    if content[:4] != b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="invalid_file_type")

    try:
        sess = create_session(
            session,
            filename=file.filename or "import.xlsx",
            content=content,
            actor=actor,
            parser_id=parser_id,
        )
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    session.commit()
    return {"session_id": str(sess.id), "preview": sess.parsed_state}


@router.get("")
def list_import_sessions(
    status_filter: str | None = None,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    statuses = (
        [s.strip() for s in status_filter.split(",") if s.strip()]
        if status_filter
        else DEFAULT_STATUSES
    )
    stmt = select(ImportSession).where(ImportSession.status.in_(statuses))
    if actor.role != "admin":
        stmt = stmt.where(ImportSession.created_by == actor.id)
    sessions = session.execute(stmt).scalars().all()
    return [_session_summary(s) for s in sessions]


@router.get("/{session_id}")
def get_import_session(
    session_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    sess = _get_owned_or_404(session, session_id, actor)
    return _session_detail(sess)


@router.post("/{session_id}/reparse")
def reparse_import_session(
    session_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    _get_owned_or_404(session, session_id, actor)
    try:
        sess = reparse_session(session, session_id=session_id, actor=actor)
    except ImportSessionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    session.commit()
    return _session_detail(sess)


@router.patch("/{session_id}/selections")
def update_import_session_selections(
    session_id: uuid.UUID,
    req: SelectionsRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    _get_owned_or_404(session, session_id, actor)
    try:
        set_selections(session, session_id=session_id, selections=req.selections)
    except ImportSessionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    session.commit()
    return {"ok": True}


@router.post("/{session_id}/confirm")
def confirm_import_session(
    session_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    _get_owned_or_404(session, session_id, actor)
    try:
        result = confirm_session(session, session_id=session_id, actor=actor)
    except ImportSessionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    session.commit()
    return result


@router.post("/{session_id}/cancel")
def cancel_import_session(
    session_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    _get_owned_or_404(session, session_id, actor)
    try:
        sess = cancel_session(session, session_id=session_id, actor=actor)
    except ImportSessionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    session.commit()
    return {"status": sess.status}


@router.post("/{session_id}/done")
def mark_import_session_done(
    session_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    _get_owned_or_404(session, session_id, actor)
    try:
        sess = mark_done(session, session_id=session_id, actor=actor)
    except ImportSessionError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))

    session.commit()
    return {"status": sess.status}
