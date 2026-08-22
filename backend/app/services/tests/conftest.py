# Re-export fixtures from the root test conftest so that tests in this
# subdirectory can use admin_session, app_session, etc.
#
# NOTE: this used to be `pytest_plugins = ["tests.conftest"]`, but now that
# "app/services/tests" is a testpaths entry alongside "tests" (both are
# collected in the same pytest session), that explicit plugin registration
# collides with pytest's own direct collection of tests/conftest.py as a
# rootdir conftest, raising "Plugin already registered under a different
# name". A plain import re-exposes the same fixtures in this conftest module
# without registering tests/conftest.py as a plugin a second time. We import
# fixtures only (not tests/conftest.py's session/collection hooks like
# pytest_addoption) since those already get registered once via its own
# direct collection under the "tests" testpath, and importing them here too
# would double-register e.g. the --slow CLI option.
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
