import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from app.duty_eligibility_worker import run_duty_eligibility_worker
from app.email_worker import run_email_worker
from app.error_logging import (
    REQUEST_ID_HEADER,
    log_backend_exception,
    redact,
    redact_query,
    request_data,
    request_id,
)
from app.hr_sync_worker import run_hr_sync_worker
from app.logging_config import setup_logging
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.qualification_expiry_worker import run_qualification_expiry_worker
from app.range_attendance_worker import run_range_attendance_worker
from app.range_reminder_worker import run_range_reminder_worker
from app.rank_advancement_worker import run_rank_advancement_worker
from app.rate_limit import limiter
from app.routes import admin_errors as admin_error_routes
from app.routes import algorithm as algorithm_routes
from app.routes import approvals_export as approvals_export_routes
from app.routes import assignments as assignment_routes
from app.routes import audit_logs as audit_log_routes
from app.routes import auth as auth_routes
from app.routes import bug_reports as bug_report_routes
from app.routes import calendar as calendar_routes
from app.routes import calendar_holidays as calendar_holidays_routes
from app.routes import client_errors as client_error_routes
from app.routes import commander_dashboard as commander_dashboard_routes
from app.routes import config_export as config_export_routes
from app.routes import constraints as constraint_routes
from app.routes import deputies as deputy_routes
from app.routes import dm_scope as dm_scope_routes
from app.routes import duty_config as duty_config_routes
from app.routes import enrollment as enrollment_routes
from app.routes import exchange_calendar_sync as exchange_calendar_sync_routes
from app.routes import exemption_requests as exemption_request_routes
from app.routes import exemptions as exemption_routes
from app.routes import gimelim as gimelim_routes
from app.routes import hakpaza as hakpaza_routes
from app.routes import health as health_routes
from app.routes import hierarchy as hierarchy_routes
from app.routes import hierarchy_transfers as hierarchy_transfer_routes
from app.routes import hr_activation as hr_activation_routes
from app.routes import hr_onboarding as hr_onboarding_routes
from app.routes import hr_review as hr_review_routes
from app.routes import identity_conflicts as identity_conflict_routes
from app.routes import import_excel as import_excel_routes
from app.routes import import_lookup as import_lookup_routes
from app.routes import import_sessions as import_sessions_routes
from app.routes import invite_codes as invite_code_routes
from app.routes import me as me_routes
from app.routes import my_requests as my_request_routes
from app.routes import nav_counts as nav_count_routes
from app.routes import no_show as no_show_routes
from app.routes import notifications as notification_routes
from app.routes import oidc as oidc_routes
from app.routes import potential as potential_routes
from app.routes import public_settings as public_settings_routes
from app.routes import range_locations as range_locations_routes
from app.routes import range_qualification_visibility as range_qualification_visibility_routes
from app.routes import ranges as ranges_routes
from app.routes import rank_advancement as rank_advancement_routes
from app.routes import reserves as reserve_routes
from app.routes import score_adjustments as score_adjustment_routes
from app.routes import scoring as scoring_routes
from app.routes import search as search_routes
from app.routes import shift_templates as shift_template_routes
from app.routes import shifts as shift_routes
from app.routes import soldiers as soldier_routes
from app.routes import swaps as swap_routes
from app.routes import swaps_eligibility as swaps_eligibility_routes
from app.routes import system_settings as system_settings_routes
from app.score_projection_revalidation_worker import run_score_projection_revalidation_worker

# Importing v1_standard registers it in the import-parser registry as a
# side effect (see app/services/import_parsers/v1_standard.py's bottom-level
# `register(...)` call). Imported here so it's registered once at app startup.
from app.services.import_parsers import v1_standard as _v1_standard_import_parser  # noqa: F401
from app.settings import get_settings
from app.swap_expiry_worker import run_swap_expiry_worker
from app.transparency_read_model_worker import run_transparency_read_model_worker

setup_logging()
logger = logging.getLogger(__name__)


class _BodySizeLimitMiddleware(BaseHTTPMiddleware):
    _LIMIT = 50 * 1024 * 1024  # 50 MB

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request.state.request_id = request_id(request.headers.get(REQUEST_ID_HEADER))
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self._LIMIT:
                    return StarletteResponse("Payload too large", status_code=413)
            except ValueError:
                return StarletteResponse("Invalid Content-Length header", status_code=400)
        logged_exception = False
        try:
            response = await call_next(request)
        except Exception as exc:
            log_backend_exception(request, exc, await request_data(request))
            logged_exception = True
            response = StarletteResponse(
                "Internal server error", status_code=500,
                headers={REQUEST_ID_HEADER: request.state.request_id},
            )
        if response.status_code >= 500 and not logged_exception:
            # A route can return a >=500 response directly (rather than raising)
            # after call_next() has already finished, e.g. the readiness probe's
            # 503 — by that point the ASGI receive channel BaseHTTPMiddleware
            # handed to the downstream app is no longer available, so re-reading
            # the request body here raises RuntimeError. Fall back to logging
            # without the body rather than losing the error report entirely.
            try:
                data = await request_data(request)
            except RuntimeError:
                headers = {
                    key: request.headers[key]
                    for key in ("content-type", "user-agent", "referer")
                    if key in request.headers
                }
                data = {
                    "method": request.method,
                    "path": request.url.path,
                    "query": redact_query(request.query_params),
                    "headers": redact(headers),
                    "body": None,
                }
            log_backend_exception(
                request,
                RuntimeError(f"HTTP {response.status_code} response"),
                data,
            )
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        return response


async def _unhandled_exception_handler(request: Request, exc: Exception) -> StarletteResponse:
    log_backend_exception(request, exc, await request_data(request))
    return StarletteResponse("Internal server error", status_code=500, headers={REQUEST_ID_HEADER: request.state.request_id})


def _handle_async_exception(loop: asyncio.AbstractEventLoop, context: dict) -> None:
    logging.getLogger("asyncio").critical(
        "UNHANDLED ASYNCIO EXCEPTION: %s",
        context.get("message"),
        exc_info=context.get("exception"),
    )


def _fail_orphaned_algorithm_jobs() -> None:
    """Mark any AlgorithmJob left in "running" status as failed.

    The solve loop's cancel_event and timeout watchdog (see
    algorithm_bridge._watch_job_timeout) live only in the process that started
    the job. If that process dies mid-solve (crash, reload, restart), the DB
    row is orphaned at status="running" forever — nothing in the new process
    knows about it. Every web worker process runs this hook at startup, so a
    "running" row may still belong to a live sibling process: the runner holds
    a per-job advisory lock for its whole run (see
    algorithm_bridge.job_has_live_runner), and only rows whose lock is free
    are orphans.
    """
    import json
    from datetime import UTC, datetime

    from app.db.models import AlgorithmJob
    from app.db.session import session_scope
    from app.services.algorithm_bridge import job_has_live_runner

    with session_scope() as session:
        running = session.query(AlgorithmJob).filter(AlgorithmJob.status == "running").all()
        orphaned = [job for job in running if not job_has_live_runner(session, job.id)]
        for job in orphaned:
            job.status = "failed"
            job.error_message = json.dumps({"status": "INTERRUPTED", "reason": "server_restarted"})
            job.finished_at = datetime.now(tz=UTC)
        if orphaned:
            session.commit()
            logger.warning("Marked %d orphaned algorithm job(s) as failed on startup", len(orphaned))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== STARTUP pid=%d ===", os.getpid())
    asyncio.get_running_loop().set_exception_handler(_handle_async_exception)
    _fail_orphaned_algorithm_jobs()
    if os.getenv("JUSTICE_TESTING") == "1":
        yield
        logger.info("=== CLEAN SHUTDOWN ===")
        return
    email_task = asyncio.create_task(run_email_worker())
    swap_expiry_task = asyncio.create_task(run_swap_expiry_worker())
    range_reminder_task = asyncio.create_task(run_range_reminder_worker())
    range_attendance_task = asyncio.create_task(run_range_attendance_worker())
    duty_eligibility_task = asyncio.create_task(run_duty_eligibility_worker())
    rank_advancement_task = asyncio.create_task(run_rank_advancement_worker())
    hr_sync_task = asyncio.create_task(run_hr_sync_worker())
    qualification_expiry_task = asyncio.create_task(run_qualification_expiry_worker())
    score_projection_revalidation_task = asyncio.create_task(run_score_projection_revalidation_worker())
    transparency_read_model_task = None
    if get_settings().transparency_read_model_enabled:
        transparency_read_model_task = asyncio.create_task(run_transparency_read_model_worker())
    yield
    tasks = [
        email_task, swap_expiry_task, range_reminder_task, range_attendance_task,
        duty_eligibility_task, rank_advancement_task, hr_sync_task,
        qualification_expiry_task, score_projection_revalidation_task,
    ]
    if transparency_read_model_task is not None:
        tasks.append(transparency_read_model_task)
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
    logger.info("=== CLEAN SHUTDOWN ===")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Justice API", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None,
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(_BodySizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=["Retry-After", "Content-Disposition", REQUEST_ID_HEADER],
    )
    app.include_router(health_routes.router, prefix="/api")
    app.include_router(client_error_routes.router, prefix="/api")
    app.include_router(admin_error_routes.router, prefix="/api")
    app.include_router(exchange_calendar_sync_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/api")
    app.include_router(oidc_routes.router, prefix="/api")
    app.include_router(me_routes.router, prefix="/api")
    app.include_router(my_request_routes.router, prefix="/api")
    app.include_router(nav_count_routes.router, prefix="/api")
    app.include_router(hierarchy_routes.router, prefix="/api")
    app.include_router(hierarchy_transfer_routes.router, prefix="/api")
    app.include_router(hr_activation_routes.router, prefix="/api")
    app.include_router(hr_onboarding_routes.router, prefix="/api")
    app.include_router(hr_review_routes.router, prefix="/api")
    app.include_router(identity_conflict_routes.router, prefix="/api")
    # Registered before soldier_routes: soldier_routes has GET /soldiers/{soldier_id}
    # (a uuid-typed path param) which would otherwise shadow our literal
    # /soldiers/rank-ladder path and fail pydantic UUID validation (422) instead
    # of falling through to this router.
    app.include_router(rank_advancement_routes.router, prefix="/api")
    app.include_router(soldier_routes.router, prefix="/api")
    app.include_router(assignment_routes.router, prefix="/api")
    app.include_router(constraint_routes.router, prefix="/api")
    app.include_router(duty_config_routes.router, prefix="/api")
    app.include_router(exemption_routes.router, prefix="/api")
    app.include_router(exemption_request_routes.router, prefix="/api")
    app.include_router(audit_log_routes.router, prefix="/api")
    app.include_router(score_adjustment_routes.router, prefix="/api")
    app.include_router(scoring_routes.router, prefix="/api")
    app.include_router(calendar_routes.router, prefix="/api")
    app.include_router(calendar_holidays_routes.router, prefix="/api")
    app.include_router(algorithm_routes.router, prefix="/api")
    app.include_router(shift_routes.router, prefix="/api")
    app.include_router(shift_template_routes.router, prefix="/api")
    app.include_router(swap_routes.router, prefix="/api")
    app.include_router(swaps_eligibility_routes.router, prefix="/api")
    app.include_router(reserve_routes.router, prefix="/api")
    app.include_router(commander_dashboard_routes.router, prefix="/api")
    app.include_router(notification_routes.router, prefix="/api")
    app.include_router(dm_scope_routes.router, prefix="/api")
    app.include_router(deputy_routes.router, prefix="/api")
    app.include_router(enrollment_routes.router, prefix="/api")
    app.include_router(invite_code_routes.router, prefix="/api")
    app.include_router(system_settings_routes.router, prefix="/api")
    app.include_router(hakpaza_routes.router, prefix="/api")
    app.include_router(config_export_routes.router, prefix="/api")
    app.include_router(approvals_export_routes.router, prefix="/api")
    app.include_router(import_excel_routes.router, prefix="/api")
    app.include_router(import_lookup_routes.router, prefix="/api")
    app.include_router(import_sessions_routes.router, prefix="/api")
    app.include_router(gimelim_routes.router, prefix="/api")
    app.include_router(public_settings_routes.router, prefix="/api")
    app.include_router(potential_routes.router, prefix="/api")
    app.include_router(bug_report_routes.router, prefix="/api")
    app.include_router(search_routes.router, prefix="/api")
    app.include_router(no_show_routes.router, prefix="/api")
    app.include_router(range_qualification_visibility_routes.router, prefix="/api")
    app.include_router(range_qualification_visibility_routes.soldiers_router, prefix="/api")
    app.include_router(ranges_routes.router, prefix="/api")
    app.include_router(range_locations_routes.router, prefix="/api")
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    return app


app = create_app()
