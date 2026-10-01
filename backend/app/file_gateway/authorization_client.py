from __future__ import annotations

import os
import ssl
import uuid

import httpx

from app.file_authorization.schemas import FileAuthorizationDecision


def _create_authorization_tls_context(
    ca_bundle: str, client_cert: str, client_key: str
) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=ca_bundle)
    context.load_cert_chain(certfile=client_cert, keyfile=client_key)
    return context


class AuthorizationClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        ca_bundle: str | None = None,
        client_cert: tuple[str, str] | None = None,
        timeout: float = 8.0,
        transport=None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("FILE_AUTHORIZATION_URL", "")).rstrip("/")
        self.ca_bundle = ca_bundle or os.environ.get("FILE_AUTHORIZATION_CA", "")
        cert_value = client_cert or (
            os.environ.get("FILE_GATEWAY_CLIENT_CERT", ""),
            os.environ.get("FILE_GATEWAY_CLIENT_KEY", ""),
        )
        self.cert = cert_value if all(cert_value) else None
        if not self.base_url.startswith("https://") or not self.ca_bundle or not self.cert:
            raise ValueError("verified mTLS authorization settings are required")
        self.verify = _create_authorization_tls_context(
            self.ca_bundle, self.cert[0], self.cert[1]
        )
        self.timeout = timeout
        self.follow_redirects = False
        self.transport = transport

    async def authorize(
        self, request_data, bearer_token: str, *, request_id: str | uuid.UUID | None = None
    ) -> FileAuthorizationDecision:
        if not bearer_token or any(ord(c) < 32 for c in bearer_token):
            raise ValueError("invalid bearer token")
        try:
            request_id = str(uuid.UUID(str(request_id))) if request_id is not None else str(uuid.uuid4())
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("invalid request id") from exc
        async with httpx.AsyncClient(
            base_url=self.base_url,
            verify=self.verify,
            timeout=self.timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            response = await client.post(
                "/_internal/file-authorizations",
                json=request_data.model_dump(mode="json"),
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                    "X-Request-ID": request_id,
                },
            )
        if response.is_redirect or response.status_code >= 500:
            raise RuntimeError("authorization service unavailable")
        if response.status_code != 200:
            raise PermissionError("file authorization denied")
        return FileAuthorizationDecision.model_validate(response.json())
