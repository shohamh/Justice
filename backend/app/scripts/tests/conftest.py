# Re-export fixtures from the root test conftest so that tests in this
# subdirectory can use admin_session, app_session, etc.
pytest_plugins = ["tests.conftest"]
