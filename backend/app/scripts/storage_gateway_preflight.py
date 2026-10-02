"""Check gateway-to-authorization mTLS without using real credentials or data."""

from __future__ import annotations

import asyncio
import ssl
import sys
import uuid

from app.file_authorization.schemas import ExemptionRequestFileRequest
from app.file_gateway.authorization_client import AuthorizationClient


def main() -> int:
    """Print a safe denial or transport reason; never print request secrets."""
    try:
        request_id = str(uuid.uuid4())
        request = ExemptionRequestFileRequest(
            kind="exemption_request",
            request_id=request_id,
            file_id=str(uuid.uuid4()),
        )
        asyncio.run(
            AuthorizationClient(timeout=5.0).authorize(
                request,
                "task8-preflight-invalid-token",
                request_id=request_id,
            )
        )
        print(
            "Task 8 mTLS preflight: authorization unexpectedly allowed an invalid bearer"
        )
        return 1
    except PermissionError:
        print("Task 8 mTLS preflight: mTLS verified; invalid bearer denied")
        return 0
    except Exception as exc:  # report transport reason, never request credentials
        causes = []
        current = exc
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, ssl.SSLError):
                reason = current.reason or "unknown"
                errno = current.errno
                causes.append(f"TLS:{reason}:{errno}")
            else:
                causes.append(type(current).__name__)
            current = current.__cause__ or current.__context__
        print(f"Task 8 mTLS preflight: {' <- '.join(causes)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
