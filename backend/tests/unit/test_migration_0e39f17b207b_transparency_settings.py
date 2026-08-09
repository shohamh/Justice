"""Tests for migration 0e39f17b207b (transparency settings rework)."""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from testcontainers.postgres import PostgresContainer

DOWN_REVISION = "5abac7d1ec0b"
REVISION = "0e39f17b207b"


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


def test_nonempty_old_array_migrates_to_most_senior_level():
    with _db_at_down_revision() as (engine, run_migration):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO hierarchy_level_types (id, key, label, rank) VALUES "
                "(gen_random_uuid(), 'אגף', 'אגף', 9000), (gen_random_uuid(), 'ענף', 'ענף', 9001)"
            ))
            conn.execute(text(
                "INSERT INTO system_settings (key, value) VALUES "
                "('transparency.visible_commander_levels', '[\"ענף\", \"אגף\"]'::jsonb)"
            ))
        run_migration()
        with engine.begin() as conn:
            row = conn.execute(text(
                "SELECT value FROM system_settings WHERE key = 'transparency.min_visible_level'"
            )).scalar()
            old_row = conn.execute(text(
                "SELECT value FROM system_settings WHERE key = 'transparency.visible_commander_levels'"
            )).scalar()
        assert row == "אגף"  # rank 9000 is more senior than rank 9001
        assert old_row is None


def test_empty_or_missing_old_value_migrates_to_default_level():
    with _db_at_down_revision() as (engine, run_migration):
        run_migration()
        with engine.begin() as conn:
            row = conn.execute(text(
                "SELECT value FROM system_settings WHERE key = 'transparency.min_visible_level'"
            )).scalar()
        assert row == "מדור"
