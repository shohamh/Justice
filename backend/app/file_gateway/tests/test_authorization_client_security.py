import pytest

from app.file_gateway.authorization_client import AuthorizationClient


def test_authorization_client_fails_closed_without_https_ca_and_client_identity():
    with pytest.raises(ValueError):
        AuthorizationClient(
            base_url="http://file-auth", ca_bundle="ca.pem", client_cert=("client.pem", "key.pem")
        )
    with pytest.raises(ValueError):
        AuthorizationClient(
            base_url="https://file-auth", ca_bundle="", client_cert=("client.pem", "key.pem")
        )
    with pytest.raises(ValueError):
        AuthorizationClient(base_url="https://file-auth", ca_bundle="ca.pem", client_cert=None)
