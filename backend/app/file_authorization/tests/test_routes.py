from app.file_authorization.main import create_app


def test_private_app_has_no_docs_and_only_authorization_route():
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/docs" not in paths
    assert "/openapi.json" not in paths
    assert paths == {"/_internal/file-authorizations"}
