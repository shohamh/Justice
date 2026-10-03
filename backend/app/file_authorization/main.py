from __future__ import annotations

import os
import ssl
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy.orm import Session

from app.audit.writer import write_file_download_audit
from app.auth.deps import get_current_user
from app.db.session import get_session
from app.file_authorization.policies import authorize_file
from app.file_authorization.schemas import FileAuthorizationDecision, FileAuthorizationRequest


def create_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/_internal/file-authorizations", response_model=FileAuthorizationDecision)
    def decide(
        request: Request, body: FileAuthorizationRequest, session: Session = Depends(get_session)
    ):
        resource_id = next(
            (
                getattr(body, name, None)
                for name in (
                    "file_id",
                    "attachment_id",
                    "report_id",
                    "session_id",
                    "request_id",
                    "exemption_id",
                    "dismissal_id",
                    "comment_id",
                )
                if getattr(body, name, None) is not None
            ),
            None,
        )
        request_id = request.headers.get("X-Request-ID", "")
        try:
            request_id = str(uuid.UUID(request_id))
        except (ValueError, TypeError, AttributeError):
            request_id = str(uuid.uuid4())
        try:
            try:
                actor = get_current_user(request, session)
            except HTTPException:
                write_file_download_audit(
                    session,
                    actor_id=None,
                    allowed=False,
                    resource_id=resource_id,
                    file_class=body.kind,
                    request_id=request_id,
                )
                session.commit()
                raise
            try:
                result = FileAuthorizationDecision.model_validate(
                    authorize_file(session, actor, body)
                )
            except HTTPException:
                write_file_download_audit(
                    session,
                    actor_id=actor.id,
                    allowed=False,
                    resource_id=resource_id,
                    file_class=body.kind,
                    request_id=request_id,
                )
                session.commit()
                raise
            except (ValueError, TypeError):
                write_file_download_audit(
                    session,
                    actor_id=actor.id,
                    allowed=False,
                    resource_id=resource_id,
                    file_class=body.kind,
                    request_id=request_id,
                )
                session.commit()
                raise HTTPException(status_code=404, detail="file_not_found") from None
            write_file_download_audit(
                session,
                actor_id=actor.id,
                allowed=True,
                resource_id=resource_id,
                file_class=body.kind,
                request_id=request_id,
            )
            session.commit()
            return result
        except HTTPException:
            raise
        except Exception as exc:
            session.rollback()
            raise HTTPException(status_code=503, detail="file_authorization_unavailable") from exc

    return app


def run() -> None:
    """Serve only with the dedicated gateway CA; task 8 wires this entrypoint."""
    import uvicorn

    uvicorn.run(
        "app.file_authorization.main:app",
        host="0.0.0.0",
        port=8443,
        ssl_certfile=os.environ["FILE_AUTHORIZATION_TLS_CERT"],
        ssl_keyfile=os.environ["FILE_AUTHORIZATION_TLS_KEY"],
        ssl_ca_certs=os.environ["FILE_AUTHORIZATION_GATEWAY_CA"],
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        proxy_headers=False,
    )


app = create_app()


if __name__ == "__main__":
    run()
