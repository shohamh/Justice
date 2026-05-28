from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.settings import get_settings


def _make_engine_factory() -> tuple[Engine, sessionmaker[Session]]:
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return engine, factory


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
