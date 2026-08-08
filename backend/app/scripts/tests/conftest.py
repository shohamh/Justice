# Re-export fixtures from the root test conftest so that tests in this
# subdirectory can use admin_session, app_session, etc. A plain import
# (rather than `pytest_plugins = ["tests.conftest"]`) avoids double-
# re-registering tests/conftest.py as a plugin — pytest >= 9 rejects
# pytest_plugins in a non-top-level conftest as a collection error.
from tests.conftest import (  # noqa: F401
    admin_engine,
    admin_session,
    app_engine,
    app_session,
    client,
    db_admin_url,
    pg_container,
    _apply_schema,
    _reset_rate_limiter,
    _truncate_tables,
)