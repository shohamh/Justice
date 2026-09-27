from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from contextlib import suppress

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.file_authorization.schemas import (
    BugReportCommentAttachmentRequest,
    BugReportScreenshotRequest,
    ExemptionRequestFileRequest,
    GimelimAttachmentRequest,
    ImportWorkbookRequest,
    SoldierExemptionFileRequest,
)
from app.file_gateway.authorization_client import AuthorizationClient
from app.file_gateway.response_headers import build_file_headers
from app.storage.dependencies import get_object_storage
from app.storage.keys import make_object_key, validate_managed_key

router = APIRouter()
_OPEN_READ_TIMEOUT_SECONDS = 8.0
_LIMITS = {
    "exemption_request": 25 * 1024 * 1024,
    "soldier_exemption": 25 * 1024 * 1024,
    "gimelim": 10 * 1024 * 1024,
    "bug_report_screenshot": 10 * 1024 * 1024,
    "bug_report_comment": 10 * 1024 * 1024,
    "import_workbook": 25 * 1024 * 1024,
}
_RESOURCE_ID = {
    "exemption_request": "file_id",
    "soldier_exemption": "file_id",
    "gimelim": "attachment_id",
    "bug_report_screenshot": "report_id",
    "bug_report_comment": "attachment_id",
    "import_workbook": "session_id",
}


class _PendingOpen:
    """Close an object returned after the waiting request has gone away."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._abandoned = False
        self._body = None

    def open(self, storage, key: str):
        body, size = storage.open_read(key=key)
        with self._lock:
            abandoned = self._abandoned
            if not abandoned:
                self._body = body
        if abandoned:
            with suppress(Exception):
                body.close()
        return body, size

    def take(self) -> None:
        with self._lock:
            self._body = None

    def abandon(self) -> None:
        with self._lock:
            self._abandoned = True
            body, self._body = self._body, None
        if body is not None:
            with suppress(Exception):
                body.close()


def _consume_open_result(task: asyncio.Task) -> None:
    with suppress(Exception, asyncio.CancelledError):
        task.result()


class _DownloadLease:
    def __init__(self, body, semaphore) -> None:
        self._body = body
        self._semaphore = semaphore
        self._closed = False
        self._close_lock = threading.Lock()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._body.close()
            finally:
                if self._semaphore is not None:
                    self._semaphore.release()


class _ManagedStreamingResponse(StreamingResponse):
    def __init__(self, *args, lease: _DownloadLease, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._lease = lease

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._lease.close()


class SlidingWindowRateLimiter:
    """Small bounded process-wide limiter; ingress proxy should also throttle."""

    def __init__(self, *, limit: int = 120, window_seconds: float = 60.0) -> None:
        self.limit, self.window_seconds = limit, window_seconds
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._times and self._times[0] <= now - self.window_seconds:
                self._times.popleft()
            if len(self._times) >= self.limit:
                return False
            self._times.append(now)
            return True


async def stream_authorized(request: Request, auth_request, *, inline: bool = False):
    if request.headers.get("Range"):
        raise HTTPException(
            416, detail="range_not_supported", headers={"Content-Range": "bytes */*"}
        )
    raw = request.headers.get("Authorization", "")
    if not raw.lower().startswith("bearer ") or not raw[7:].strip():
        raise HTTPException(401, detail="missing_token", headers={"WWW-Authenticate": "Bearer"})
    limiter = getattr(request.app.state, "download_rate_limiter", None)
    if limiter is not None and not limiter.allow():
        raise HTTPException(429, detail="download_rate_limit_exceeded")
    token = raw[7:].strip()
    try:
        request_id = str(uuid.UUID(request.headers["X-Request-ID"]))
    except (KeyError, ValueError, TypeError, AttributeError):
        request_id = str(uuid.uuid4())
    semaphore = getattr(request.app.state, "download_semaphore", None)
    acquired = False
    body = None
    response_started = False
    if semaphore is not None:
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=0.05)
            acquired = True
        except TimeoutError as exc:
            raise HTTPException(429, detail="download_capacity_exceeded") from exc
    try:
        try:
            client = (
                getattr(request.app.state, "authorization_client", None) or AuthorizationClient()
            )
            decision = await asyncio.wait_for(
                client.authorize(auth_request, token, request_id=request_id), timeout=8.0
            )
        except PermissionError as exc:
            raise HTTPException(404, detail="file_not_found") from exc
        except Exception as exc:
            raise HTTPException(503, detail="file_download_unavailable") from exc
        resource_id = getattr(auth_request, _RESOURCE_ID[auth_request.kind])
        expected_key = make_object_key(auth_request.kind, resource_id)
        if decision.object_key != expected_key or not validate_managed_key(decision.object_key):
            raise HTTPException(503, detail="file_metadata_invalid")
        if decision.size < 0 or decision.size > _LIMITS[auth_request.kind]:
            raise HTTPException(503, detail="file_metadata_invalid")
        try:
            headers = build_file_headers(
                filename=decision.filename,
                content_type=decision.content_type,
                size=decision.size,
                inline=inline,
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(503, detail="file_metadata_invalid") from exc
        pending = _PendingOpen()
        try:
            open_task = asyncio.create_task(
                asyncio.to_thread(pending.open, get_object_storage(), decision.object_key)
            )
            open_task.add_done_callback(_consume_open_result)
            body, actual_size = await asyncio.wait_for(
                asyncio.shield(open_task), timeout=_OPEN_READ_TIMEOUT_SECONDS
            )
            pending.take()
        except asyncio.CancelledError:
            pending.abandon()
            raise
        except Exception as exc:
            pending.abandon()
            raise HTTPException(503, detail="file_download_unavailable") from exc
        if actual_size != decision.size:
            raise HTTPException(503, detail="file_metadata_invalid")

        lease = _DownloadLease(body, semaphore if acquired else None)

        async def chunks() -> AsyncIterator[bytes]:
            sent = 0
            try:
                while True:
                    chunk = await asyncio.wait_for(
                        asyncio.to_thread(body.read, 64 * 1024), timeout=8.0
                    )
                    if not chunk:
                        break
                    sent += len(chunk)
                    if sent > decision.size:
                        raise RuntimeError("object exceeds authorized size")
                    yield chunk
                if sent != decision.size:
                    raise RuntimeError("object size differs from authorization")
            finally:
                lease.close()

        async def close_on_background() -> None:
            lease.close()

        response = _ManagedStreamingResponse(
            chunks(),
            headers=headers,
            media_type=None,
            background=BackgroundTask(close_on_background),
            lease=lease,
        )
        response_started = True
        return response
    finally:
        if not response_started:
            try:
                if body is not None:
                    body.close()
            finally:
                if acquired:
                    semaphore.release()


@router.get("/api/file-download/exemption-requests/{request_id}/files/{file_id}")
async def exemption_request_file(request: Request, request_id: uuid.UUID, file_id: uuid.UUID):
    return await stream_authorized(
        request,
        ExemptionRequestFileRequest(
            kind="exemption_request", request_id=request_id, file_id=file_id
        ),
    )


@router.get("/api/file-download/exemptions/{exemption_id}/files/{file_id}")
async def soldier_exemption_file(request: Request, exemption_id: uuid.UUID, file_id: uuid.UUID):
    return await stream_authorized(
        request,
        SoldierExemptionFileRequest(
            kind="soldier_exemption", exemption_id=exemption_id, file_id=file_id
        ),
    )


@router.get("/api/file-download/gimelim/{dismissal_id}/attachments/{attachment_id}")
async def gimelim_attachment(request: Request, dismissal_id: uuid.UUID, attachment_id: uuid.UUID):
    return await stream_authorized(
        request,
        GimelimAttachmentRequest(
            kind="gimelim", dismissal_id=dismissal_id, attachment_id=attachment_id
        ),
    )


@router.get("/api/file-download/bug-reports/{report_id}/screenshot")
async def bug_report_screenshot(request: Request, report_id: uuid.UUID):
    return await stream_authorized(
        request,
        BugReportScreenshotRequest(kind="bug_report_screenshot", report_id=report_id),
        inline=True,
    )


@router.get(
    "/api/file-download/bug-reports/{report_id}/comments/{comment_id}/attachments/{attachment_id}"
)
async def bug_report_comment_attachment(
    request: Request, report_id: uuid.UUID, comment_id: uuid.UUID, attachment_id: uuid.UUID
):
    return await stream_authorized(
        request,
        BugReportCommentAttachmentRequest(
            kind="bug_report_comment",
            report_id=report_id,
            comment_id=comment_id,
            attachment_id=attachment_id,
        ),
    )


@router.get("/api/file-download/import-sessions/{session_id}/workbook")
async def import_workbook(request: Request, session_id: uuid.UUID):
    return await stream_authorized(
        request, ImportWorkbookRequest(kind="import_workbook", session_id=session_id)
    )
