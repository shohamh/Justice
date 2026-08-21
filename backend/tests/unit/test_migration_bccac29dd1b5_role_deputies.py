"""Tests for migration bccac29dd1b5 (create role_deputies table).

Uses the same throwaway-container pattern as
test_migration_15feab823caf_squad_level.py: the shared session-scoped
container in conftest.py is already migrated straight to head, so there's
no way to seed pre-migration state against it.
"""
import os
import uuid
from contextlib import contextmanager
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import IntegrityError
from testcontainers.postgres import PostgresContainer

DOWN_REVISION = "15feab823caf"
REVISION = "bccac29dd1b5"


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


def _insert_soldier(conn, *, personal_number):
    sid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO soldiers (id, personal_number, full_name, password_hash, role) "
            "VALUES (:id, :pn, 'Test', 'x', 'soldier')"
        ),
        {"id": sid, "pn": personal_number},
    )
    return sid


def test_upgrade_creates_table_with_working_constraints():
    with _db_at_down_revision() as (engine, run_migration):
        run_migration()

        with engine.begin() as conn:
            principal_id = _insert_soldier(conn, personal_number="dep-test-1")
            deputy_id = _insert_soldier(conn, personal_number="dep-test-2")
            conn.execute(
                text(
                    "INSERT INTO role_deputies (id, principal_id, deputy_id, role, start_date, end_date) "
                    "VALUES (gen_random_uuid(), :p, :d, 'commander', :s, :e)"
                ),
                {"p": principal_id, "d": deputy_id, "s": date(2026, 1, 1), "e": date(2026, 1, 31)},
            )

        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT role, start_date, end_date FROM role_deputies WHERE principal_id = :p"),
                {"p": principal_id},
            ).mappings().one()
        assert row["role"] == "commander"
        assert row["start_date"] == date(2026, 1, 1)
        assert row["end_date"] == date(2026, 1, 31)


def test_end_date_before_start_date_is_rejected():
    with _db_at_down_revision() as (engine, run_migration):
        run_migration()

        with engine.begin() as conn:
            principal_id = _insert_soldier(conn, personal_number="dep-test-3")
            deputy_id = _insert_soldier(conn, personal_number="dep-test-4")

        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO role_deputies (id, principal_id, deputy_id, role, start_date, end_date) "
                        "VALUES (gen_random_uuid(), :p, :d, 'commander', :s, :e)"
                    ),
                    {"p": principal_id, "d": deputy_id, "s": date(2026, 2, 1), "e": date(2026, 1, 1)},
                )
            assert False, "expected IntegrityError from the date-range check constraint"
        except IntegrityError:
            pass


def test_duplicate_principal_deputy_role_is_rejected():
    with _db_at_down_revision() as (engine, run_migration):
        run_migration()

        with engine.begin() as conn:
            principal_id = _insert_soldier(conn, personal_number="dep-test-5")
            deputy_id = _insert_soldier(conn, personal_number="dep-test-6")
            conn.execute(
                text(
                    "INSERT INTO role_deputies (id, principal_id, deputy_id, role, start_date, end_date) "
                    "VALUES (gen_random_uuid(), :p, :d, 'commander', :s, :e)"
                ),
                {"p": principal_id, "d": deputy_id, "s": date(2026, 1, 1), "e": date(2026, 1, 31)},
            )

        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO role_deputies (id, principal_id, deputy_id, role, start_date, end_date) "
                        "VALUES (gen_random_uuid(), :p, :d, 'commander', :s2, :e2)"
                    ),
                    {"p": principal_id, "d": deputy_id, "s2": date(2026, 3, 1), "e2": date(2026, 3, 31)},
                )
            assert False, "expected IntegrityError from the unique constraint"
        except IntegrityError:
            pass


def test_downgrade_drops_the_table():
    from alembic import command
    from alembic.config import Config

    with _db_at_down_revision() as (engine, run_migration):
        run_migration()

        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "alembic")
        command.downgrade(cfg, DOWN_REVISION)

        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT to_regclass('role_deputies')")
            ).scalar()
        assert exists is None
