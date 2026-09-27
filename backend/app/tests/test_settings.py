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
