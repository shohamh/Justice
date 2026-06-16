import pytest
from unittest.mock import patch
from app.settings import Settings


def test_cookie_secure_defaults_true():
    s = Settings(
        DATABASE_URL="postgresql+psycopg://x:y@localhost/z",
        DB_ADMIN_URL="postgresql+psycopg://x:y@localhost/z",
        JWT_SECRET="a" * 32,
        _env_file=None,
    )
    assert s.cookie_secure is True


def test_cookie_secure_can_be_disabled_for_dev():
    import os
    with patch.dict(os.environ, {"COOKIE_SECURE": "false"}):
        from app.settings import Settings as S2
        s = S2(
            DATABASE_URL="postgresql+psycopg://x:y@localhost/z",
            DB_ADMIN_URL="postgresql+psycopg://x:y@localhost/z",
            JWT_SECRET="a" * 32,
            _env_file=None,
        )
        assert s.cookie_secure is False
