# tests/conftest.py
import logging
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

_SHARED_URL_KEY = "shared_postgres_url"
_SHARED_TEMPLATE_KEY = "shared_postgres_template"
_SHARED_CONTAINER_ATTR = "_shared_postgres_container"
_SHARED_URL_ATTR = "_shared_postgres_url"
_SHARED_TEMPLATE_ATTR = "_shared_postgres_template"


def _new_postgres_container() -> PostgresContainer:
    return PostgresContainer(
        "postgres:16-alpine",
        username="db_admin",
        password="db_admin_pw",
        dbname="justice",
    ).with_command("postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off")


def _render_psycopg_url(url: str) -> str:
    return make_url(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def _shared_postgres_enabled(config: pytest.Config) -> bool:
    """Use the controller-owned database only for a complete parallel suite."""
    if getattr(config, "workerinput", None):
        return False
    if not getattr(config.option, "numprocesses", 0):
        return False

    suite_root = (Path(config.rootpath) / "tests").resolve()
    selected_paths = [Path(arg).resolve() for arg in config.args]
    return selected_paths == [suite_root]


def _worker_database_name(workerinput: dict[str, object]) -> str:
    raw = f"{workerinput['testrunuid']}_{workerinput['workerid']}".lower()
    safe = re.sub(r"[^a-z0-9_]", "_", raw)
    return f"pytest_{safe}"[:63].rstrip("_")


def _database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def _quoted_database_name(name: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]{1,63}", name):
        raise ValueError(f"unsafe PostgreSQL database name: {name!r}")
    return f'"{name}"'


def _run_migrations(database_url: str, rootpath: Path) -> None:
    os.environ["DATABASE_URL"] = database_url
    os.environ["DB_ADMIN_URL"] = database_url

    from app.settings import get_settings

    get_settings.cache_clear()

    from alembic.config import Config

    from alembic import command

    cfg = Config(str(rootpath / "alembic.ini"))
    cfg.set_main_option("script_location", str(rootpath / "alembic"))
    command.upgrade(cfg, "head")

    # alembic's env.py runs in-process here and calls logging.config.fileConfig,
    # whose disable_existing_loggers defaults to True: every logger that existed
    # before the migration gets disabled=True, silently killing later logging in
    # this pytest process (e.g. capture helpers and caplog assertions). Restore.
    for _lg in logging.Logger.manager.loggerDict.values():
        if isinstance(_lg, logging.Logger):
            _lg.disabled = False


def pytest_configure(config: pytest.Config) -> None:
    """Build one migrated template database before xdist workers start."""
    if not _shared_postgres_enabled(config):
        return

    container = _new_postgres_container()
    container.start()
    base_url = _render_psycopg_url(container.get_connection_url())
    template_name = f"pytest_template_{uuid.uuid4().hex[:16]}"
    template_sql = _quoted_database_name(template_name)
    server_engine = create_engine(base_url, isolation_level="AUTOCOMMIT", future=True)

    previous_database_url = os.environ.get("DATABASE_URL")
    previous_admin_url = os.environ.get("DB_ADMIN_URL")
    try:
        with server_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {template_sql} TEMPLATE template0"))
        _run_migrations(_database_url(base_url, template_name), Path(config.rootpath))
        with server_engine.connect() as conn:
            conn.execute(text(f"ALTER DATABASE {template_sql} ALLOW_CONNECTIONS false"))
    except BaseException:
        server_engine.dispose()
        container.stop()
        raise
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        if previous_admin_url is None:
            os.environ.pop("DB_ADMIN_URL", None)
        else:
            os.environ["DB_ADMIN_URL"] = previous_admin_url
        from app.settings import get_settings

        get_settings.cache_clear()

    server_engine.dispose()
    setattr(config, _SHARED_CONTAINER_ATTR, container)
    setattr(config, _SHARED_URL_ATTR, base_url)
    setattr(config, _SHARED_TEMPLATE_ATTR, template_name)


def pytest_configure_node(node) -> None:
    base_url = getattr(node.config, _SHARED_URL_ATTR, None)
    if base_url is None:
        return

    database_name = _worker_database_name(node.workerinput)
    database_sql = _quoted_database_name(database_name)
    template_sql = _quoted_database_name(getattr(node.config, _SHARED_TEMPLATE_ATTR))
    maintenance_url = _database_url(base_url, "postgres")
    server_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with server_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {database_sql} TEMPLATE {template_sql}"))
            conn.execute(text(f"GRANT CONNECT ON DATABASE {database_sql} TO app"))
    finally:
        server_engine.dispose()

    node.workerinput[_SHARED_URL_KEY] = _database_url(base_url, database_name)


def pytest_unconfigure(config: pytest.Config) -> None:
    container = getattr(config, _SHARED_CONTAINER_ATTR, None)
    if container is not None:
        container.stop()


_DATABASE_FIXTURES = {
    "client",
    "admin_session",
    "app_session",
    "admin_engine",
    "app_engine",
    "pg_container",
    "db_admin_url",
}


def _item_needs_database(item: pytest.Item) -> bool:
    return bool(_DATABASE_FIXTURES.intersection(item.fixturenames))


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
    "test_validation": "auth",
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
    "test_swap_targets": "duty",
    "test_swaps": "duty",
    "test_swaps_eligibility": "duty",
    "test_system_settings_density": "duty",
    "test_range_models": "duty",
    "test_range_exemption": "duty",
    "test_range_auto_assign": "duty",
    "test_range_authorization": "duty",
    "test_ranges_service": "duty",
    "test_range_attendance": "duty",
    "test_ranges_api": "duty",
    "test_public_settings_ranges": "duty",
    "test_range_reminders": "duty",
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
    "test_bug_reports_service": "misc",
    "test_bug_reports_api": "misc",
    "test_audit_logs_api": "misc",
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
    "bug_reports",
    "bug_report_comments",
    "bug_report_comment_attachments",
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
    "range_events",
    "range_excusal_requests",
    "range_assignments",
    "soldier_range_qualifications",
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
    "rank_advancement_intervals",
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
    # Focused and single-process runs retain an independent throwaway database.
    with _new_postgres_container() as pg:
        yield pg


@pytest.fixture(scope="session")
def db_admin_url(request: pytest.FixtureRequest) -> Iterator[str]:
    """Yield the controller-provided worker database or a focused-run container."""
    workerinput = getattr(request.config, "workerinput", {})
    shared_url = workerinput.get(_SHARED_URL_KEY)
    if shared_url is not None:
        yield shared_url
        return

    pg = request.getfixturevalue("pg_container")
    yield _render_psycopg_url(pg.get_connection_url())


@pytest.fixture(scope="session", autouse=True)
def _apply_schema(request: pytest.FixtureRequest) -> None:
    """Run migrations against the throwaway container at session start.

    Sets env vars, then explicitly invalidates the settings cache and the
    global DB engine â€” both of which may already have been created (and
    baked in the wrong DATABASE_URL/DB_ADMIN_URL) by a test module that
    imports a route module at collection time, which happens before any
    fixture runs. Pumps the login rate limit high so the multi-login test
    suite isn't artificially throttled.
    """
    if not any(_item_needs_database(item) for item in request.session.items):
        return

    db_admin_url = request.getfixturevalue("db_admin_url")
    os.environ["DATABASE_URL"] = db_admin_url
    os.environ["DB_ADMIN_URL"] = db_admin_url
    os.environ["JWT_SECRET"] = "test-secret-32-bytes-of-padding-_-x"
    os.environ["LOGIN_RATE_LIMIT"] = "10000/minute"

    from app.settings import get_settings

    get_settings.cache_clear()

    from app.db.session import reset_engine

    reset_engine()

    workerinput = getattr(request.config, "workerinput", {})
    if _SHARED_URL_KEY not in workerinput:
        _run_migrations(db_admin_url, Path(request.config.rootpath))


_SYSTEM_SETTINGS_DEFAULTS = [
    ("auth.session_minutes", "15"),
    ("auth.refresh_days", "30"),
    ("auth.login_rate_limit_per_5m", "5"),
    ("eligibility.mitvahim_months", "6"),
    ("eligibility.alal_months", "3"),
    ("mitvachim.excusal_approve_min_commander_level", '"מדור"'),
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
def _truncate_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    """Wipe all data rows before each test so personal_number and other unique constraints
    never collide across test functions, even when they use the same hardcoded values.
    Re-seeds system_settings defaults (set by migrations) after truncation.

    Reuses the session-scoped admin_engine (one pooled connection) rather than
    building and disposing a fresh engine on every test."""
    if not _item_needs_database(request.node):
        yield
        return

    admin_engine = request.getfixturevalue("admin_engine")
    table_list = ", ".join(_ALL_DATA_TABLES)
    with admin_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {table_list} RESTART IDENTITY CASCADE"))
        # Re-apply migration-seeded defaults for system_settings.
        # Use string formatting (not bind params) to avoid :param vs ::cast ambiguity.
        rows = ", ".join(f"('{k}', '{v}'::jsonb)" for k, v in _SYSTEM_SETTINGS_DEFAULTS)
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
        conn.execute(
            text(
                f"INSERT INTO hierarchy_level_types (id, key, label, rank) VALUES {level_type_rows}"
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
def client() -> Iterator["TestClient"]:  # noqa: F821
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
