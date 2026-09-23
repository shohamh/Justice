import json
from pathlib import Path

import pytest

# Re-export fixtures from the root test conftest so that tests in this
# subdirectory can use admin_session, app_session, etc. See the identical
# re-export in app/services/tests/conftest.py for why a plain import is used
# instead of `pytest_plugins = ["tests.conftest"]`.
from tests.conftest import (  # noqa: F401
    _apply_schema,
    _database_runtime,
    _reset_rate_limiter,
    _truncate_tables,
    admin_engine,
    admin_session,
    app_engine,
    app_session,
    client,
    db_admin_url,
    pg_container,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict | list:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def hr_base_url() -> str:
    return "https://hr.example.internal"


@pytest.fixture
def hr_api_key() -> str:
    return "test-api-key"
