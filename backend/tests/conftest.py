# tests/conftest.py
import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

# All data tables in dependency order (referenced-by-FK tables first so CASCADE handles the rest)
_ALL_DATA_TABLES = [
    "audit_log",
    "duty_day_overrides",
    "duty_dismissals",
    "score_adjustments",
    "duty_assignments",
    "swap_requests",
    "personal_constraints",
    "exemption_request_files",
    "exemption_requests",
    "soldier_exemptions",
    "exemption_duty_type_map",
    "forced_callups",
    "algorithm_jobs",
    "duty_shifts",
    "shift_templates",
    "commander_notification_scopes",
    "commander_notification_depth",
    "duty_manager_scope",
    "telegram_outbox",
    "telegram_action_tokens",
    "telegram_links",
    "password_reset_tokens",
    "email_verification_tokens",
    "registration_invite_codes",
    "soldier_enrollment_requests",
    "exemption_types",
    "duty_types",
    "duty_locations",
    "system_settings",
    "soldiers",
    "hierarchy_nodes",
]


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    # Match the prod database/role names so migration 0001's hardcoded
    # `GRANT CONNECT ON DATABASE cod2` and the 'app'/'app_pw' role line apply cleanly.
    with PostgresContainer(
        "postgres:16-alpine", username="db_admin", password="db_admin_pw", dbname="cod2"
    ) as pg:
        yield pg


@pytest.fixture(scope="session")
def db_admin_url(pg_container: PostgresContainer) -> str:
    """Superuser URL from testcontainers, normalised to the psycopg3 driver."""
    url = make_url(pg_container.get_connection_url()).set(drivername="postgresql+psycopg")
    # str(url) masks the password as *** in SQLAlchemy 2.0; render it verbatim.
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session", autouse=True)
def _apply_schema(db_admin_url: str) -> None:
    """Run migrations against the throwaway container at session start.

    Also sets env vars BEFORE any app module is imported, so settings cache picks
    them up. Pumps the login rate limit high so the multi-login test suite isn't
    artificially throttled.
    """
    os.environ["DATABASE_URL"] = db_admin_url
    os.environ["DB_ADMIN_URL"] = db_admin_url
    os.environ["JWT_SECRET"] = "test-secret-32-bytes-of-padding-_-x"
    os.environ["LOGIN_RATE_LIMIT"] = "10000/minute"

    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "alembic")
    command.upgrade(cfg, "head")


_SYSTEM_SETTINGS_DEFAULTS = [
    ("auth.session_minutes", "15"),
    ("auth.refresh_days", "30"),
    ("auth.login_rate_limit_per_5m", "5"),
    ("eligibility.mitvahim_months", "6"),
    ("eligibility.alal_months", "3"),
]


@pytest.fixture(scope="session")
def admin_engine(db_admin_url: str) -> Iterator["Engine"]:  # noqa: F821
    """Superuser engine, shared for the whole session.

    Session-scoped so the connection pool is created once per worker instead of
    rebuilt for every test (the old function-scoped engine + the per-test engine
    in _truncate_tables were the dominant fixture overhead)."""
    engine = create_engine(db_admin_url, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(db_admin_url: str) -> Iterator["Engine"]:  # noqa: F821
    """Engine using the unprivileged 'app' role — exposes RBAC errors at the DB layer.

    Session-scoped for the same pool-reuse reason as admin_engine."""
    app_url = make_url(db_admin_url).set(username="app", password="app_pw")
    engine = create_engine(app_url.render_as_string(hide_password=False), future=True)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _truncate_tables(admin_engine) -> Iterator[None]:
    """Wipe all data rows before each test so personal_number and other unique constraints
    never collide across test functions, even when they use the same hardcoded values.
    Re-seeds system_settings defaults (set by migrations) after truncation.

    Reuses the session-scoped admin_engine (one pooled connection) rather than
    building and disposing a fresh engine on every test."""
    table_list = ", ".join(_ALL_DATA_TABLES)
    with admin_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))
        # Re-apply migration-seeded defaults for system_settings.
        # Use string formatting (not bind params) to avoid :param vs ::cast ambiguity.
        rows = ", ".join(
            f"('{k}', '{v}'::jsonb)" for k, v in _SYSTEM_SETTINGS_DEFAULTS
        )
        conn.execute(
            text(
                f"INSERT INTO system_settings (key, value) VALUES {rows}"
                " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            )
        )
    yield


@pytest.fixture()
def admin_session(admin_engine) -> Iterator[Session]:
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as s:
        yield s


@pytest.fixture()
def app_session(app_engine) -> Iterator[Session]:
    SessionLocal = sessionmaker(bind=app_engine, expire_on_commit=False)
    with SessionLocal() as s:
        yield s


@pytest.fixture()
def client(db_admin_url: str) -> Iterator["TestClient"]:  # noqa: F821
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
