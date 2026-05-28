# tests/conftest.py
import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer


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


@pytest.fixture()
def admin_engine(db_admin_url: str):
    return create_engine(db_admin_url, future=True)


@pytest.fixture()
def admin_session(admin_engine) -> Iterator[Session]:
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    with SessionLocal() as s:
        yield s


@pytest.fixture()
def app_engine(db_admin_url: str):
    """Engine using the unprivileged 'app' role — exposes RBAC errors at the DB layer."""
    app_url = make_url(db_admin_url).set(username="app", password="app_pw")
    return create_engine(app_url.render_as_string(hide_password=False), future=True)


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
