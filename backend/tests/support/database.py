"""Database lifecycle support for PostgreSQL-backed tests only.

This module keeps container, migration, engine, and reset behavior outside the
general pytest configuration so pure tests can import ``conftest`` without
implicitly acquiring database infrastructure.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from testcontainers.postgres import PostgresContainer


RESET_TABLES = (
    "audit_log",
    "bug_reports",
    "bug_report_comments",
    "bug_report_comment_attachments",
    "duty_day_overrides",
    "duty_dismissals",
    "score_projection_dirty_buckets",
    "score_projection_state",
    "score_projection_quarter_total",
    "soldier_quarter_score_projection",
    "soldier_score_projection",
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
    "range_locations",
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
)

SYSTEM_SETTINGS_DEFAULTS = (
    ("auth.session_minutes", "15"),
    ("auth.refresh_days", "30"),
    ("auth.login_rate_limit_per_5m", "5"),
    ("eligibility.mitvahim_months", "6"),
    ("eligibility.alal_months", "3"),
    # "group" is the seeded key for the מדור level (rank 6) — get_level_rank
    # matches HierarchyLevelType.key, not .label. See
    # alembic/versions/0059_hierarchy_level_types.py and the corrective
    # migration 366b35d4cff5.
    ("mitvachim.excusal_approve_min_commander_level", '"group"'),
)

HIERARCHY_LEVEL_TYPE_DEFAULTS = (
    ("corps", "אגף", 1),
    ("division", "מערך", 2),
    ("unit", "יחידה", 3),
    ("department", "מרכז", 4),
    ("branch", "ענף", 5),
    ("group", "מדור", 6),
    ("team", "צוות", 7),
)

RESET_DATABASE_STATEMENT = f"TRUNCATE {', '.join(RESET_TABLES)} RESTART IDENTITY CASCADE"
_system_settings_rows = ", ".join(
    f"('{key}', '{value}'::jsonb)" for key, value in SYSTEM_SETTINGS_DEFAULTS
)
SYSTEM_SETTINGS_SEED_STATEMENT = (
    "INSERT INTO system_settings (key, value) VALUES "
    f"{_system_settings_rows} "
    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
)
_hierarchy_level_type_rows = ", ".join(
    f"(gen_random_uuid(), '{key}', '{label}', {rank})"
    for key, label, rank in HIERARCHY_LEVEL_TYPE_DEFAULTS
)
HIERARCHY_LEVEL_TYPES_SEED_STATEMENT = (
    "INSERT INTO hierarchy_level_types (id, key, label, rank) VALUES "
    f"{_hierarchy_level_type_rows}"
)


def new_postgres_container() -> PostgresContainer:
    return PostgresContainer(
        "postgres:16-alpine",
        username="db_admin",
        password="db_admin_pw",
        dbname="justice",
    ).with_command("postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off")


def render_psycopg_url(url: str) -> str:
    return make_url(url).set(drivername="postgresql+psycopg").render_as_string(hide_password=False)


def database_url(base_url: str, database: str) -> str:
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


def autocommit_engine(url: str) -> Engine:
    return create_engine(url, isolation_level="AUTOCOMMIT", future=True)


def quoted_database_name(name: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]{1,63}", name):
        raise ValueError(f"unsafe PostgreSQL database name: {name!r}")
    return f'"{name}"'


def worker_database_name(workerinput: dict[str, object]) -> str:
    raw = f"{workerinput['testrunuid']}_{workerinput['workerid']}".lower()
    safe = re.sub(r"[^a-z0-9_]", "_", raw)
    return f"pytest_{safe}"[:63].rstrip("_")


def run_migrations(database_url: str, rootpath: Path) -> None:
    os.environ["DATABASE_URL"] = database_url
    os.environ["DB_ADMIN_URL"] = database_url

    from app.settings import get_settings

    get_settings.cache_clear()

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(rootpath / "alembic.ini"))
    cfg.set_main_option("script_location", str(rootpath / "alembic"))
    command.upgrade(cfg, "head")

    # alembic's env.py runs in-process and disables pre-existing loggers through
    # logging.config.fileConfig; restore them for later caplog assertions.
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.disabled = False


def reset_database(engine: Engine) -> None:
    """Remove test data and restore migration-seeded settings and hierarchy rows."""
    with engine.begin() as conn:
        conn.execute(text(RESET_DATABASE_STATEMENT))
        conn.execute(text(SYSTEM_SETTINGS_SEED_STATEMENT))
        conn.execute(text(HIERARCHY_LEVEL_TYPES_SEED_STATEMENT))


@dataclass
class TestDatabaseRuntime:
    """The session-scoped database resources for one pytest worker."""

    database_url: str
    rootpath: Path
    requires_migration: bool

    @classmethod
    def for_database(
        cls, database_url: str, rootpath: Path, *, cloned_from_template: bool
    ) -> "TestDatabaseRuntime":
        return cls(
            database_url=database_url,
            rootpath=rootpath,
            requires_migration=not cloned_from_template,
        )

    @cached_property
    def admin_engine(self) -> Engine:
        return create_engine(self.database_url, future=True)

    @cached_property
    def app_engine(self) -> Engine:
        app_url = make_url(self.database_url).set(username="app", password="app_pw")
        return create_engine(app_url.render_as_string(hide_password=False), future=True)

    def migrate_schema(self) -> None:
        if self.requires_migration:
            run_migrations(self.database_url, self.rootpath)

    def reset(self) -> None:
        reset_database(self.admin_engine)

    def dispose(self) -> None:
        for engine_name in ("admin_engine", "app_engine"):
            engine = self.__dict__.get(engine_name)
            if engine is not None:
                engine.dispose()


@dataclass
class MigratedTemplate:
    """A container whose default database is migrated to one specific revision
    and marked non-connectable so it can serve as a CREATE DATABASE template."""

    container: PostgresContainer
    server_url: str  # maintenance URL on the same server (database "postgres")
    template_name: str


_MIGRATED_TEMPLATES: dict[str, MigratedTemplate] = {}


def _alembic_upgrade(url: str, revision: str, rootpath: Path) -> None:
    os.environ["DATABASE_URL"] = url
    os.environ["DB_ADMIN_URL"] = url

    from app.settings import get_settings

    get_settings.cache_clear()

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(rootpath / "alembic.ini"))
    cfg.set_main_option("script_location", str(rootpath / "alembic"))
    command.upgrade(cfg, revision)

    # alembic's env.py runs in-process and disables pre-existing loggers through
    # logging.config.fileConfig; restore them for later caplog assertions.
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.disabled = False


def get_migrated_template(down_revision: str, rootpath: Path) -> MigratedTemplate:
    """Process-cached template database migrated exactly to ``down_revision``.

    Migration regression tests clone this per test instead of each booting a
    fresh container and replaying the whole alembic chain."""
    cached = _MIGRATED_TEMPLATES.get(down_revision)
    if cached is not None:
        return cached

    container = new_postgres_container()
    container.start()
    try:
        base_url = render_psycopg_url(container.get_connection_url())
        template_name = make_url(base_url).database or "justice"
        _alembic_upgrade(base_url, down_revision, rootpath)
        server_url = (
            make_url(base_url).set(database="postgres").render_as_string(hide_password=False)
        )
        with autocommit_engine(server_url).connect() as conn:
            conn.execute(
                text(f"ALTER DATABASE {quoted_database_name(template_name)} ALLOW_CONNECTIONS false")
            )
    except BaseException:
        container.stop()
        raise

    template = MigratedTemplate(container=container, server_url=server_url, template_name=template_name)
    _MIGRATED_TEMPLATES[down_revision] = template
    atexit.register(container.stop)
    return template


@contextmanager
def cloned_migration_database(
    template: MigratedTemplate, *, upgrade_to_revision: str, rootpath: Path
) -> Iterator[tuple[Engine, Callable[[], None]]]:
    """Yield ``(engine, run_migration)`` on a fresh clone of ``template``.

    Repoints DATABASE_URL/DB_ADMIN_URL and the settings cache for the body and
    restores them afterwards — the same process-global contract the per-test
    containers previously provided."""
    clone_name = f"migr_{uuid.uuid4().hex[:16]}"
    quoted_clone = quoted_database_name(clone_name)
    with autocommit_engine(template.server_url).connect() as conn:
        conn.execute(
            text(f"CREATE DATABASE {quoted_clone} TEMPLATE {quoted_database_name(template.template_name)}")
        )

    clone_url = database_url(template.server_url, clone_name)
    saved_database_url = os.environ.get("DATABASE_URL")
    saved_db_admin_url = os.environ.get("DB_ADMIN_URL")

    engine: Engine | None = None
    try:
        os.environ["DATABASE_URL"] = clone_url
        os.environ["DB_ADMIN_URL"] = clone_url

        from app.settings import get_settings

        get_settings.cache_clear()

        from alembic import command
        from alembic.config import Config

        cfg = Config(str(rootpath / "alembic.ini"))
        cfg.set_main_option("script_location", str(rootpath / "alembic"))

        def run_migration() -> None:
            command.upgrade(cfg, upgrade_to_revision)
            for logger in logging.Logger.manager.loggerDict.values():
                if isinstance(logger, logging.Logger):
                    logger.disabled = False

        engine = create_engine(clone_url, future=True)
        yield engine, run_migration
    finally:
        if engine is not None:
            engine.dispose()
        if saved_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved_database_url
        if saved_db_admin_url is None:
            os.environ.pop("DB_ADMIN_URL", None)
        else:
            os.environ["DB_ADMIN_URL"] = saved_db_admin_url

        from app.settings import get_settings

        get_settings.cache_clear()
        with autocommit_engine(template.server_url).connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {quoted_clone} WITH (FORCE)"))
