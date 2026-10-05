"""Authenticated endpoints that create bounded XLSX exports."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, ValidationError

from app.auth.deps import require_password_changed
from app.db.models import Soldier
from app.services.xlsx_export import (
    MAX_EXPORT_REQUEST_BYTES,
    WorksheetMatrix,
    build_matrix_workbook,
    validate_export_filename,
)

router = APIRouter()

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class MatrixExportRequest(BaseModel):
    """Strict request envelope for a client-prepared worksheet matrix."""

    model_config = ConfigDict(strict=True, extra="forbid")

    filename: str
    matrix: WorksheetMatrix


async def _read_bounded_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_EXPORT_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="export_request_too_large",
            )
        body.extend(chunk)
    return bytes(body)


@router.post("/exports/xlsx")
async def export_xlsx_matrix(
    request: Request,
    _user: Soldier = Depends(require_password_changed),
) -> Response:
    """Build an XLSX attachment from a bounded matrix supplied by the client."""
    raw_body = await _read_bounded_body(request)
    try:
        payload = MatrixExportRequest.model_validate_json(raw_body, strict=True)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_export_request",
        ) from exc

    try:
        filename = validate_export_filename(payload.filename)
        workbook = build_matrix_workbook([payload.matrix])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="invalid_export_request",
        ) from exc

    return Response(
        content=workbook,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
