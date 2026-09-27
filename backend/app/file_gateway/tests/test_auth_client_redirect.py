import asyncio

import httpx
import pytest

from app.file_authorization.schemas import ExemptionRequestFileRequest
from app.file_gateway.authorization_client import AuthorizationClient


def test_bearer_is_only_sent_to_fixed_auth_service_and_redirect_is_not_followed():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            302, headers={"Location": "https://attacker.invalid/steal"}, request=request
        )

    client = AuthorizationClient(
        base_url="https://file-auth:8443",
        ca_bundle="ca.pem",
        client_cert=("client.pem", "key.pem"),
        transport=httpx.MockTransport(handler),
    )
    request = ExemptionRequestFileRequest(
        kind="exemption_request",
        request_id="00000000-0000-0000-0000-000000000001",
        file_id="00000000-0000-0000-0000-000000000002",
    )
    with pytest.raises(RuntimeError):
        asyncio.run(
            client.authorize(
                request,
                "sensitive-access-token",
                request_id="00000000-0000-0000-0000-000000000003",
            )
        )
    assert len(seen) == 1
    assert str(seen[0].url) == "https://file-auth:8443/_internal/file-authorizations"
    assert seen[0].headers["Authorization"] == "Bearer sensitive-access-token"
    assert seen[0].headers["X-Request-ID"] == "00000000-0000-0000-0000-000000000003"
