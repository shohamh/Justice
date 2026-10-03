import ssl
import sys
from types import SimpleNamespace

import app.file_authorization.main as auth_main


def test_run_requires_client_certificate_from_dedicated_gateway_ca(monkeypatch):
    called = {}
    monkeypatch.setenv("FILE_AUTHORIZATION_TLS_CERT", "server.pem")
    monkeypatch.setenv("FILE_AUTHORIZATION_TLS_KEY", "server-key.pem")
    monkeypatch.setenv("FILE_AUTHORIZATION_GATEWAY_CA", "gateway-ca.pem")
    monkeypatch.setitem(
        sys.modules, "uvicorn", SimpleNamespace(run=lambda *args, **kwargs: called.update(kwargs))
    )
    auth_main.run()
    assert called["ssl_certfile"] == "server.pem"
    assert called["ssl_keyfile"] == "server-key.pem"
    assert called["ssl_ca_certs"] == "gateway-ca.pem"
    assert called["ssl_cert_reqs"] == ssl.CERT_REQUIRED
