from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse

from app import redis_client
from app.db.session import get_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def liveness() -> dict[str, str]:
    """Liveness probe — no external deps. Returns 200 if process is alive."""
    return {"status": "alive"}


@router.get("/ready")
def readiness(session: Session = Depends(get_session)) -> JSONResponse:
    """Readiness probe — checks DB and Redis. Returns 503 if either is down."""
    try:
        session.execute(text("SELECT 1"))
        redis_client.get_redis().ping()
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        return JSONResponse({"status": "not_ready", "error": str(exc)}, status_code=503)


@router.get("")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    """Legacy health endpoint — kept for backward compatibility."""
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
