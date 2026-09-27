from app.file_gateway.authorization_client import AuthorizationClient


def test_authorization_client_requires_verified_mtls_configuration():
    client = AuthorizationClient(
        base_url="https://file-authorization:8443",
        ca_bundle="ca.pem",
        client_cert=("gateway.pem", "gateway-key.pem"),
    )
    assert client.verify == "ca.pem"
    assert client.cert == ("gateway.pem", "gateway-key.pem")
    assert client.follow_redirects is False
