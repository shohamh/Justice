# tests/conftest.py
import ast
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, cast

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

from tests.support import app as test_app_support
from tests.support import database, profiling

_SHARED_URL_KEY = "shared_postgres_url"
_SHARED_TEMPLATE_KEY = "shared_postgres_template"
_SHARED_CONTAINER_ATTR = "_shared_postgres_container"
_SHARED_URL_ATTR = "_shared_postgres_url"
_SHARED_TEMPLATE_ATTR = "_shared_postgres_template"
_SOLVER_PROFILES_ATTR = "_justice_solver_profiles"
_SOLVER_PROFILE_ENABLED_ATTR = "_justice_solver_profile_enabled"
_SOLVER_PROFILE_WARNING_ATTR = "_justice_solver_profile_warning"

TestLayer = Literal["pure", "database", "http"]
_TEST_LAYERS: tuple[TestLayer, ...] = ("pure", "database", "http")
_EXPLICIT_LAYER_MARKER = "test_layer"


def _pure_only_selected(config: pytest.Config) -> bool:
    """Return whether the marker expression can select only ``pure`` tests."""
    markexpr = getattr(config.option, "markexpr", "").strip()
    if not markexpr:
        return False

    try:
        expression = ast.parse(markexpr, mode="eval").body
    except SyntaxError:
        return False

    known_safe_markers = {"pure", "slow", *_AREA_MARKERS.values()}
    requires_pure = False

    def is_safe_conjunction(node: ast.expr, *, negated: bool = False) -> bool:
        nonlocal requires_pure

        if isinstance(node, ast.Name):
            if node.id not in known_safe_markers or node.id in {"database", "http"}:
                return False
            if node.id == "pure":
                if negated:
                    return False
                requires_pure = True
            return True

        if isinstance(node, ast.BoolOp):
            if negated or not isinstance(node.op, ast.And):
                return False
            return all(is_safe_conjunction(value) for value in node.values)

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            if negated or not isinstance(node.operand, ast.Name):
                return False
            return is_safe_conjunction(node.operand, negated=True)

        return False

    return is_safe_conjunction(expression) and requires_pure


def _shared_postgres_enabled(config: pytest.Config) -> bool:
    """Use one migrated template for pytest's default full parallel suite.

    Pytest expands configured ``testpaths`` into ``config.args`` even when the
    user invoked only ``pytest -q``. Compare the parsed positional selectors to
    ``invocation_params.args`` so configured testpaths do not look explicit.

    Explicit file/path runs stay isolated: they are intentionally useful for
    focused debugging and should not pay for controller-side template cloning.
    """
    if getattr(config, "workerinput", None):
        return False
    if not getattr(config.option, "numprocesses", 0):
        return False

    # A marker expression that necessarily includes ``pure`` cannot request
    # database-backed fixtures, even when an explicit pure test path is given.
    if _pure_only_selected(config):
        return False

    invocation_args = {
        os.fspath(argument) for argument in config.invocation_params.args
    }
    parsed_selectors = getattr(config.option, "file_or_dir", None)
    if parsed_selectors is None:
        # ``file_or_dir`` is present on real pytest configs. Falling back to
        # ``config.args`` keeps the helper usable with narrow config adapters.
        parsed_selectors = config.args

    explicitly_selected = any(
        os.fspath(selector) in invocation_args for selector in parsed_selectors
    )
    return not explicitly_selected


def pytest_configure(config: pytest.Config) -> None:
    """Build one migrated template database before xdist workers start."""
    setattr(config, _SOLVER_PROFILES_ATTR, [])
    setattr(config, _SOLVER_PROFILE_ENABLED_ATTR, profiling.profiling_enabled(config))
    setattr(config, _SOLVER_PROFILE_WARNING_ATTR, profiling.profiling_warning(config))
    for marker, description in (
        ("pure", "pure unit or algorithm test; no database or HTTP fixture required"),
        ("database", "database-backed test without an HTTP client"),
        ("http", "HTTP integration test using the test client"),
        (
            _EXPLICIT_LAYER_MARKER,
            "test_layer(layer): override path inference for direct layer dependencies",
        ),
    ):
        config.addinivalue_line("markers", f"{marker}: {description}")

    if not _shared_postgres_enabled(config):
        return

    container = database.new_postgres_container()
    container.start()
    base_url = database.render_psycopg_url(container.get_connection_url())
    template_name = f"pytest_template_{uuid.uuid4().hex[:16]}"
    template_sql = database.quoted_database_name(template_name)
    server_engine = database.autocommit_engine(base_url)

    previous_database_url = os.environ.get("DATABASE_URL")
    previous_admin_url = os.environ.get("DB_ADMIN_URL")
    try:
        with server_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {template_sql} TEMPLATE template0"))
        database.run_migrations(database.database_url(base_url, template_name), Path(config.rootpath))
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

    database_name = database.worker_database_name(node.workerinput)
    database_sql = database.quoted_database_name(database_name)
    template_sql = database.quoted_database_name(getattr(node.config, _SHARED_TEMPLATE_ATTR))
    maintenance_url = database.database_url(base_url, "postgres")
    server_engine = database.autocommit_engine(maintenance_url)
    try:
        with server_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {database_sql} TEMPLATE {template_sql}"))
            conn.execute(text(f"GRANT CONNECT ON DATABASE {database_sql} TO app"))
    finally:
        server_engine.dispose()

    node.workerinput[_SHARED_URL_KEY] = database.database_url(base_url, database_name)


def pytest_unconfigure(config: pytest.Config) -> None:
    container = getattr(config, _SHARED_CONTAINER_ATTR, None)
    if container is not None:
        container.stop()


def pytest_terminal_summary(terminalreporter, exitstatus, config: pytest.Config) -> None:
    warning = getattr(config, _SOLVER_PROFILE_WARNING_ATTR, None)
    if warning is not None:
        terminalreporter.write_sep("=", "solver phase profile")
        terminalreporter.write_line(warning)
        return

    records = getattr(config, _SOLVER_PROFILES_ATTR, [])
    if not records:
        return

    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for _nodeid, durations, phase_counts in records:
        for phase, duration in durations.items():
            totals[phase] = totals.get(phase, 0.0) + duration
        for phase, count in phase_counts.items():
            counts[phase] = counts.get(phase, 0) + count

    terminalreporter.write_sep("=", "solver phase profile")
    for phase, duration in sorted(totals.items(), key=lambda item: item[1], reverse=True):
        terminalreporter.write_line(
            f"{phase}: {duration:.6f}s across {counts.get(phase, 0)} call(s)"
        )


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


_HTTP_FIXTURES = {"client"}
_PURE_TEST_PATH_PREFIXES = ("app/algorithm/tests/", "tests/unit/")


def _explicit_item_layer(item: pytest.Item) -> TestLayer | None:
    """Read an intentional layer override from a collected test item."""
    get_closest_marker = getattr(item, "get_closest_marker", None)
    if get_closest_marker is None:
        return None

    marker = get_closest_marker(_EXPLICIT_LAYER_MARKER)
    if marker is None:
        return None
    if len(marker.args) != 1 or marker.kwargs or marker.args[0] not in _TEST_LAYERS:
        raise pytest.UsageError(
            "@pytest.mark.test_layer requires exactly one of: pure, database, http"
        )
    return cast(TestLayer, marker.args[0])


def item_layer(item: pytest.Item) -> TestLayer:
    """Classify a collected test by its fixture requirements and test location."""
    explicit_layer = _explicit_item_layer(item)
    if explicit_layer is not None:
        return explicit_layer
    if _HTTP_FIXTURES.intersection(item.fixturenames):
        return "http"
    if _item_needs_database(item):
        return "database"

    test_path = item.nodeid.split("::", 1)[0].replace("\\", "/")
    if test_path.startswith(_PURE_TEST_PATH_PREFIXES):
        return "pure"
    return "database"


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
        help="also run @pytest.mark.slow scale and statistical CP-SAT tests; "
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
        item.add_marker(getattr(pytest.mark, item_layer(item)))
        stem = item.nodeid.split("::", 1)[0].rsplit("/", 1)[-1].removesuffix(".py")
        area = _AREA_MARKERS.get(stem)
        if area is not None:
            item.add_marker(getattr(pytest.mark, area))


@pytest.fixture(scope="session")
def pg_container() -> Iterator[PostgresContainer]:
    # Focused and single-process runs retain an independent throwaway database.
    with database.new_postgres_container() as pg:
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
    yield database.render_psycopg_url(pg.get_connection_url())


@pytest.fixture(scope="session")
def _database_runtime(request: pytest.FixtureRequest, db_admin_url: str) -> Iterator[database.TestDatabaseRuntime]:
    """Session-scoped engines and migration decision for this test worker."""
    workerinput = getattr(request.config, "workerinput", {})
    runtime = database.TestDatabaseRuntime.for_database(
        db_admin_url,
        Path(request.config.rootpath),
        cloned_from_template=_SHARED_URL_KEY in workerinput,
    )
    yield runtime
    runtime.dispose()


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

    runtime = request.getfixturevalue("_database_runtime")
    os.environ["DATABASE_URL"] = runtime.database_url
    os.environ["DB_ADMIN_URL"] = runtime.database_url
    os.environ["JWT_SECRET"] = "test-secret-32-bytes-of-padding-_-x"
    os.environ["LOGIN_RATE_LIMIT"] = "10000/minute"

    from app.settings import get_settings

    get_settings.cache_clear()

    from app.db.session import reset_engine

    reset_engine()

    runtime.migrate_schema()

@pytest.fixture(scope="session")
def admin_engine(_database_runtime: database.TestDatabaseRuntime) -> Iterator["Engine"]:  # noqa: F821
    """Superuser engine, shared for the whole session.

    Session-scoped so the connection pool is created once per worker instead of
    rebuilt for every test (the old function-scoped engine + the per-test engine
    in _truncate_tables were the dominant fixture overhead)."""
    yield _database_runtime.admin_engine


@pytest.fixture(scope="session")
def app_engine(_database_runtime: database.TestDatabaseRuntime) -> Iterator["Engine"]:  # noqa: F821
    """Engine using the unprivileged 'app' role — exposes RBAC errors at the DB layer.

    Session-scoped for the same pool-reuse reason as admin_engine."""
    yield _database_runtime.app_engine


@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> Iterator[None]:
    """Reset the in-memory rate-limiter storage before each test so that
    rate-limited endpoints (e.g. algorithm job creation) don't bleed state
    across tests that share the same synthetic client IP."""
    test_app_support.reset_process_state()
    yield


@pytest.fixture(autouse=True)
def _solver_profile_report(request: pytest.FixtureRequest) -> Iterator[None]:
    """Collect solver phase totals only for explicitly enabled test runs."""
    if not getattr(request.config, _SOLVER_PROFILE_ENABLED_ATTR, False):
        yield
        return

    with profiling.capture_solver_profile() as profile:
        yield

    records = getattr(request.config, _SOLVER_PROFILES_ATTR)
    records.append(
        (
            request.node.nodeid,
            dict(profile.durations),
            dict(profile.counts),
        )
    )


@pytest.fixture(autouse=True)
def _truncate_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    """Wipe all data rows before each test so personal_number and other unique constraints
    never collide across test functions, even when they use the same hardcoded values.
    Re-seeds system_settings defaults (set by migrations) after truncation.

    Reuses the session-scoped adapter runtime (and its pooled admin engine)
    rather than building and disposing a fresh engine on every test."""
    if not _item_needs_database(request.node):
        yield
        return

    runtime = request.getfixturevalue("_database_runtime")
    runtime.reset()
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
    with test_app_support.test_client() as c:
        yield c
