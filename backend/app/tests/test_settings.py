import pytest

from app.settings import Settings


def test_hr_sync_enabled_false_when_unset(monkeypatch):
    monkeypatch.delenv("HR_API_BASE_URL", raising=False)
    monkeypatch.delenv("HR_API_KEY", raising=False)
    s = Settings(_env_file=None, DATABASE_URL="x", DB_ADMIN_URL="x", JWT_SECRET="x" * 32)
    assert s.hr_sync_enabled is False


def test_redis_url_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = Settings(_env_file=None, DATABASE_URL="x", DB_ADMIN_URL="x", JWT_SECRET="x" * 32)
    assert s.redis_url == "redis://localhost:6379/0"


def test_redis_url_reads_from_env():
    s = Settings(
        _env_file=None, DATABASE_URL="x", DB_ADMIN_URL="x", JWT_SECRET="x" * 32,
        REDIS_URL="redis://redis:6379/0",
    )
    assert s.redis_url == "redis://redis:6379/0"


def test_hr_sync_enabled_true_when_both_set(monkeypatch):
    s = Settings(
        _env_file=None,
        DATABASE_URL="x",
        DB_ADMIN_URL="x",
        JWT_SECRET="x" * 32,
        HR_API_BASE_URL="https://hr.example.internal",
        HR_API_KEY="secret",
    )
    assert s.hr_sync_enabled is True


def test_hr_sync_enabled_false_when_only_one_set(monkeypatch):
    monkeypatch.delenv("HR_API_KEY", raising=False)
    s = Settings(
        _env_file=None,
        DATABASE_URL="x",
        DB_ADMIN_URL="x",
        JWT_SECRET="x" * 32,
        HR_API_BASE_URL="https://hr.example.internal",
    )
    assert s.hr_sync_enabled is False


def test_storage_settings_are_typed_and_keep_credentials_secret():
    s = Settings(_env_file=None, DATABASE_URL="x", DB_ADMIN_URL="x", JWT_SECRET="x" * 32,
                 STORAGE_BUCKET="private-files", STORAGE_REGION="us-east-1",
                 STORAGE_ACCESS_KEY_ID="private-id", STORAGE_SECRET_ACCESS_KEY="private-secret")
    assert s.storage_bucket == "private-files"
    assert s.storage_secret_access_key.get_secret_value() == "private-secret"
    assert "private-secret" not in repr(s)


def test_http_storage_endpoint_rejected_outside_explicit_local_test_stub():
    with pytest.raises(ValueError):
        Settings(_env_file=None, DATABASE_URL="x", DB_ADMIN_URL="x", JWT_SECRET="x" * 32,
                 STORAGE_ENDPOINT_URL="http://storage.example.invalid")


def test_http_storage_endpoint_allowed_only_for_explicit_loopback_test_stub():
    s = Settings(_env_file=None, DATABASE_URL="x", DB_ADMIN_URL="x", JWT_SECRET="x" * 32,
                 STORAGE_LOCAL_TEST_STUB=True, STORAGE_ENDPOINT_URL="http://127.0.0.1:9000")
    assert s.storage_endpoint_url == "http://127.0.0.1:9000"
    with pytest.raises(ValueError):
        Settings(_env_file=None, DATABASE_URL="x", DB_ADMIN_URL="x", JWT_SECRET="x" * 32,
                 STORAGE_LOCAL_TEST_STUB=True, STORAGE_ENDPOINT_URL="http://storage.example.invalid")
