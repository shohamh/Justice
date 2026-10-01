import ssl

import app.file_gateway.authorization_client as authorization_client
from app.file_gateway.authorization_client import AuthorizationClient


def test_authorization_client_requires_verified_mtls_configuration(monkeypatch):
    monkeypatch.setattr(
        authorization_client,
        "_create_authorization_tls_context",
        lambda *_: ssl.create_default_context(),
    )
    client = AuthorizationClient(
        base_url="https://file-authorization:8443",
        ca_bundle="ca.pem",
        client_cert=("gateway.pem", "gateway-key.pem"),
    )
    assert isinstance(client.verify, ssl.SSLContext)
    assert client.cert == ("gateway.pem", "gateway-key.pem")
    assert client.follow_redirects is False
