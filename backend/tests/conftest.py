# tests/conftest.py
import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

# Test file stem -> system-area marker. Applied automatically in
# pytest_collection_modifyitems so individual test files don't need decorators.
# Run a slice with e.g. `pytest -m algorithm` or `pytest -m "duty or scoring"`.
_AREA_MARKERS: dict[str, str] = {
    # algorithm: CP-SAT solver, scheduling model, fairness/effort inputs
    "test_algorithm_cancel": "algorithm",
    "test_algorithm_jobs_list": "algorithm",
    "test_algorithm_notification": "algorithm",
    "test_algorithm_routes": "algorithm",
    "test_algorithm_shifts": "algorithm",
    "test_algorithm_bridge": "algorithm",
    "test_algorithm_bridge_shifts": "algorithm",
    "test_algorithm_proposals": "algorithm",
    "test_model": "algorithm",
    "test_model_effort": "algorithm",
    "test_fairness": "algorithm",
    "test_fairness_components": "algorithm",
    "test_fairness_e2e": "algorithm",
    "test_fairness_batching": "algorithm",
    "test_tiebreak_e2e": "algorithm",
    "test_effort_score": "algorithm",
    "test_effort_future_published": "algorithm",
    # auth: login, JWT, password policy, RBAC, registration/enrollment, security hardening
    "test_login": "auth",
    "test_change_password": "auth",
    "test_forgot_password": "auth",
    "test_jwt_tokens": "auth",
    "test_password": "auth",
    "test_password_policy": "auth",
    "test_authz": "auth",
    "test_action_tokens": "auth",
    "test_rbac_matrix": "auth",
    "test_registration_routes": "auth",
    "test_invite_code_routes": "auth",
    "test_enrollment_routes": "auth",
    "test_security_hardening": "auth",
    "test_security_hardening_2": "auth",
    # hierarchy: hierarchy nodes and duty-manager scope
    "test_hierarchy_api": "hierarchy",
    "test_hierarchy_service": "hierarchy",
    "test_dm_scope_routes": "hierarchy",
    # duty: assignments, shifts, swaps, constraints, exemptions, gimelim, hakpaza, duty config
    "test_assignments_api": "duty",
    "test_assignments_service": "duty",
    "test_calendar_api": "duty",
    "test_constraints_api": "duty",
    "test_constraints_service": "duty",
    "test_duty_config_api": "duty",
    "test_duty_config_service": "duty",
    "test_eligibility": "duty",
    "test_exemptions_api": "duty",
    "test_exemptions_service": "duty",
    "test_commander_exemption_escalation_api": "duty",
    "test_gimelim_api": "duty",
    "test_gimelim_service": "duty",
    "test_hakpaza": "duty",
    "test_reserves": "duty",
    "test_score_adjustments_api": "duty",
    "test_adjustments_service": "duty",
    "test_shift_generation": "duty",
    "test_shifts_routes": "duty",
    "test_shifts_service": "duty",
    "test_swap_eligibility": "duty",
    "test_swaps": "duty",
    "test_swaps_eligibility": "duty",
    "test_system_settings_density": "duty",
    # scoring: cumulative score / transparency / effort-score reporting
    "test_scoring_api": "scoring",
    "test_scoring_service": "scoring",
    "test_scoring_reserve": "scoring",
    "test_transparency_export": "scoring",
    # potential: potential endpoint and potential modifiers (marks as "scoring" subsystem)
    "test_potential_api": "scoring",
    # notifications: notifications, email, Telegram, bot actions
    "test_notifications_api": "notifications",
    "test_email_notifications": "notifications",
    "test_email_render": "notifications",
    "test_telegram_notifications": "notifications",
    "test_bot_actions": "notifications",
    # soldiers: soldier profile, soldier listing, Excel import
    "test_soldier_profile": "soldiers",
    "test_soldiers_api": "soldiers",
    "test_import_excel": "soldiers",
    "test_import_lookup": "soldiers",
    # misc: health check, audit log, settings loader
    "test_health": "misc",
    "test_audit_append_only": "misc",
    "test_settings_loader": "misc",
    "test_logging_config": "misc",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--slow",
        action="store_true",
        default=False,
        help="also run @pytest.mark.slow large-scale CP-SAT tests (~11 min); "
        "excluded by default so a plain `pytest` run stays fast",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not config.getoption("--slow"):
        keep, deselected = [], []
        for item in items:
            (deselected if "slow" in item.keywords else keep).append(item)
        if deselected:
            config.hook.pytest_deselected(items=deselected)
            items[:] = keep

    for item in items:
        stem = item.nodeid.split("::", 1)[0].rsplit("/", 1)[-1].removesuffix(".py")
        area = _AREA_MARKERS.get(stem)
        if area is not None:
            item.add_marker(getattr(pytest.mark, area))

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
    "email_outbox",
    "notification_preferences",
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
    "hierarchy_level_types",
    "hierarchy_nodes",
]


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    # Match the prod database/role names so migration 0001's hardcoded
    # `GRANT CONNECT ON DATABASE justice` and the 'app'/'app_pw' role line apply cleanly.
    #
    # fsync/full_page_writes/synchronous_commit are disabled: this container is
    # throwaway (destroyed at session end), so crash-durability guarantees are
    # irrelevant, but Postgres pays their fsync cost on every TRUNCATE (new
    # relfilenode per truncated table). On Docker Desktop/Windows that fsync cost
    # measured ~3s for the per-test _truncate_tables truncate — the dominant
    # per-test cost in the whole suite. With these off it drops to ~2ms.
    with PostgresContainer(
        "postgres:16-alpine", username="db_admin", password="db_admin_pw", dbname="justice"
    ).with_command(
        "postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off"
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

_LEVEL_TYPE_DEFAULTS = [
    ("corps", "אגף", 1),
    ("division", "מערך", 2),
    ("unit", "יחידה", 3),
    ("department", "מרכז", 4),
    ("branch", "ענף", 5),
    ("group", "מדור", 6),
    ("team", "צוות", 7),
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
def _reset_rate_limiter() -> Iterator[None]:
    """Reset the in-memory rate-limiter storage before each test so that
    rate-limited endpoints (e.g. algorithm job creation) don't bleed state
    across tests that share the same synthetic client IP."""
    from app.rate_limit import limiter
    limiter._storage.reset()
    yield


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
        level_type_rows = ", ".join(
            f"(gen_random_uuid(), '{key}', '{label}', {rank})"
            for key, label, rank in _LEVEL_TYPE_DEFAULTS
        )
        conn.execute(text(f"INSERT INTO hierarchy_level_types (id, key, label, rank) VALUES {level_type_rows}"))
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
