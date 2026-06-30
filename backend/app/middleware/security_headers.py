from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_HSTS_MAX_AGE = int(os.environ.get("HSTS_MAX_AGE", "31536000"))

# Tight CSP: same-origin scripts/styles only, no inline eval, block framing.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"  # explicitly disable legacy XSS filter
        response.headers["Content-Security-Policy"] = _CSP
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        if _HSTS_MAX_AGE > 0:
            response.headers["Strict-Transport-Security"] = (
                f"max-age={_HSTS_MAX_AGE}; includeSubDomains"
            )
        return response
