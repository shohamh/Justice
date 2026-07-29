from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import get_settings


def _make_engine_factory() -> tuple[Engine, sessionmaker[Session]]:
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        pool_size=20,
        max_overflow=10,
        pool_recycle=3600,
        pool_timeout=30,
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return engine, factory


_engine, SessionLocal = _make_engine_factory()


def reset_engine() -> None:
    """Rebuild the global engine/session factory from current settings.

    The engine above is built once at import time, so any process that
    imports this module (directly or transitively) before settings are
    finalized — e.g. a test file importing a route module during pytest
    collection, before fixtures patch DATABASE_URL — bakes in the wrong
    connection target. Callers that patch settings after the fact (tests)
    must call this — together with app.settings.get_settings.cache_clear()
    — to make the change take effect.
    """
    global _engine, SessionLocal
    _engine, SessionLocal = _make_engine_factory()


def get_session() -> Iterator[Session]:
    """FastAPI dependency — yields a session and closes it on request completion."""
    with SessionLocal() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standalone context manager for scripts and tests outside FastAPI."""
    with SessionLocal() as session:
        yield session
