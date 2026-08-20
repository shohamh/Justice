"""Tests for migration 032cff6493dd (add index on role_deputies.deputy_id).

Uses the same throwaway-container pattern as
test_migration_bccac29dd1b5_role_deputies.py: the shared session-scoped
container in conftest.py is already migrated straight to head, so there's
no way to seed pre-migration state against it.
"""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from testcontainers.postgres import PostgresContainer

DOWN_REVISION = "bccac29dd1b5"
REVISION = "032cff6493dd"


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
                yield engine, cfg
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


def _index_exists(engine) -> bool:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT 1 FROM pg_indexes WHERE tablename = 'role_deputies' "
                "AND indexname = 'ix_role_deputies_deputy_id'"
            )
        ).scalar() is not None


def test_upgrade_creates_the_index():
    with _db_at_down_revision() as (engine, cfg):
        assert not _index_exists(engine)

        from alembic import command
        command.upgrade(cfg, REVISION)

        assert _index_exists(engine)


def test_downgrade_drops_the_index():
    with _db_at_down_revision() as (engine, cfg):
        from alembic import command
        command.upgrade(cfg, REVISION)
        assert _index_exists(engine)

        command.downgrade(cfg, DOWN_REVISION)
        assert not _index_exists(engine)
