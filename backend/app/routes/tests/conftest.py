import sys
import os

# Ensure the backend directory is on the path so `app` can be imported
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Re-export fixtures from the root test conftest so that tests in this
# subdirectory can use admin_session, client, etc. A plain import (rather
# than `pytest_plugins = ["tests.conftest"]`) avoids double-registering
# tests/conftest.py as a plugin — pytest >= 9 rejects pytest_plugins in a
# non-top-level conftest as a collection error.
from tests.conftest import (  # noqa: F401
    _database_runtime,
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