"""HTTP mapping for soldier identity write errors (see app.services.identity_write)."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.services.identity import IdentityCollisionError


def identity_http_exception(exc: ValueError) -> HTTPException:
    """409 ``<field>_taken`` for a collision, 400 with the validation code otherwise.

    The detail is a stable code naming the colliding field, never the other soldier.
    """
    code = status.HTTP_409_CONFLICT if isinstance(exc, IdentityCollisionError) else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))
