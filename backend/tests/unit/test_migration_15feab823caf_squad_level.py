"""Tests for migration 15feab823caf (seed default "חוליה" squad level type).

Uses the same throwaway-container pattern as
test_migration_6b45caf468c2_keva.py: the shared session-scoped container in
conftest.py is already migrated straight to head, so there's no way to seed
pre-migration state against it.
"""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from testcontainers.postgres import PostgresContainer

DOWN_REVISION = "c7e8f9a0b1c2"
REVISION = "15feab823caf"


@contextmanager
def _db_at_down_revision():
    from app.settings import get_settings

    saved_database_url = os.environ.get("DATABASE_URL")
    saved_db_admin_url = os.environ.get("DB_ADMIN_URL")

    with PostgresContainer(
        "postgres:16-alpine", username="db_admin", password="db_admin_pw", dbname="justice"
    ).with_command(
        "postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off"
    ) as pg:
        url = make_url(pg.get_connection_url()).set(drivername="postgresql+psycopg")
        db_url = url.render_as_string(hide_password=False)

        try:
            os.environ["DATABASE_URL"] = db_url
            os.environ["DB_ADMIN_URL"] = db_url
            get_settings.cache_clear()

            from alembic import command
            from alembic.config import Config

            cfg = Config("alembic.ini")
            cfg.set_main_option("script_location", "alembic")
            command.upgrade(cfg, DOWN_REVISION)

            engine = create_engine(db_url, future=True)
            try:
                yield engine, (lambda: command.upgrade(cfg, REVISION))
            finally:
                engine.dispose()
        finally:
            if saved_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = saved_database_url
            if saved_db_admin_url is None:
                os.environ.pop("DB_ADMIN_URL", None)
            else:
                os.environ["DB_ADMIN_URL"] = saved_db_admin_url
            get_settings.cache_clear()


def test_upgrade_adds_squad_one_rank_below_team():
    with _db_at_down_revision() as (engine, run_migration):
        run_migration()

        with engine.begin() as conn:
            rows = conn.execute(
                text("SELECT key, label, rank FROM hierarchy_level_types ORDER BY rank")
            ).mappings().all()

        by_key = {r["key"]: r for r in rows}
        assert by_key["squad"]["label"] == "חוליה"
        assert by_key["squad"]["rank"] == by_key["team"]["rank"] + 1
        # squad must be strictly the lowest (highest rank number) level
        assert by_key["squad"]["rank"] == max(r["rank"] for r in rows)


def test_upgrade_is_a_noop_if_squad_key_already_exists():
    """An admin may have already added a "squad"-keyed level by hand through
    the existing level-type management UI before this migration ships —
    upgrade() must not error or insert a duplicate in that case."""
    with _db_at_down_revision() as (engine, run_migration):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO hierarchy_level_types (id, key, label, rank) "
                    "VALUES (gen_random_uuid(), 'squad', 'חוליה הישן', 99)"
                )
            )

        run_migration()

        with engine.begin() as conn:
            rows = conn.execute(
                text("SELECT label, rank FROM hierarchy_level_types WHERE key = 'squad'")
            ).mappings().all()

        assert len(rows) == 1
        assert rows[0]["label"] == "חוליה הישן"
        assert rows[0]["rank"] == 99


def test_downgrade_removes_the_squad_row():
    from alembic import command
    from alembic.config import Config

    with _db_at_down_revision() as (engine, run_migration):
        run_migration()

        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "alembic")
        command.downgrade(cfg, DOWN_REVISION)

        with engine.begin() as conn:
            rows = conn.execute(
                text("SELECT 1 FROM hierarchy_level_types WHERE key = 'squad'")
            ).mappings().all()

        assert rows == []
